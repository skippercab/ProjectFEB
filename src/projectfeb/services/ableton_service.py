"""Ableton Live project file generation and manipulation service."""

import gzip
import gc
import json
import subprocess
import threading
import zipfile
import wave
import xml.etree.ElementTree as ET
import tkinter as tk
from pathlib import Path
from typing import ClassVar, Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from collections import defaultdict
from loguru import logger
import shutil
import tempfile
import os
import copy
import zlib
import re
from itertools import combinations
from tkinter import messagebox, ttk
import struct
import numpy as np

from ..core.config import AbletonConfig, default_output_buses
from ._audio_clip_template import create_audio_clip_template
from ._blank_audio_track import create_blank_audio_track_template
from ._blank_return_track import create_blank_return_track_template
from .multitracks_service import AudioStem, StemMatch

@dataclass
class AbletonTrack:
    """Represents an Ableton Live track."""
    id: str
    name: str
    track_type: str  # AudioTrack, MidiTrack, GroupTrack, etc.
    color: Optional[int] = None
    is_group_track: bool = False


class GenerationCancelledError(Exception):
    """Raised when the user cancels a required generation input."""

class AbletonService:
    """Service for working with Ableton Live project files."""

    TIME_SIGNATURE_FOUR_FOUR_VALUE = '201'
    TIME_SIGNATURE_SIX_EIGHT_VALUE = '302'
    KEY_OPTION_ORDER = ('AB', 'A', 'BB', 'B', 'C', 'DB', 'D', 'EB', 'E', 'F', 'GB', 'G')
    GUIDE_CUE_WINDOW_SECONDS = 0.03
    GUIDE_CUE_MIN_ACTIVE_SECONDS = 0.18
    GUIDE_CUE_MERGE_GAP_SECONDS = 1.0
    GUIDE_SECTION_MIN_DURATION_SECONDS = 2.0
    GUIDE_SECTION_MIN_SUBSEGMENTS = 2
    TEMPLATE_ARRANGEMENT_INTRO_BEATS = 20
    GUIDE_CUE_MAX_EXTRA_MATCHES = 3
    GUIDE_TRANSCRIPTION_MODEL = 'base.en'
    GUIDE_TRANSCRIPTION_EXACT_MATCH_SCORE = 3
    GUIDE_TRANSCRIPTION_WEAK_MATCH_SCORE = 1
    GUIDE_TRANSCRIPTION_STRUCTURAL_MATCH_BONUS = 2
    GUIDE_TRANSCRIPTION_CLOSE_MATCH_RATIO = 0.03
    GUIDE_TRANSCRIPTION_GUIDE_NATIVE_MARGIN = 6

    @staticmethod
    def _calculate_rms(frames: bytes, sample_width: int) -> int:
        """Calculate RMS value of audio frames. Replaces deprecated audioop.rms() for Python 3.13+."""
        if not frames or sample_width == 0:
            return 0
        fmt = {1: 'B', 2: 'h', 4: 'i'}.get(sample_width, 'h')
        sample_count = len(frames) // sample_width
        samples = struct.unpack(f'<{sample_count}{fmt}', frames)
        return int(np.sqrt(np.mean(np.array(samples, dtype=np.float64) ** 2)))
    GUIDE_TRANSCRIPTION_MIN_SPLIT_BEATS = 8.0
    GUIDE_TRANSCRIPTION_MEASURE_ALIGNMENT_TOLERANCE_BEATS = 1.0
    GUIDE_TRANSCRIPTION_MICRO_FRAGMENT_MEASURES = 0.75
    GUIDE_TRANSCRIPTION_MIN_MATCH_RATIO = 0.55
    GUIDE_TRANSCRIPTION_DUPLICATE_GAP_SECONDS = 4.0
    GUIDE_TRANSCRIPTION_GUIDE_NATIVE_EXTRA_SECTIONS = 2
    GUIDE_TRANSCRIPTION_MODIFIER_MERGE_GAP_SECONDS = 3.0
    GUIDE_TRANSCRIPTION_TINY_FRAGMENT_SECONDS = 4.0
    KEY_DISPLAY_NAMES = {
        'AB': 'Ab',
        'A': 'A',
        'BB': 'Bb',
        'B': 'B',
        'C': 'C',
        'DB': 'Db',
        'D': 'D',
        'EB': 'Eb',
        'E': 'E',
        'F': 'F',
        'GB': 'Gb',
        'G': 'G',
    }

    KEY_TO_SEMITONE = {
        'C': 0,
        'B#': 0,
        'C#': 1,
        'DB': 1,
        'D': 2,
        'D#': 3,
        'EB': 3,
        'E': 4,
        'FB': 4,
        'F': 5,
        'E#': 5,
        'F#': 6,
        'GB': 6,
        'G': 7,
        'G#': 8,
        'AB': 8,
        'A': 9,
        'A#': 10,
        'BB': 10,
        'B': 11,
        'CB': 11,
    }
    STEM_WARP_MODES = {
        'bass': 4,
        'leads': 4,
        'strings': 4,
        'keys': 4,
        'vocals': 6,
    }
    STEM_GROUP_ORDER = ('perc', 'bass', 'leads', 'strings', 'keys', 'vocals')
    STEM_GROUP_NAMES = {
        'perc': 'Perc',
        'bass': 'Bass',
        'leads': 'Lead',
        'strings': 'Strings',
        'keys': 'Keys',
        'vocals': 'Vocals',
    }
    OFF_SEND_LEVEL = 0.0003162277571

    @classmethod
    def validate_output_buses(cls, output_buses: Any) -> List[Dict[str, Any]]:
        """Validate and normalize logical bus configuration."""
        if not isinstance(output_buses, list) or not output_buses:
            raise ValueError('Output bus layout must be a non-empty list.')

        normalized: List[Dict[str, Any]] = []
        occupied_slots: set[int] = set()
        seen_roles: set[str] = set()
        content_lane_count = 0

        for raw_bus in output_buses:
            if not isinstance(raw_bus, dict):
                raise ValueError('Each output bus must be an object.')

            role = str(raw_bus.get('role', 'content')).strip().lower()
            mode = str(raw_bus.get('mode', 'mono')).strip().lower()
            name = str(raw_bus.get('name', '')).strip()

            try:
                slot = int(raw_bus.get('slot'))
            except (TypeError, ValueError):
                raise ValueError(f"Invalid bus slot '{raw_bus.get('slot')}'.")

            if slot < 1 or slot > 8:
                raise ValueError(f"Bus slot {slot} is outside the valid 1-8 range.")

            if role not in {'content', 'click', 'guide'}:
                raise ValueError(f"Unsupported bus role '{role}'.")

            if not name:
                raise ValueError(f"Bus in slot {slot} must have a name.")

            if role in {'click', 'guide'}:
                if role in seen_roles:
                    raise ValueError(f"Only one '{role}' bus can be defined.")
                seen_roles.add(role)
                mode = 'mono'
                tags: List[str] = []
            else:
                if mode not in {'mono', 'stereo'}:
                    raise ValueError(f"Unsupported content bus mode '{mode}' in slot {slot}.")
                tags = sorted({str(tag).strip().lower() for tag in raw_bus.get('tags', []) if str(tag).strip()})
                if not tags:
                    raise ValueError(f"Content bus '{name}' in slot {slot} must include at least one routing tag.")

            occupied_width = 2 if mode == 'stereo' else 1
            if mode == 'stereo' and (slot % 2 == 0 or slot + 1 > 8):
                raise ValueError(f"Stereo bus '{name}' must start on an odd slot with an adjacent pair.")

            for occupied_slot in range(slot, slot + occupied_width):
                if occupied_slot in occupied_slots:
                    raise ValueError(f"Bus '{name}' overlaps an existing assignment at slot {occupied_slot}.")
                occupied_slots.add(occupied_slot)

            if role == 'content':
                content_lane_count += occupied_width

            normalized.append({
                'slot': slot,
                'role': role,
                'mode': mode,
                'name': name,
                'tags': tags,
            })

        missing_roles = {'click', 'guide'} - seen_roles
        if missing_roles:
            missing = ', '.join(sorted(missing_roles))
            raise ValueError(f"Output bus layout must define: {missing}.")

        if content_lane_count > 6:
            raise ValueError('Content buses cannot consume more than 6 logical lanes total.')

        return sorted(normalized, key=lambda bus: (bus['slot'], bus['role'] != 'content'))

    def __init__(self, config: AbletonConfig):
        """Initialize the Ableton service.

        Args:
            config: Ableton configuration
        """
        self.config = config
        self.template_path = Path(config.template_path) if config.template_path else None
        self.output_folder = Path(config.output_folder) if config.output_folder else Path.home() / "Desktop"
        self.template_format = None  # Will be set to 'zip' or 'gzip' when loading template
        self.template_midi_clip = None  # Template MidiClip to use as base for copies
        self.template_six_eight_midi_clip = None  # Template 6/8 MidiClip to duplicate for meter changes
        self.template_four_four_midi_clip = None  # Template 4/4 MidiClip to duplicate for meter changes
        self.blank_audio_track_template = create_blank_audio_track_template()
        self.blank_return_track_template = create_blank_return_track_template()
        self.audio_clip_template = create_audio_clip_template()
        self.source_key_cache: Dict[str, Optional[str]] = {}
        self.song_bpm_cache: Dict[str, float] = {}
        self.target_key_cache: Dict[str, Optional[str]] = {}
        self.ui_thread_dispatcher: Optional[Callable[[Callable[[], Any]], Any]] = None
        self.status_reporter: Optional[Callable[[str], None]] = None
        self.guide_cue_cache: Dict[str, List[float]] = {}
        self.guide_transcription_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.guide_transcription_model = None
        self.guide_transcription_unavailable = False
        self.output_buses = self._load_output_buses()
        self.active_return_buses: List[Dict[str, Any]] = []
        self.return_bus_indexes: Dict[str, int] = {}

        # Ensure output folder exists
        self.output_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"Ableton service initialized with template: {self.template_path}")

    def _load_output_buses(self) -> List[Dict[str, Any]]:
        """Load normalized bus layout from config, falling back to defaults if needed."""
        try:
            return self.validate_output_buses(self.config.output_buses)
        except ValueError as exc:
            logger.warning(f"Invalid output bus layout in config, using defaults: {exc}")
            return self.validate_output_buses(default_output_buses())

    def _run_on_ui_thread(self, callback: Callable[[], Any]) -> Any:
        """Run a callback on the UI thread when generation is happening in a worker thread."""
        if self.ui_thread_dispatcher is not None and threading.current_thread() is not threading.main_thread():
            return self.ui_thread_dispatcher(callback)
        return callback()

    def _report_status(self, message: str) -> None:
        """Send a concise progress update to the UI when a reporter is configured."""
        if self.status_reporter is None:
            return

        self._run_on_ui_thread(lambda: self.status_reporter(message))

    def shutdown(self) -> None:
        """Release heavyweight model resources before interpreter shutdown."""
        model_wrapper = self.guide_transcription_model
        self.guide_transcription_model = None
        self.status_reporter = None

        if model_wrapper is None:
            return

        backend_model = getattr(model_wrapper, 'model', None)
        unload_model = getattr(backend_model, 'unload_model', None)
        if callable(unload_model):
            try:
                unload_model(False)
            except Exception as exc:
                logger.debug(f"Failed to unload guide transcription backend cleanly: {exc}")

        del model_wrapper
        gc.collect()

    def generate_setlist(self, service_type_name: str, service_date, stem_matches: Dict[str, StemMatch], plan_songs: Optional[List] = None) -> Optional[Path]:
        """Generate an Ableton Live setlist from stem matches.

        Args:
            service_type_name: Name of the service type (e.g., "SMC Weekend Services")
            service_date: Date of the service (datetime object)
            stem_matches: Dictionary of song titles to stem matches
            plan_songs: Optional ordered list of PCOSong objects with key information

        Returns:
            Path to the project folder, or None if failed
        """
        if not self.template_path or not self.template_path.exists():
            logger.error(f"Template file not found: {self.template_path}")
            return None

        try:
            self.song_bpm_cache = {}
            self.target_key_cache = {}
            song_count = len(plan_songs or [])

            self._report_status("Preparing Ableton template...")

            # Load and parse the template
            template_tree = self._load_template()
            if not template_tree:
                return None

            # Convert to target Ableton version if needed
            self._convert_version(template_tree)

            # Create a project title for the Ableton window from service type and date
            project_title = f"{service_type_name} {service_date.strftime('%Y-%m-%d')}"
            
            # Save the new project file
            als_file_path = self._generate_output_path(service_type_name, service_date)

            # Modify the template with service data
            if song_count:
                self._report_status(f"Building setlist for {song_count} songs...")
            else:
                self._report_status("Building setlist structure...")
            self._populate_setlist(template_tree, project_title, stem_matches, plan_songs, als_file_path)

            self._report_status("Saving Ableton setlist...")
            self._save_project(template_tree, als_file_path)
            self._report_status("Setlist ready.")

            logger.info(f"Generated setlist: {als_file_path}")
            return als_file_path

        except GenerationCancelledError as e:
            logger.warning(f"Setlist generation cancelled: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate setlist: {e}")
            return None

    def _load_template(self) -> Optional[ET.ElementTree]:
        """Load and parse the Ableton template file from ZIP or gzip format."""
        try:
            # Try to open as ZIP first (modern .als format)
            try:
                with zipfile.ZipFile(self.template_path, 'r') as zip_file:
                    file_list = zip_file.namelist()
                    logger.debug(f"Files in template ZIP: {file_list}")

                    # Look for the main project file (usually Ableton/Project.xml)
                    project_xml_path = None
                    for file_path in file_list:
                        if file_path.endswith('Project.xml'):
                            project_xml_path = file_path
                            break

                    if not project_xml_path:
                        # Fallback: look for any .xml file
                        for file_path in file_list:
                            if file_path.endswith('.xml'):
                                project_xml_path = file_path
                                break

                    if not project_xml_path:
                        logger.error("No Project.xml found in template ZIP")
                        return None

                    # Read the XML content
                    with zip_file.open(project_xml_path) as xml_file:
                        content = xml_file.read()

                    # Parse XML
                    root = ET.fromstring(content)
                    tree = ET.ElementTree(root)

                    self.template_format = 'zip'
                    self._extract_template_midi_clip(root)
                    logger.info(f"Template loaded successfully from ZIP: {project_xml_path}")
                    return tree

            except zipfile.BadZipFile:
                # Not a ZIP file, try gzip format
                logger.debug("Template is not a ZIP file, trying gzip format...")
                with gzip.open(self.template_path, 'rb') as f:
                    content = f.read()

                # Parse XML
                root = ET.fromstring(content)
                tree = ET.ElementTree(root)

                self.template_format = 'gzip'
                self._extract_template_midi_clip(root)
                logger.info("Template loaded successfully from gzip format")
                return tree

        except Exception as e:
            logger.error(f"Failed to load template: {e}")
            return None

    def _extract_template_midi_clip(self, root: ET.Element) -> None:
        """Extract reusable template MidiClips from the source template.
        
        The INTRO clip is used as the base for section clips, and the parked 6/8
        clip is reused for songs that need a meter change overlay.
        """
        self.template_midi_clip = None
        self.template_six_eight_midi_clip = None
        self.template_four_four_midi_clip = None

        try:
            fallback_clip = None

            # Find the INTRO MidiClip in ArrangerAutomation/Events
            for midi_track in root.findall('.//MidiTrack'):
                clip_timeable = midi_track.find('.//ClipTimeable')
                if clip_timeable is not None:
                    events = clip_timeable.find('.//ArrangerAutomation/Events')
                    if events is not None:
                        for midi_clip in events.findall('MidiClip'):
                            if fallback_clip is None:
                                fallback_clip = midi_clip

                            name_elem = midi_clip.find('Name')
                            if name_elem is not None:
                                clip_name = name_elem.get('Value', '')
                                if clip_name == 'INTRO':
                                    self.template_midi_clip = copy.deepcopy(midi_clip)
                                    logger.info(f"Extracted working template INTRO MidiClip: Id={midi_clip.get('Id')}")

                                if clip_name == '6/8':
                                    self.template_six_eight_midi_clip = copy.deepcopy(midi_clip)
                                    logger.info(f"Extracted template 6/8 MidiClip: Id={midi_clip.get('Id')}")

                                if clip_name == '4/4':
                                    self.template_four_four_midi_clip = copy.deepcopy(midi_clip)
                                    logger.info(f"Extracted template 4/4 MidiClip: Id={midi_clip.get('Id')}")

            if self.template_midi_clip is None and fallback_clip is not None:
                name_elem = fallback_clip.find('Name')
                clip_name = name_elem.get('Value', 'unknown') if name_elem is not None else 'unknown'
                self.template_midi_clip = copy.deepcopy(fallback_clip)
                logger.info(
                    f"Extracted template MidiClip (fallback): Id={fallback_clip.get('Id')}, Name={clip_name}"
                )
        except Exception as e:
            logger.warning(f"Failed to extract template MidiClip: {e}")

    def _convert_version(self, tree: ET.ElementTree) -> None:
        """Convert the Ableton project version if needed."""
        root = tree.getroot()

        # Check current version
        current_version = root.get('MinorVersion', '')
        target_version = self.config.version

        if current_version != target_version:
            logger.info(f"Converting from version {current_version} to {target_version}")
            root.set('MinorVersion', target_version)

            # Update Creator if present
            if root.get('Creator'):
                root.set('Creator', 'Ableton Live 11.3.43')

    def _populate_setlist(
        self,
        tree: ET.ElementTree,
        service_title: str,
        stem_matches: Dict[str, StemMatch],
        plan_songs: Optional[List] = None,
        als_file_path: Optional[Path] = None,
    ) -> None:
        """Populate the template with service data - title, song markers, guides, and MIDI clips."""
        root = tree.getroot()

        # Find the LiveSet element
        liveset = root.find('LiveSet')
        if liveset is None:
            logger.error("No LiveSet element found in template")
            return

        # Update the project title
        self._set_project_title(liveset, service_title)
        logger.info(f"Set project title to: {service_title}")

        # Replace existing placeholder markers with actual song titles
        self._populate_existing_markers(liveset, stem_matches, plan_songs)

        # Rebuild logical return buses from the saved output layout.
        self._prepare_output_buses(liveset)
        
        # Add guide stems and MIDI clips for each song (if arrangement data available)
        if plan_songs:
            self._add_guides_and_midi_clips(liveset, stem_matches, plan_songs, als_file_path)
            # Add tempo mapping for each song
            self._add_tempo_mapping(liveset, plan_songs)
            self._add_time_signature_mapping(liveset, plan_songs)

    def _prepare_output_buses(self, liveset: ET.Element) -> None:
        """Rebuild return buses from config so generation does not depend on template returns."""
        tracks = liveset.find('.//Tracks')
        if tracks is None:
            logger.warning('No Tracks element found; cannot rebuild return buses')
            self.active_return_buses = []
            self.return_bus_indexes = {}
            return

        active_buses = [dict(bus) for bus in self.output_buses]
        if self.config.enable_sub_master:
            active_buses.append({
                'slot': 99,
                'role': 'sub_master',
                'mode': 'mono',
                'name': self.config.sub_master_bus_name or 'Sub Master',
                'tags': [],
            })

        self._remove_existing_return_tracks(tracks)
        self.active_return_buses = []

        insert_index = self._get_generated_track_insert_index(tracks)
        for bus in active_buses:
            new_return_track = self._create_return_track(
                liveset,
                tracks,
                bus['name'],
                insert_index,
                muted=bus['role'] == 'sub_master',
            )
            if new_return_track is None:
                continue

            bus['send_index'] = len(self.active_return_buses)
            self.active_return_buses.append(bus)
            insert_index += 1

        send_count = len(self.active_return_buses)
        self.return_bus_indexes = {
            bus['role']: bus['send_index']
            for bus in self.active_return_buses
            if bus['role'] in {'click', 'guide', 'sub_master'}
        }

        if send_count > 0:
            self._sync_sends_pre(liveset, send_count)
            self._ensure_tracks_send_count(liveset, tracks, send_count)
            self._configure_click_track_routing(tracks)
            self._configure_existing_guide_track_routing(tracks)
            self._configure_existing_pads_group_routing(tracks)
            self._update_next_pointee_id(liveset)
        else:
            self._sync_sends_pre(liveset, 0)

    def _remove_existing_return_tracks(self, tracks: ET.Element) -> None:
        """Remove all return tracks so the configured bus layout becomes the source of truth."""
        for child in list(tracks):
            if child.tag == 'ReturnTrack':
                tracks.remove(child)

    def _sync_sends_pre(self, liveset: ET.Element, send_count: int) -> None:
        """Keep LiveSet/SendsPre aligned with the active return-bus count."""
        sends_pre = liveset.find('SendsPre')
        if sends_pre is None:
            sends_pre = ET.Element('SendsPre')
            insert_index = next((index for index, child in enumerate(list(liveset)) if child.tag == 'Scenes'), len(list(liveset)))
            liveset.insert(insert_index, sends_pre)

        for child in list(sends_pre):
            sends_pre.remove(child)

        next_id = self._next_available_id(liveset)
        for _ in range(send_count):
            send_pre_bool = ET.SubElement(sends_pre, 'SendPreBool')
            send_pre_bool.set('Id', str(next_id))
            send_pre_bool.set('Value', 'false')
            next_id += 1

    def _create_return_track(
        self,
        liveset: ET.Element,
        tracks: ET.Element,
        track_name: str,
        insert_index: int,
        muted: bool = False,
    ) -> Optional[ET.Element]:
        """Create a generated return bus from the embedded ReturnTrack template."""
        try:
            new_track = copy.deepcopy(self.blank_return_track_template)
            next_id = self._next_available_id(liveset)
            new_track.set('Id', str(next_id))
            next_id += 1

            next_id = self._remap_audio_track_internal_ids(new_track, next_id)
            self._set_track_name(new_track, track_name)
            self._set_track_volume(new_track, 1.0)
            self._set_track_muted(new_track, muted)
            self._set_track_group_id(new_track, None)
            self._set_audio_output_routing(new_track, 'AudioOut/Master', 'Master')

            for selected_elem in new_track.iter('IsContentSelectedInDocument'):
                selected_elem.set('Value', 'false')

            tracks.insert(insert_index, new_track)
            return new_track

        except Exception as exc:
            logger.error(f"Failed to create return track '{track_name}': {exc}", exc_info=True)
            return None

    def _ensure_tracks_send_count(self, liveset: ET.Element, tracks: ET.Element, send_count: int) -> None:
        """Ensure every routable track has enough send holders for the generated buses."""
        for child in tracks:
            if child.tag not in {'AudioTrack', 'MidiTrack', 'GroupTrack', 'ReturnTrack'}:
                continue

            self._resize_track_sends(child, send_count, liveset)

    def _configure_click_track_routing(self, tracks: ET.Element) -> None:
        """Route the template click track to the configured click bus when present."""
        send_indexes = self._special_bus_send_indexes('click')
        if not send_indexes:
            return

        for track in tracks.findall('MidiTrack'):
            if 'click' not in self._get_track_name(track).lower():
                continue

            self._configure_track_send_routing(track, send_indexes)
    def _configure_existing_pads_group_routing(self, tracks: ET.Element) -> None:
        """Route the template PADS group to the selected content bus.

        Pads can be assigned explicitly via the `pads` tag, but older configs should
        still land on synth/keys style returns without requiring an immediate settings edit.
        """
        for track in tracks.findall('GroupTrack'):
            if self._get_track_name(track).strip().lower() != 'pads':
                continue

            content_bus = self._resolve_content_bus_for_tags(['pads', 'synth', 'keys'])
            if content_bus is None:
                logger.warning("No configured content bus matched the template PADS group")
                return

            send_indexes = [content_bus['send_index']]
            sub_master_index = self.return_bus_indexes.get('sub_master')
            if sub_master_index is not None:
                send_indexes.append(sub_master_index)

            self._configure_track_send_routing(track, send_indexes)
            return

    def _configure_existing_guide_track_routing(self, tracks: ET.Element) -> None:
        """Route an existing template guide track to the configured guide bus if present."""
        send_indexes = self._special_bus_send_indexes('guide')
        if not send_indexes:
            return

        for track in tracks.findall('AudioTrack'):
            if self._get_track_name(track).strip().lower() != 'guide':
                continue

            self._configure_track_send_routing(track, send_indexes)
            return

    def _populate_existing_markers(self, liveset: ET.Element, stem_matches: Dict[str, StemMatch], plan_songs: Optional[List] = None) -> None:
        """Populate song locators and expand slots beyond 4 songs when needed."""
        # Find the Locators element
        locators = liveset.find("Locators")
        if locators is None:
            logger.warning("No Locators element found in template")
            return

        locators_list = locators.find("Locators")
        if locators_list is None:
            logger.warning("No Locators/Locators element found in template")
            return

        # Get all existing locator elements
        existing_locators = locators_list.findall("Locator")
        logger.info(f"Found {len(existing_locators)} total markers in template")

        # Get songs in API order if available (from plan_songs), otherwise use sorted stems
        songs_with_keys: List[tuple[str, str]] = []
        if plan_songs:
            # Use the ordered songs from the plan
            for song in plan_songs:
                key_suffix = f" ({song.key_name})" if song.key_name else ""
                songs_with_keys.append((song.title, key_suffix))
            logger.info(f"Using {len(songs_with_keys)} songs in API order")
        else:
            # Fallback to alphabetically sorted stems
            sorted_songs = sorted(stem_matches.keys())
            songs_with_keys = [(title, "") for title in sorted_songs]
            logger.info(f"Using {len(songs_with_keys)} songs in alphabetical order (no plan_songs provided)")

        if not songs_with_keys:
            return

        # Index current placeholder locators by numeric slot, e.g. "1)", "2)", ...
        placeholder_locators: Dict[int, ET.Element] = {}
        for locator in existing_locators:
            name_elem = locator.find("Name")
            if name_elem is None:
                continue
            marker_name = name_elem.get('Value', '').strip()
            match = re.fullmatch(r'(\d+)\)', marker_name)
            if not match:
                continue
            placeholder_locators[int(match.group(1))] = locator

        if not placeholder_locators:
            logger.warning("No numeric placeholder markers found in template")
            return

        # Replace existing placeholders with song names for available slots.
        for slot, locator in sorted(placeholder_locators.items()):
            if slot > len(songs_with_keys):
                continue
            name_elem = locator.find("Name")
            if name_elem is None:
                continue
            song_title, key_suffix = songs_with_keys[slot - 1]
            new_name = f"{slot}) {song_title}{key_suffix}"
            name_elem.set('Value', new_name)
            logger.info(f"Replaced placeholder '{slot})' with '{new_name}'")

        # Expand template spacing only when we have more songs than existing placeholder slots.
        max_template_slot = max(placeholder_locators)
        if len(songs_with_keys) <= max_template_slot:
            return

        # We intentionally insert extra slots between song 4 and LOOP when available.
        anchor_slot = 4 if 4 in placeholder_locators else max_template_slot
        anchor_locator = placeholder_locators.get(anchor_slot)
        if anchor_locator is None:
            return

        anchor_time_elem = anchor_locator.find("Time")
        if anchor_time_elem is None:
            logger.warning("Anchor song marker has no Time element; cannot expand markers")
            return

        try:
            anchor_time = float(anchor_time_elem.get('Value', '0'))
        except ValueError:
            logger.warning("Anchor song marker has invalid Time value; cannot expand markers")
            return

        loop_boundary = None
        for locator in existing_locators:
            name_elem = locator.find("Name")
            time_elem = locator.find("Time")
            if name_elem is None or time_elem is None:
                continue

            locator_name = name_elem.get('Value', '').strip().lower()
            if not locator_name.startswith('loop'):
                continue

            try:
                locator_time = float(time_elem.get('Value', '0'))
            except ValueError:
                continue

            if locator_time > anchor_time and (loop_boundary is None or locator_time < loop_boundary):
                loop_boundary = locator_time

        if loop_boundary is None:
            logger.warning("No LOOP marker found after song 4; cannot expand extra song slots")
            return

        slot_width = loop_boundary - anchor_time
        if slot_width <= 0:
            logger.warning("Invalid slot width between song 4 and LOOP; cannot expand extra song slots")
            return

        extra_slots = len(songs_with_keys) - anchor_slot
        shift_amount = slot_width * extra_slots

        # Push everything at/after the loop boundary forward to make room.
        for locator in existing_locators:
            time_elem = locator.find("Time")
            if time_elem is None:
                continue
            try:
                locator_time = float(time_elem.get('Value', '0'))
            except ValueError:
                continue
            if locator_time >= loop_boundary:
                new_time = locator_time + shift_amount
                time_elem.set('Value', str(int(new_time) if new_time.is_integer() else new_time))

        # Add new song locators for slots beyond the template capacity.
        current_max_id = max(
            (
                int(locator.get('Id', '0'))
                for locator in existing_locators
                if str(locator.get('Id', '0')).isdigit()
            ),
            default=0,
        )

        for slot in range(anchor_slot + 1, len(songs_with_keys) + 1):
            song_title, key_suffix = songs_with_keys[slot - 1]
            marker_name = f"{slot}) {song_title}{key_suffix}"
            marker_time = anchor_time + (slot - anchor_slot) * slot_width

            current_max_id += 1
            locator = ET.SubElement(locators_list, "Locator")
            locator.set('Id', str(current_max_id))

            lom_id = ET.SubElement(locator, "LomId")
            lom_id.set('Value', '0')

            time_elem = ET.SubElement(locator, "Time")
            time_elem.set('Value', str(int(marker_time) if marker_time.is_integer() else marker_time))

            name_elem = ET.SubElement(locator, "Name")
            name_elem.set('Value', marker_name)

            annotation_elem = ET.SubElement(locator, "Annotation")
            annotation_elem.set('Value', '')

            logger.info(f"Added expanded marker '{marker_name}' at beat {time_elem.get('Value')}")

    def _set_project_title(self, liveset: ET.Element, title: str) -> None:
        """Set the project title in the LiveSet."""
        # Look for MasterTrack to set the project title
        master_track = liveset.find(".//MasterTrack")
        if master_track is not None:
            name_elem = master_track.find(".//Name")
            if name_elem is not None:
                # Update the EffectiveName
                effective_name = name_elem.find("EffectiveName")
                if effective_name is not None:
                    effective_name.set('Value', title)

                # Update UserName
                user_name = name_elem.find("UserName")
                if user_name is not None:
                    user_name.set('Value', title)

    def _add_song_marker(self, liveset: ET.Element, song_title: str, time_position: float) -> None:
        """Add a marker for song start with proper Ableton Locator structure."""
        # Find or create Locators element
        locators = liveset.find("Locators")
        if locators is None:
            locators = ET.SubElement(liveset, "Locators")

        # Find or create nested Locators list
        locators_list = locators.find("Locators")
        if locators_list is None:
            locators_list = ET.SubElement(locators, "Locators")

        # Count existing locators to get the next ID
        existing_locators = locators_list.findall("Locator")
        locator_id = len(existing_locators)

        # Create a new Locator element with proper structure
        locator = ET.SubElement(locators_list, "Locator")
        locator.set('Id', str(locator_id))

        # Add LomId (required element)
        lom_id = ET.SubElement(locator, "LomId")
        lom_id.set('Value', '0')

        # Add Time value
        time_elem = ET.SubElement(locator, "Time")
        time_elem.set('Value', str(int(time_position)))

        # Add Name
        name_elem = ET.SubElement(locator, "Name")
        name_elem.set('Value', song_title)

        # Add Annotation
        annotation_elem = ET.SubElement(locator, "Annotation")
        annotation_elem.set('Value', '')

        logger.debug(f"Added locator: {song_title} at beat {time_position} with ID {locator_id}")

    def _add_guides_and_midi_clips(
        self,
        liveset: ET.Element,
        stem_matches: Dict[str, StemMatch],
        plan_songs: List,
        als_file_path: Optional[Path],
    ) -> None:
        """Add guide stems, routed audio stem tracks, and MIDI clips for each song."""
        locators_map = self._get_locators_map(liveset)

        logger.info(f"Starting to add guides and MIDI clips for {len(plan_songs)} songs")
        logger.info(f"Found {len(locators_map)} song markers: {list(locators_map.keys())}")

        tracks = liveset.find(".//Tracks")
        if tracks is None:
            logger.error("No Tracks element found")
            return

        guide_track_idx = self._find_track_by_name(tracks, "Guide")
        midi_track_idx = self._create_arrangement_track(tracks)
        shared_guide_audio_track = None

        if guide_track_idx is None:
            logger.warning("Guide track not found, will create a shared audio track for guide wavs")
        if midi_track_idx is None:
            logger.warning("Failed to create arrangement track")

        # Snapshot existing click colors before replacing template meter clips.
        song_colors_by_start: Dict[float, Optional[str]] = {}
        for song_idx, song in enumerate(plan_songs):
            marker_key = self._song_marker_key(song_idx, song)
            song_start_beat = locators_map.get(marker_key)
            if song_start_beat is None:
                continue
            song_colors_by_start[song_start_beat] = self._get_song_color_from_click_track(tracks, song_start_beat)

        self._remove_named_midi_clips(tracks, '6/8')
        self._remove_named_midi_clips(tracks, '4/4')

        for song_idx, song in enumerate(plan_songs):
            self._report_status(f"Building song {song_idx + 1}/{len(plan_songs)}: {song.title}")

            marker_key = self._song_marker_key(song_idx, song)

            if marker_key not in locators_map:
                logger.warning(f"Marker '{marker_key}' not found in template")
                continue

            song_start_beat = locators_map[marker_key]
            logger.info(f"Song {song_idx + 1} '{song.title}' starts at beat {song_start_beat}")

            bpm = self._resolve_song_bpm(song)
            stem_match = stem_matches.get(song.title)
            primary_guide_wav = self._select_primary_guide_wav(stem_match.stems) if stem_match is not None else None
            song_color = song_colors_by_start.get(song_start_beat)

            self._add_meter_signature_clip_for_song(
                tracks,
                plan_songs,
                locators_map,
                song_idx,
                song,
                song_start_beat,
                primary_guide_wav,
                bpm,
                song_color,
            )

            if stem_match is None:
                logger.warning(f"Song '{song.title}' not in stem matches, skipping guide/audio/MIDI sections")
                continue

            if song_color is None:
                song_color = self._get_song_color_from_click_track(tracks, song_start_beat)
            song_source_key = self._resolve_song_source_key(song, stem_match.stems)
            song_target_key = self._resolve_song_target_key(song, stem_match.stems, song_source_key)
            song_pitch_shift = self._calculate_song_pitch_shift(song_source_key, song_target_key)
            if song_source_key is not None and song_target_key is not None:
                logger.info(
                    f"Key mapping for '{song.title}': {song_source_key} -> {song_target_key} ({song_pitch_shift:+d} st)"
                )

            if primary_guide_wav and als_file_path is not None:
                logger.info(f"Adding guide wav for '{song.title}' at beat {song_start_beat}: {primary_guide_wav.filename}")
                if shared_guide_audio_track is None:
                    shared_guide_audio_track = self._create_guide_audio_track(liveset, tracks, "Guide")

                if shared_guide_audio_track is not None:
                    self._add_audio_clip_to_track(
                        shared_guide_audio_track,
                        primary_guide_wav,
                        song_start_beat,
                        bpm,
                        als_file_path,
                        song_color,
                        pitch_shift=song_pitch_shift,
                    )
            elif guide_track_idx is not None:
                guide_stem = self._select_primary_guide_stem(stem_match.stems)
                if guide_stem is not None:
                    logger.info(f"Adding fallback guide stem for '{song.title}' at beat {song_start_beat}")
                    self._add_guide_stem_to_track(tracks, guide_track_idx, guide_stem, song_start_beat)
                else:
                    logger.debug(f"No guide stem found for '{song.title}'")

            if als_file_path is not None:
                audio_stems = self._select_song_audio_wavs(stem_match.stems)
                if audio_stems and not self._add_grouped_song_audio_tracks(
                    liveset,
                    tracks,
                    song.title,
                    audio_stems,
                    song_start_beat,
                    bpm,
                    als_file_path,
                    song_color,
                    song_pitch_shift,
                ):
                    self._add_flat_song_audio_tracks(
                        liveset,
                        tracks,
                        song.title,
                        audio_stems,
                        song_start_beat,
                        bpm,
                        als_file_path,
                        song_color,
                        song_pitch_shift,
                    )

            if midi_track_idx is not None and song.arrangement and song.arrangement.sequence:
                logger.info(f"Adding MIDI clips for '{song.title}' with {len(song.arrangement.sequence)} sections")
                self._add_midi_clips_for_song(tracks, midi_track_idx, song, song_start_beat, primary_guide_wav, bpm)

    def _add_tempo_mapping(self, liveset: ET.Element, plan_songs: List) -> None:
        """Add tempo automation events for each song based on their BPM values."""
        try:
            # Get locators to find song start positions
            locators_map = self._get_locators_map(liveset)
            
            # Find the MasterTrack which contains the tempo automation
            master_track = liveset.find(".//MasterTrack")
            if master_track is None:
                logger.warning("No MasterTrack found, skipping tempo mapping")
                return
            
            # Find the AutomationEnvelopes element
            auto_envelopes = master_track.find(".//AutomationEnvelopes")
            if auto_envelopes is None:
                logger.warning("No AutomationEnvelopes found in MasterTrack")
                return
            
            # Find the Envelopes container
            envelopes_container = auto_envelopes.find("Envelopes")
            if envelopes_container is None:
                logger.warning("No Envelopes container found in AutomationEnvelopes")
                return
            
            # Find the tempo automation envelope (PointeeId="8" points to Tempo target)
            tempo_envelope = None
            for envelope in envelopes_container.findall("AutomationEnvelope"):
                target = envelope.find("EnvelopeTarget/PointeeId")
                if target is not None and target.get("Value") == "8":
                    tempo_envelope = envelope
                    break
            
            if tempo_envelope is None:
                logger.warning("Tempo automation envelope not found, skipping tempo mapping")
                return
            
            # Get the Events container
            automation = tempo_envelope.find("Automation")
            if automation is None:
                logger.warning("No Automation element in tempo envelope")
                return
            
            events = automation.find("Events")
            if events is None:
                logger.warning("No Events element in tempo automation")
                return
            
            # Clear all existing FloatEvent entries and rebuild them
            for event in events.findall("FloatEvent"):
                events.remove(event)
            
            # Collect all BPM values from songs
            song_bpms = []
            for song_idx, song in enumerate(plan_songs):
                resolved_bpm = self._resolve_song_bpm(song)
                song_bpms.append(resolved_bpm)
                logger.info(f"Song {song_idx + 1} '{song.title}' BPM: {resolved_bpm}")
            
            # Create new tempo events for each song
            # Start with initial BPM at very early time
            event_id = 0
            initial_event = ET.Element("FloatEvent")
            initial_event.set("Id", str(event_id))
            initial_event.set("Time", "-63072000")  # Very early, before song starts
            initial_event.set("Value", str(song_bpms[0]))
            events.append(initial_event)
            event_id += 1
            
            # For each subsequent song, create tempo ramp events at transition points
            for song_idx in range(1, len(plan_songs)):
                song = plan_songs[song_idx]
                
                # Find the marker name for this song
                marker_key = f"{song_idx + 1}) {song.title}"
                if song.key_name:
                    marker_key += f" ({song.key_name})"
                
                if marker_key not in locators_map:
                    logger.warning(f"Marker '{marker_key}' not found, skipping tempo event")
                    continue
                
                song_start_beat = locators_map[marker_key]
                prev_bpm = song_bpms[song_idx - 1]
                curr_bpm = song_bpms[song_idx]
                
                # Create two events at this beat for smooth tempo ramp:
                # First event: keep previous BPM (smooth transition start)
                ramp_start = ET.Element("FloatEvent")
                ramp_start.set("Id", str(event_id))
                ramp_start.set("Time", str(int(song_start_beat)))
                ramp_start.set("Value", str(prev_bpm))  # Keep original value (may be decimal)
                events.append(ramp_start)
                event_id += 1
                
                # Second event: new song BPM (ramp target)
                ramp_end = ET.Element("FloatEvent")
                ramp_end.set("Id", str(event_id))
                ramp_end.set("Time", str(int(song_start_beat)))
                ramp_end.set("Value", str(curr_bpm))  # Keep original value (may be decimal)
                events.append(ramp_end)
                event_id += 1
                
                logger.info(f"Added tempo ramp at beat {song_start_beat}: {prev_bpm} → {curr_bpm} for '{song.title}'")
                
        except Exception as e:
            logger.error(f"Failed to add tempo mapping: {e}")

    def _time_signature_value_for_meter(self, meter: Optional[str]) -> str:
        """Map supported song meters to Ableton master-envelope enum values."""
        if self._is_six_eight_meter(meter):
            return self.TIME_SIGNATURE_SIX_EIGHT_VALUE
        return self.TIME_SIGNATURE_FOUR_FOUR_VALUE

    def _add_time_signature_mapping(self, liveset: ET.Element, plan_songs: List) -> None:
        """Add master time-signature automation events so the top ruler matches song meters."""
        try:
            locators_map = self._get_locators_map(liveset)

            master_track = liveset.find('.//MasterTrack')
            if master_track is None:
                logger.warning('No MasterTrack found, skipping time-signature mapping')
                return

            auto_envelopes = master_track.find('.//AutomationEnvelopes')
            if auto_envelopes is None:
                logger.warning('No AutomationEnvelopes found in MasterTrack')
                return

            envelopes_container = auto_envelopes.find('Envelopes')
            if envelopes_container is None:
                logger.warning('No Envelopes container found in AutomationEnvelopes')
                return

            time_signature_envelope = None
            for envelope in envelopes_container.findall('AutomationEnvelope'):
                target = envelope.find('EnvelopeTarget/PointeeId')
                if target is not None and target.get('Value') == '10':
                    time_signature_envelope = envelope
                    break

            if time_signature_envelope is None:
                logger.warning('Time-signature automation envelope not found, skipping meter mapping')
                return

            automation = time_signature_envelope.find('Automation')
            if automation is None:
                logger.warning('No Automation element in time-signature envelope')
                return

            events = automation.find('Events')
            if events is None:
                logger.warning('No Events element in time-signature automation')
                return

            for event in list(events.findall('EnumEvent')):
                events.remove(event)

            initial_meter = plan_songs[0].arrangement.meter if plan_songs and plan_songs[0].arrangement else None
            initial_event = ET.Element('EnumEvent')
            initial_event.set('Id', '0')
            initial_event.set('Time', '-63072000')
            initial_event.set('Value', self._time_signature_value_for_meter(initial_meter))
            events.append(initial_event)

            event_id = 1
            for song_idx in range(1, len(plan_songs)):
                song = plan_songs[song_idx]
                marker_key = self._song_marker_key(song_idx, song)
                song_start_beat = locators_map.get(marker_key)
                if song_start_beat is None:
                    logger.warning(f"Marker '{marker_key}' not found, skipping time-signature event")
                    continue

                meter = song.arrangement.meter if song.arrangement else None
                event = ET.Element('EnumEvent')
                event.set('Id', str(event_id))
                event.set('Time', self._format_beat_value(song_start_beat))
                event.set('Value', self._time_signature_value_for_meter(meter))
                events.append(event)
                event_id += 1

                logger.info(
                    f"Added time-signature event at beat {song_start_beat}: {meter or '4/4'} for '{song.title}'"
                )

        except Exception as e:
            logger.error(f"Failed to add time-signature mapping: {e}")

    def _get_locators_map(self, liveset: ET.Element) -> Dict[str, float]:
        """Extract marker names and their beat positions from locators."""
        locators_map = {}
        
        locators = liveset.find("Locators")
        if locators is None:
            return locators_map
        
        locators_list = locators.find("Locators")
        if locators_list is None:
            return locators_map
        
        for locator in locators_list.findall("Locator"):
            name_elem = locator.find("Name")
            time_elem = locator.find("Time")
            
            if name_elem is not None and time_elem is not None:
                name = name_elem.get('Value', '')
                try:
                    beat_pos = float(time_elem.get('Value', 0))
                    locators_map[name] = beat_pos
                except ValueError:
                    pass
        
        return locators_map

    def _song_marker_key(self, song_idx: int, song) -> str:
        """Build the locator name used for a song marker in the template."""
        marker_key = f"{song_idx + 1}) {song.title}"
        if song.key_name:
            marker_key += f" ({song.key_name})"
        return marker_key

    def _is_six_eight_meter(self, meter: Optional[str]) -> bool:
        """Return True when the arrangement meter is explicitly 6/8."""
        if meter is None:
            return False
        return meter.replace(' ', '') == '6/8'

    def _remove_named_midi_clips(self, tracks: ET.Element, clip_name: str) -> None:
        """Remove template placeholder MIDI clips by name before adding generated copies."""
        for midi_track in tracks.findall('MidiTrack'):
            events = midi_track.find('./DeviceChain/MainSequencer/ClipTimeable/ArrangerAutomation/Events')
            if events is None:
                continue

            for midi_clip in list(events.findall('MidiClip')):
                name_elem = midi_clip.find('Name')
                if name_elem is not None and name_elem.get('Value', '') == clip_name:
                    events.remove(midi_clip)

    def _get_track_arranger_events(self, track: ET.Element) -> Optional[ET.Element]:
        """Return the ArrangerAutomation Events container for a MIDI track."""
        clip_timeable = track.find('./DeviceChain/MainSequencer/ClipTimeable')
        if clip_timeable is None:
            return None

        arranger_automation = clip_timeable.find('ArrangerAutomation')
        if arranger_automation is None:
            arranger_automation = ET.SubElement(clip_timeable, 'ArrangerAutomation')

        events = arranger_automation.find('Events')
        if events is None:
            events = ET.SubElement(arranger_automation, 'Events')

        return events

    def _next_midi_clip_id(self, events: ET.Element) -> int:
        """Return the next available MIDI clip Id for an Events container."""
        max_id = 0
        for clip in events.findall('MidiClip'):
            try:
                max_id = max(max_id, int(clip.get('Id', '0')))
            except ValueError:
                continue
        return max_id + 1

    def _get_midi_clip_start_beat(self, clip: ET.Element) -> Optional[float]:
        """Read a MIDI clip start beat from either the Time attribute or CurrentStart."""
        clip_time = clip.get('Time')
        if clip_time is not None:
            try:
                return float(clip_time)
            except ValueError:
                pass

        current_start = clip.find('CurrentStart')
        if current_start is not None:
            current_start_value = current_start.get('Value')
            if current_start_value is not None:
                try:
                    return float(current_start_value)
                except ValueError:
                    pass

        return None

    def _get_midi_clip_end_beat(self, clip: ET.Element) -> Optional[float]:
        """Read a MIDI clip end beat from CurrentEnd when present."""
        current_end = clip.find('CurrentEnd')
        if current_end is None:
            return None

        current_end_value = current_end.get('Value')
        if current_end_value is None:
            return None

        try:
            return float(current_end_value)
        except ValueError:
            return None

    def _get_existing_meter_clip_end_beat(self, events: ET.Element, beat_position: float) -> Optional[float]:
        """Reuse the template click clip span already present at this beat when available."""
        for clip in events.findall('MidiClip'):
            clip_start = self._get_midi_clip_start_beat(clip)
            if clip_start is None or abs(clip_start - beat_position) > 0.001:
                continue

            clip_end = self._get_midi_clip_end_beat(clip)
            if clip_end is not None and clip_end > beat_position:
                return clip_end

        return None

    def _remove_meter_clips_at_beat(self, events: ET.Element, clip_names: set[str], beat_position: float) -> None:
        """Remove time-signature clips with matching names that start at the given beat."""
        for clip in list(events.findall('MidiClip')):
            name_elem = clip.find('Name')
            clip_name = name_elem.get('Value', '') if name_elem is not None else ''
            if clip_name not in clip_names:
                continue

            clip_start = self._get_midi_clip_start_beat(clip)
            if clip_start is None:
                continue

            if abs(clip_start - beat_position) <= 0.001:
                events.remove(clip)

    def _insert_midi_clip_in_time_order(self, events: ET.Element, midi_clip: ET.Element) -> None:
        """Insert a MIDI clip before the first later clip so event order stays chronological."""
        new_start = self._get_midi_clip_start_beat(midi_clip)
        if new_start is None:
            events.append(midi_clip)
            return

        for index, existing_clip in enumerate(events.findall('MidiClip')):
            existing_start = self._get_midi_clip_start_beat(existing_clip)
            if existing_start is None:
                continue
            if existing_start > new_start:
                events.insert(index, midi_clip)
                return

        events.append(midi_clip)

    def _resolve_song_end_beat(
        self,
        plan_songs: List,
        locators_map: Dict[str, float],
        song_idx: int,
        song,
        song_start_beat: float,
        guide_wav: Optional[AudioStem],
        bpm: float,
    ) -> float:
        """Estimate the end beat for a song so meter clips can span the full song."""
        if song_idx + 1 < len(plan_songs):
            next_marker_key = self._song_marker_key(song_idx + 1, plan_songs[song_idx + 1])
            next_song_start = locators_map.get(next_marker_key)
            if next_song_start is not None and next_song_start > song_start_beat:
                return next_song_start

        if guide_wav is not None and bpm > 0:
            _, _, duration_seconds = self._get_wav_metadata(guide_wav.path)
            if duration_seconds > 0:
                return song_start_beat + ((duration_seconds * bpm) / 60.0)

        # When there is no next song marker and no guide duration, prefer LOOP if available.
        loop_beat = locators_map.get('LOOP')
        if loop_beat is not None and loop_beat > song_start_beat:
            return loop_beat

        return song_start_beat + 240.0

    def _add_meter_signature_clip_for_song(
        self,
        tracks: ET.Element,
        plan_songs: List,
        locators_map: Dict[str, float],
        song_idx: int,
        song,
        song_start_beat: float,
        guide_wav: Optional[AudioStem],
        bpm: float,
        song_color: Optional[str],
    ) -> None:
        """Duplicate the template 4/4 or 6/8 click clip across each song span."""
        meter_is_six_eight = self._is_six_eight_meter(song.arrangement.meter if song.arrangement else None)
        meter_name = '6/8' if meter_is_six_eight else '4/4'
        template_clip = self.template_six_eight_midi_clip if meter_is_six_eight else self.template_four_four_midi_clip

        if template_clip is None:
            logger.warning(f"Template {meter_name} MidiClip not found; skipping meter overlay clip")
            return

        meter_track_idx = self._find_midi_track_by_name(tracks, 'click')
        if meter_track_idx is None:
            logger.warning("MIDI click track not found; skipping 6/8 meter clip")
            return

        midi_tracks = tracks.findall('.//MidiTrack')
        if meter_track_idx >= len(midi_tracks):
            logger.warning("MIDI click track index out of range; skipping 6/8 meter clip")
            return

        events = self._get_track_arranger_events(midi_tracks[meter_track_idx])
        if events is None:
            logger.warning("Could not locate ArrangerAutomation events on MIDI click track")
            return

        existing_clip_end_beat = self._get_existing_meter_clip_end_beat(events, song_start_beat)
        self._remove_meter_clips_at_beat(events, {'4/4', '6/8'}, song_start_beat)

        song_end_beat = existing_clip_end_beat
        if song_end_beat is None:
            song_end_beat = self._resolve_song_end_beat(
                plan_songs,
                locators_map,
                song_idx,
                song,
                song_start_beat,
                guide_wav,
                bpm,
            )
        clip_duration = max(1.0, song_end_beat - song_start_beat)
        clip_id = self._next_midi_clip_id(events)
        meter_color_code = int(song_color) if song_color and song_color.isdigit() else None
        meter_clip = self._create_midi_clip_from_template(
            template_clip=template_clip,
            name=meter_name,
            beat_position=song_start_beat,
            duration=clip_duration,
            clip_id=clip_id,
            color_code=meter_color_code,
            preserve_loop_values=True,
        )
        if meter_clip is None:
            return

        self._insert_midi_clip_in_time_order(events, meter_clip)
        logger.info(
            f"Added {meter_name} meter clip for '{song.title}' from beat {song_start_beat:.2f} to {song_end_beat:.2f}"
        )

    def _find_track_by_name(self, tracks: ET.Element, search_name: str) -> Optional[int]:
        """Find audio track index by name, returns None if not found."""
        audio_tracks = tracks.findall(".//AudioTrack")
        
        for idx, track in enumerate(audio_tracks):
            name_elem = track.find(".//Name/EffectiveName")
            if name_elem is not None:
                track_name = name_elem.get('Value', '')
                if search_name.lower() in track_name.lower():
                    return idx
        
        return None

    def _find_midi_track_by_name(self, tracks: ET.Element, search_name: str) -> Optional[int]:
        """Find MIDI track index by name, returns None if not found."""
        midi_tracks = tracks.findall(".//MidiTrack")
        
        for idx, track in enumerate(midi_tracks):
            name_elem = track.find(".//Name/EffectiveName")
            if name_elem is not None:
                track_name = name_elem.get('Value', '')
                if search_name.lower() in track_name.lower():
                    return idx
        
        return None

    def _next_available_id(self, scope: ET.Element) -> int:
        """Return the next available numeric Id within the given XML scope."""
        max_id = 0
        for elem in scope.iter():
            elem_id = elem.get('Id')
            if elem_id and elem_id.lstrip('-').isdigit():
                max_id = max(max_id, int(elem_id))
        return max_id + 1

    def _get_track_name(self, track: ET.Element) -> str:
        """Return a track's effective name when present."""
        name_elem = track.find('Name/EffectiveName')
        return name_elem.get('Value', '') if name_elem is not None else ''

    def _set_track_name(self, track: ET.Element, track_name: str) -> None:
        """Set both EffectiveName and UserName for a generated track."""
        name_elem = track.find('Name')
        if name_elem is None:
            return

        effective_name = name_elem.find('EffectiveName')
        if effective_name is not None:
            effective_name.set('Value', track_name)

        user_name = name_elem.find('UserName')
        if user_name is not None:
            user_name.set('Value', track_name)

    def _set_track_color(self, track: ET.Element, track_color: Optional[str]) -> None:
        """Apply a color to a generated track when the XML supports it."""
        color_elem = track.find('Color')
        if color_elem is not None:
            color_elem.set('Value', track_color or '13')

    def _set_track_volume(self, track: ET.Element, volume_value: float) -> None:
        """Set the mixer volume for generated tracks/groups."""
        volume_manual = track.find('./DeviceChain/Mixer/Volume/Manual')
        if volume_manual is None:
            volume_manual = track.find('.//Mixer/Volume/Manual')

        if volume_manual is not None:
            volume_manual.set('Value', str(volume_value))

    def _set_track_group_id(self, track: ET.Element, parent_group_id: Optional[int]) -> None:
        """Assign a track to a parent group, or clear grouping when top-level."""
        group_value = str(parent_group_id) if parent_group_id is not None else '-1'

        track_group_id = track.find('TrackGroupId')
        if track_group_id is not None:
            track_group_id.set('Value', group_value)

        linked_group_id = track.find('LinkedTrackGroupId')
        if linked_group_id is not None:
            linked_group_id.set('Value', '-1')

    def _get_generated_track_insert_index(self, tracks: ET.Element) -> int:
        """Insert generated song content before returns/master/prehear tracks."""
        children = list(tracks)

        for index, child in enumerate(children):
            if child.tag in {'ReturnTrack', 'MasterTrack', 'PreHearTrack'}:
                return index

        return len(children)

    def _find_group_track_template(self, tracks: ET.Element) -> Optional[ET.Element]:
        """Use a real GroupTrack from the template as the source for generated groups."""
        fallback_group = None

        for child in tracks:
            if child.tag != 'GroupTrack':
                continue

            if fallback_group is None:
                fallback_group = child

            if self._get_track_name(child).strip().lower() == 'pads':
                return child

        return fallback_group

    def _get_audio_track_insert_index(self, tracks: ET.Element, stem_type: Optional[str] = None) -> int:
        """Insert Guide after Click and append other generated audio tracks after Pads."""
        children = list(tracks)

        click_index = None

        for index, child in enumerate(children):
            if child.tag != 'MidiTrack':
                continue

            name_elem = child.find('Name/EffectiveName')
            track_name = name_elem.get('Value', '') if name_elem is not None else ''
            if 'click' in track_name.lower():
                click_index = index
                break

        if stem_type == 'guide' and click_index is not None:
            return click_index + 1

        return self._get_generated_track_insert_index(tracks)

    def _get_template_send_count(self, tracks: ET.Element) -> int:
        """Use the template's current routing layout to size the new track sends."""
        for child in tracks:
            if child.tag not in {'AudioTrack', 'MidiTrack', 'GroupTrack'}:
                continue

            sends = child.find('.//Mixer/Sends')
            if sends is None:
                continue

            send_holders = sends.findall('TrackSendHolder')
            if send_holders:
                return len(send_holders)

        return len([child for child in tracks if child.tag == 'ReturnTrack'])

    def _get_template_clip_slot_count(self, tracks: ET.Element) -> int:
        """Use the template's session layout to size the new track clip slots."""
        for child in tracks:
            if child.tag not in {'AudioTrack', 'MidiTrack', 'GroupTrack'}:
                continue

            clip_slot_list = child.find('.//MainSequencer/ClipSlotList')
            if clip_slot_list is None:
                continue

            clip_slots = clip_slot_list.findall('ClipSlot')
            if clip_slots:
                return len(clip_slots)

        return 0

    def _remap_send_holder_target_ids(self, holder: ET.Element, next_id: int) -> int:
        """Assign unique automation/modulation ids to a newly cloned send holder."""
        for elem in holder.iter():
            if elem.tag in {'AutomationTarget', 'ModulationTarget'}:
                elem.set('Id', str(next_id))
                next_id += 1
        return next_id

    def _resize_track_sends(self, track: ET.Element, send_count: int, id_scope: Optional[ET.Element] = None) -> None:
        """Resize a track's send holders to match the generated return-bus count."""
        sends = track.find('.//Mixer/Sends')
        if sends is None:
            return

        send_holders = sends.findall('TrackSendHolder')
        prototype = send_holders[-1] if send_holders else self.blank_audio_track_template.find('.//Mixer/Sends/TrackSendHolder')
        if prototype is None:
            return

        while len(send_holders) > send_count:
            sends.remove(send_holders.pop())

        next_id = self._next_available_id(id_scope) if id_scope is not None else 1
        while len(send_holders) < send_count:
            cloned_holder = copy.deepcopy(prototype)
            next_id = self._remap_send_holder_target_ids(cloned_holder, next_id)
            sends.append(cloned_holder)
            send_holders.append(cloned_holder)

        for index, holder in enumerate(send_holders):
            holder.set('Id', str(index))

    def _resize_track_clip_slots(self, track: ET.Element, clip_slot_count: int) -> None:
        """Resize the embedded blank track's session clip slots to match the template."""
        clip_slot_list = track.find('.//MainSequencer/ClipSlotList')
        if clip_slot_list is None:
            return

        clip_slots = clip_slot_list.findall('ClipSlot')
        if not clip_slots:
            return

        prototype = clip_slots[-1]

        while len(clip_slots) > clip_slot_count:
            clip_slot_list.remove(clip_slots.pop())

        while len(clip_slots) < clip_slot_count:
            cloned_slot = copy.deepcopy(prototype)
            clip_slot_list.append(cloned_slot)
            clip_slots.append(cloned_slot)

        for index, clip_slot in enumerate(clip_slots):
            clip_slot.set('Id', str(index))

    def _set_track_send_level(self, track: ET.Element, send_index: int, level: float, active: bool = True) -> None:
        """Set a track send level by zero-based return-track index."""
        sends = track.find('.//Mixer/Sends')
        if sends is None:
            return

        send_holders = sends.findall('TrackSendHolder')
        if send_index < 0 or send_index >= len(send_holders):
            logger.warning(f"Guide track send index {send_index} is out of range for {len(send_holders)} sends")
            return

        send = send_holders[send_index].find('Send')
        if send is None:
            return

        manual = send.find('Manual')
        if manual is not None:
            manual.set('Value', str(level))

        active_elem = send_holders[send_index].find('Active')
        if active_elem is not None:
            active_elem.set('Value', 'true' if active else 'false')

    def _set_track_muted(self, track: ET.Element, muted: bool) -> None:
        """Set the mixer speaker state for a track or return bus."""
        speaker_manual = track.find('.//Mixer/Speaker/Manual')
        if speaker_manual is not None:
            speaker_manual.set('Value', 'false' if muted else 'true')

    def _reset_track_sends(self, track: ET.Element, level: float = OFF_SEND_LEVEL) -> None:
        """Normalize all track sends before enabling the routing this generator needs."""
        sends = track.find('.//Mixer/Sends')
        if sends is None:
            return

        for holder in sends.findall('TrackSendHolder'):
            send = holder.find('Send')
            if send is None:
                continue

            manual = send.find('Manual')
            if manual is not None:
                manual.set('Value', str(level))

            active_elem = holder.find('Active')
            if active_elem is not None:
                active_elem.set('Value', 'true')

    def _set_audio_output_routing(
        self,
        track: ET.Element,
        target_value: str,
        upper_display: str,
        lower_display: str = '',
    ) -> None:
        """Update the visible audio output routing fields for a generated track."""
        audio_output_routing = track.find('.//AudioOutputRouting')
        if audio_output_routing is None:
            return

        target = audio_output_routing.find('Target')
        if target is not None:
            target.set('Value', target_value)

        upper_display_string = audio_output_routing.find('UpperDisplayString')
        if upper_display_string is not None:
            upper_display_string.set('Value', upper_display)

        lower_display_string = audio_output_routing.find('LowerDisplayString')
        if lower_display_string is not None:
            lower_display_string.set('Value', lower_display)

    def _set_midi_routing_channel(self, track: ET.Element, routing_tag: str, channel: int) -> None:
        """Set a MIDI input/output routing block to a 1-based channel."""
        routing_elem = track.find(f'.//{routing_tag}')
        if routing_elem is None:
            return

        channel_index = max(0, int(channel) - 1)

        target = routing_elem.find('Target')
        if target is not None:
            target_value = target.get('Value', '')
            if '/' in target_value:
                prefix, _, suffix = target_value.rpartition('/')
                if suffix.lstrip('-').isdigit():
                    target.set('Value', f"{prefix}/{channel_index}")

        lower_display_string = routing_elem.find('LowerDisplayString')
        if lower_display_string is not None:
            lower_display_string.set('Value', f"Ch. {channel}")

    def _configure_track_send_routing(self, track: ET.Element, send_indexes: List[int]) -> None:
        """Route a track to Sends Only and enable only the requested generated buses."""
        self._reset_track_sends(track)
        self._set_audio_output_routing(track, 'AudioOut/None', 'Sends Only')

        for send_index in send_indexes:
            self._set_track_send_level(track, send_index, 1.0)

    def _configure_generated_audio_track_routing(self, track: ET.Element, send_indexes: List[int]) -> None:
        """Route generated audio tracks into the selected logical return buses.

        When send_indexes is empty the track outputs to its parent group instead
        of Sends Only, so routing is controlled entirely by the stem group.
        """
        if send_indexes:
            self._configure_track_send_routing(track, send_indexes)
        else:
            self._reset_track_sends(track)
            self._set_audio_output_routing(track, 'AudioOut/GroupTrack', 'Group')

    # Maps stem_type → ordered routing tags for content-bus lookup at the GROUP level.
    # Ordered broad → specific so the widest matching bus wins first; if the user has
    # only granular returns (e.g. 'acoustic_guitar' + 'electric_guitar' but no 'strings')
    # the lookup still falls through and finds a match.
    _STEM_TYPE_ROUTING_TAGS: ClassVar[Dict[str, List[str]]] = {
        'perc':    ['perc', 'drums', 'loops', 'percussion'],
        'bass':    ['bass'],
        'leads':   ['lead_line', 'leads', 'electric_guitar', 'acoustic_guitar', 'guitars'],
        'strings': ['strings', 'guitars', 'electric_guitar', 'acoustic_guitar', 'lead_line', 'orchestra'],
        'keys':    ['keys', 'piano', 'synth', 'pads'],
        'vocals':  ['vocals', 'lead_vocal', 'bgvs'],
    }

    def _send_indexes_for_stem_type(self, stem_type: str) -> List[int]:
        """Return the active send indexes for a stem group track based on stem type.

        Searches the full ordered tag list for the stem type (broad → specific) so
        the lookup works regardless of whether the user has a single broad return
        bus (e.g. 'strings'), separate per-instrument returns (e.g. 'acoustic_guitar'
        + 'electric_guitar'), or any other custom layout.
        """
        send_indexes: List[int] = []
        routing_tags = self._STEM_TYPE_ROUTING_TAGS.get(stem_type, [stem_type])
        content_bus = self._resolve_content_bus_for_tags(routing_tags)
        if content_bus is not None:
            send_indexes.append(content_bus['send_index'])
        else:
            logger.warning(f"No configured content bus matched stem type '{stem_type}'")

        sub_master_index = self.return_bus_indexes.get('sub_master')
        if sub_master_index is not None:
            send_indexes.append(sub_master_index)

        return send_indexes

    def _configure_generated_group_track(
        self,
        track: ET.Element,
        parent_group_id: Optional[int],
        stem_type: Optional[str] = None,
        send_indexes: Optional[List[int]] = None,
    ) -> None:
        """Configure generated song/category groups using real GroupTrack XML.

        Stem-type groups (Perc, Bass, etc.) carry the content-bus send so that
        moving a leaf track between stem groups automatically picks up the new
        routing without requiring per-track rewiring.
        """
        self._set_track_group_id(track, parent_group_id)

        if parent_group_id is None:
            # Top-level song group: output via sends to the mix buses.
            self._reset_track_sends(track)
            self._set_audio_output_routing(track, 'AudioOut/None', 'Sends Only')
            return

        if send_indexes:
            # Stem group with explicit routing: send to content buses.
            self._configure_track_send_routing(track, send_indexes)
        else:
            # Stem group with no routing: pass audio up to parent group.
            self._reset_track_sends(track)
            self._set_audio_output_routing(track, 'AudioOut/GroupTrack', 'Group')

    def _select_song_audio_wavs(self, stems: List[AudioStem]) -> List[AudioStem]:
        """Return non-guide WAV stems that can be routed into generated audio tracks."""
        audio_stems = []
        for stem in stems:
            if stem.path.suffix.lower() != '.wav':
                continue
            if stem.stem_type == 'guide':
                continue
            audio_stems.append(stem)

        return audio_stems

    def _build_song_audio_track_name(self, song_title: str, stem: AudioStem) -> str:
        """Build a readable track name for a generated song audio track."""
        stem_name = stem.path.stem
        if song_title.lower() in stem_name.lower():
            return stem_name
        return f"{song_title} - {stem_name}"

    def _audio_stem_sort_label(self, stem: AudioStem) -> str:
        """Return the stem label used to order generated tracks inside a group."""
        stem_name = stem.path.stem
        song_title = (stem.song_title or '').strip()
        if ' - ' in stem_name:
            parts = [part.strip() for part in stem_name.split(' - ') if part.strip()]
            for part in parts:
                if song_title and song_title.lower() in part.lower():
                    continue
                return part

        if song_title:
            stem_name = re.sub(re.escape(song_title), ' ', stem_name, flags=re.IGNORECASE)

        stem_name = re.sub(r'^[\s\-_]+|[\s\-_]+$', '', stem_name)
        stem_name = re.sub(r'\s+', ' ', stem_name).strip()
        return stem_name or stem.path.stem

    def _audio_stem_sort_key(self, stem: AudioStem) -> tuple:
        """Natural sort key for generated audio track order inside a group."""
        label = self._audio_stem_sort_label(stem).lower()
        parts = re.split(r'(\d+)', label)
        key_parts: List[tuple[int, Any]] = []
        for part in parts:
            if not part:
                continue
            if part.isdigit():
                key_parts.append((1, int(part)))
                continue
            key_parts.append((0, part))
        return tuple(key_parts)

    def _special_bus_send_indexes(self, role: str) -> List[int]:
        """Return the generated send indexes for a non-content bus role."""
        send_indexes: List[int] = []

        send_index = self.return_bus_indexes.get(role)
        if send_index is not None:
            send_indexes.append(send_index)

        sub_master_index = self.return_bus_indexes.get('sub_master')
        if role != 'sub_master' and sub_master_index is not None:
            send_indexes.append(sub_master_index)

        return send_indexes

    def _ordered_routing_tags_for_stem(self, stem: AudioStem) -> List[str]:
        """Return ordered routing tags from most-specific to broadest for a stem."""
        stem_name = stem.path.stem.lower()
        tags: List[str] = []

        def add_tag(tag: str) -> None:
            if tag not in tags:
                tags.append(tag)

        if stem.stem_type == 'perc':
            if any(keyword in stem_name for keyword in {'drum', 'kit', 'live'}):
                add_tag('drums')
            if 'loop' in stem_name:
                add_tag('loops')
            if any(keyword in stem_name for keyword in {'perc', 'percussion', 'fx'}):
                add_tag('percussion')
            add_tag('perc')
            return tags

        if stem.stem_type == 'bass':
            add_tag('bass')
            return tags

        if stem.stem_type == 'leads':
            if any(keyword in stem_name for keyword in {'ag', 'acoustic'}):
                add_tag('acoustic_guitar')
                add_tag('guitars')
            if any(keyword in stem_name for keyword in {'eg', 'electric', 'ax', 'axe', 'gtr'}):
                add_tag('electric_guitar')
                add_tag('guitars')
            add_tag('lead_line')
            add_tag('leads')
            return tags

        if stem.stem_type == 'strings':
            if any(keyword in stem_name for keyword in {'ag', 'acoustic'}):
                add_tag('acoustic_guitar')
                add_tag('guitars')
            if any(keyword in stem_name for keyword in {'eg', 'electric', 'ax', 'axe', 'gtr'}):
                add_tag('electric_guitar')
                add_tag('guitars')
            if any(keyword in stem_name for keyword in {'lead', 'hook', 'line', 'solo', 'melody'}):
                add_tag('lead_line')
            if any(keyword in stem_name for keyword in {'orch', 'orchestral', 'violin', 'viola', 'cello', 'strings'}):
                add_tag('orchestra')
            add_tag('strings')
            return tags

        if stem.stem_type == 'keys':
            if 'piano' in stem_name:
                add_tag('piano')
            if any(keyword in stem_name for keyword in {'pad', 'strings_pad'}):
                add_tag('pads')
            if any(keyword in stem_name for keyword in {'synth', 'pad', 'moog', 'additional', 'additionals'}):
                add_tag('synth')
            if any(keyword in stem_name for keyword in {'keys', 'key ', 'organ', 'rhodes', 'wurlitzer', 'clav'}):
                add_tag('keys')
            if not tags:
                add_tag('keys')
            return tags

        if stem.stem_type == 'vocals':
            if any(keyword in stem_name for keyword in {'bgv', 'bgvs', 'choir', 'alto', 'soprano', 'tenor'}):
                add_tag('bgvs')
            else:
                add_tag('lead_vocal')
            add_tag('vocals')
            return tags

        if stem.stem_type == 'guide':
            add_tag('click' if self._is_click_stem(stem) else 'guide')

        return tags

    def _resolve_content_bus_for_stem(self, stem: AudioStem) -> Optional[Dict[str, Any]]:
        """Resolve the configured content bus for a stem from its ordered routing tags."""
        return self._resolve_content_bus_for_tags(self._ordered_routing_tags_for_stem(stem))

    def _resolve_content_bus_for_tags(self, tags: List[str]) -> Optional[Dict[str, Any]]:
        """Resolve the configured content bus for an ordered list of routing tags."""
        content_buses = [bus for bus in self.active_return_buses if bus['role'] == 'content']
        if not content_buses:
            return None

        for tag in tags:
            for bus in content_buses:
                if tag in bus['tags']:
                    return bus

        return None

    def _send_indexes_for_audio_stem(self, stem: AudioStem) -> List[int]:
        """Return the active send indexes for a generated audio stem track."""
        send_indexes: List[int] = []
        content_bus = self._resolve_content_bus_for_stem(stem)
        if content_bus is not None:
            send_indexes.append(content_bus['send_index'])
        else:
            logger.warning(f"No configured content bus matched stem '{stem.filename}'")

        sub_master_index = self.return_bus_indexes.get('sub_master')
        if sub_master_index is not None:
            send_indexes.append(sub_master_index)

        return send_indexes

    def _extract_key_token(self, text: str) -> Optional[str]:
        """Extract a musical key token from a filename or folder name."""
        for pattern in (
            r'\[\s*([A-G](?:#|b)?(?:m|maj|min|minor|major)?)\s*\]',
            r'\(\s*([A-G](?:#|b)?(?:m|maj|min|minor|major)?)\s*\)',
            r'\{\s*([A-G](?:#|b)?(?:m|maj|min|minor|major)?)\s*\}',
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                normalized = self._normalize_key_name(match.group(1))
                if normalized:
                    return normalized
        return None

    def _normalize_key_name(self, key_name: Optional[str]) -> Optional[str]:
        """Normalize key strings like Db, C#m, or B major to a pitch-class root."""
        if not key_name:
            return None

        match = re.search(r'([A-Ga-g])\s*([#bB]?)', key_name.strip())
        if not match:
            return None

        letter = match.group(1).upper()
        accidental = match.group(2).replace('B', 'b')
        normalized = f"{letter}{accidental}".upper()
        return normalized if normalized in self.KEY_TO_SEMITONE else None

    def _collect_song_key_candidates(self, stems: List[AudioStem]) -> List[str]:
        """Collect unique source-key candidates from stem filenames and parent folders."""
        candidates: List[str] = []
        scanned_directories: set[Path] = set()
        song_title = stems[0].song_title if stems else ''

        def canonicalize_song_container_name(text: str) -> str:
            text = re.sub(r'\s*[\(\[\{][^\)\]\}]*[\)\]\}]', '', text)
            text = re.sub(r'\s+sw\b', '', text, flags=re.IGNORECASE)
            return re.sub(r'[^a-z0-9]+', '', text.lower())

        def normalize_name(text: str) -> str:
            return re.sub(r'[^a-z0-9]+', '', text.lower())

        normalized_song_title = canonicalize_song_container_name(song_title)

        def is_song_container(path: Path) -> bool:
            if not normalized_song_title:
                return False

            normalized_path_name = canonicalize_song_container_name(path.name)
            return bool(normalized_path_name) and normalized_song_title == normalized_path_name

        for stem in stems:
            path_texts = [stem.filename, stem.path.stem]
            relevant_parents: List[Path] = []

            for parent in stem.path.parents:
                if not parent.name:
                    break

                relevant_parents.append(parent)
                if is_song_container(parent):
                    break

            path_texts.extend(parent.name for parent in relevant_parents if parent.name)

            for parent in relevant_parents:
                if parent in scanned_directories or not parent.exists() or not parent.is_dir():
                    continue

                scanned_directories.add(parent)

                try:
                    path_texts.extend(child.name for child in parent.iterdir() if child.name and not child.name.startswith('.'))
                except OSError as exc:
                    logger.debug(f"Unable to inspect directory '{parent}' for key hints: {exc}")

            for text in path_texts:
                candidate = self._extract_key_token(text)
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

        return candidates

    def _format_key_display(self, key_name: Optional[str]) -> Optional[str]:
        """Return a user-facing key label for a normalized pitch class."""
        normalized = self._normalize_key_name(key_name)
        if normalized is None:
            return None
        return self.KEY_DISPLAY_NAMES.get(normalized, normalized)

    def _song_prompt_cache_key(self, song) -> str:
        """Return a stable cache key for per-song generation prompts."""
        return str(getattr(song, 'item_id', None) or getattr(song, 'id', None) or song.title)

    def _prompt_for_song_bpm(self, song_title: str, initial_bpm: float = 120.0) -> float:
        """Ask the user for a BPM when Planning Center did not provide one."""
        selected_bpm: Dict[str, Optional[float]] = {'value': None}

        try:
            root = tk._get_temp_root()
            dialog = tk.Toplevel(root)
            dialog.title("Resolve Song BPM")
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()

            prompt = (
                f"Planning Center did not provide a BPM for '{song_title}'.\n\n"
                "Enter the BPM to use for audio placement and tempo automation."
            )
            message = tk.Label(dialog, text=prompt, justify='left', anchor='w', wraplength=420)
            message.pack(padx=16, pady=(16, 12), fill='both')

            display_bpm = int(initial_bpm) if float(initial_bpm).is_integer() else initial_bpm
            selected_value = tk.StringVar(value=str(display_bpm))
            entry = ttk.Entry(dialog, textvariable=selected_value, width=16)
            entry.pack(padx=16, pady=(0, 16), fill='x')
            entry.focus_set()
            entry.selection_range(0, 'end')

            button_row = tk.Frame(dialog)
            button_row.pack(padx=16, pady=(0, 16), fill='x')

            def confirm() -> None:
                try:
                    bpm_value = float(selected_value.get().strip())
                except ValueError:
                    messagebox.showwarning("Resolve Song BPM", "Enter a valid BPM number.", parent=dialog)
                    return

                if bpm_value <= 0:
                    messagebox.showwarning("Resolve Song BPM", "BPM must be greater than 0.", parent=dialog)
                    return

                selected_bpm['value'] = bpm_value
                dialog.destroy()

            def cancel() -> None:
                dialog.destroy()

            ttk.Button(button_row, text='OK', command=confirm).pack(side='right')
            ttk.Button(button_row, text='Cancel', command=cancel).pack(side='right', padx=(0, 8))

            dialog.protocol('WM_DELETE_WINDOW', cancel)
            dialog.bind('<Return>', lambda event: confirm())
            dialog.bind('<Escape>', lambda event: cancel())
            dialog.wait_window()
        except Exception as exc:
            logger.warning(f"Unable to prompt for BPM for '{song_title}': {exc}")
            return initial_bpm

        if selected_bpm['value'] is None:
            raise GenerationCancelledError(f"BPM selection cancelled for '{song_title}'")

        return selected_bpm['value']

    def _resolve_song_bpm(self, song) -> float:
        """Resolve a song BPM from PCO metadata or a one-time user prompt."""
        cache_key = self._song_prompt_cache_key(song)
        if cache_key in self.song_bpm_cache:
            return self.song_bpm_cache[cache_key]

        arrangement = getattr(song, 'arrangement', None)
        if arrangement and arrangement.bpm:
            bpm_value = float(arrangement.bpm)
        else:
            logger.warning(f"Song '{song.title}' has no arrangement BPM")
            bpm_value = self._run_on_ui_thread(lambda: self._prompt_for_song_bpm(song.title))

        self.song_bpm_cache[cache_key] = bpm_value
        return bpm_value

    def _prompt_for_song_target_key(self, song_title: str, stems: List[AudioStem], preferred_key: Optional[str]) -> Optional[str]:
        """Ask the user for the target key when Planning Center did not provide one."""
        sample_names = ', '.join(sorted({stem.path.parent.name for stem in stems})[:3])
        prompt = (
            f"Planning Center did not provide a target key for '{song_title}'.\n\n"
            f"Stem folders: {sample_names or 'n/a'}\n\n"
            "Choose the target key to use for pitch correction."
        )

        selected_key: Dict[str, Optional[str]] = {'value': None}
        options = [self.KEY_DISPLAY_NAMES[key] for key in self.KEY_OPTION_ORDER]

        preferred_normalized = self._normalize_key_name(preferred_key)
        if preferred_normalized is None:
            preferred_normalized = self.KEY_OPTION_ORDER[0]

        try:
            root = tk._get_temp_root()
            dialog = tk.Toplevel(root)
            dialog.title("Resolve Song Key")
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()

            message = tk.Label(dialog, text=prompt, justify='left', anchor='w', wraplength=420)
            message.pack(padx=16, pady=(16, 12), fill='both')

            selected_value = tk.StringVar(value=self.KEY_DISPLAY_NAMES[preferred_normalized])
            combo = ttk.Combobox(dialog, textvariable=selected_value, values=options, state='readonly', width=12)
            combo.pack(padx=16, pady=(0, 16), fill='x')
            combo.focus_set()

            button_row = tk.Frame(dialog)
            button_row.pack(padx=16, pady=(0, 16), fill='x')

            def confirm() -> None:
                selected_key['value'] = self._normalize_key_name(selected_value.get())
                dialog.destroy()

            def cancel() -> None:
                dialog.destroy()

            ttk.Button(button_row, text='OK', command=confirm).pack(side='right')
            ttk.Button(button_row, text='Cancel', command=cancel).pack(side='right', padx=(0, 8))

            dialog.protocol('WM_DELETE_WINDOW', cancel)
            dialog.bind('<Return>', lambda event: confirm())
            dialog.bind('<Escape>', lambda event: cancel())
            dialog.wait_window()
        except Exception as exc:
            logger.warning(f"Unable to prompt for target key for '{song_title}': {exc}")
            return None

        if selected_key['value'] is None:
            raise GenerationCancelledError(f"Target key selection cancelled for '{song_title}'")

        return selected_key['value']

    def _resolve_song_target_key(self, song, stems: List[AudioStem], preferred_key: Optional[str] = None) -> Optional[str]:
        """Resolve a song target key from PCO metadata or a one-time user prompt."""
        if song.key_name:
            return self._normalize_key_name(song.key_name)

        cache_key = self._song_prompt_cache_key(song)
        if cache_key in self.target_key_cache:
            return self.target_key_cache[cache_key]

        logger.warning(f"Song '{song.title}' has no Planning Center key")
        resolved_key = self._run_on_ui_thread(
            lambda: self._prompt_for_song_target_key(song.title, stems, preferred_key)
        )
        self.target_key_cache[cache_key] = resolved_key
        return resolved_key

    def _prompt_for_song_source_key(self, song_title: str, plan_key: Optional[str], stems: List[AudioStem], candidates: List[str]) -> Optional[str]:
        """Ask the user for the source key when filenames/folders are ambiguous."""
        sample_names = ', '.join(sorted({stem.path.parent.name for stem in stems})[:3])
        candidate_text = ', '.join(self._format_key_display(candidate) or candidate for candidate in candidates) if candidates else 'none detected'
        prompt = (
            f"Couldn't confidently determine the source key for '{song_title}'.\n\n"
            f"Planning Center key: {self._format_key_display(plan_key) or plan_key or 'unknown'}\n"
            f"Detected candidates: {candidate_text}\n"
            f"Stem folders: {sample_names or 'n/a'}\n\n"
            "Choose the source key for these stems."
        )

        selected_key: Dict[str, Optional[str]] = {'value': None}
        options = [self.KEY_DISPLAY_NAMES[key] for key in self.KEY_OPTION_ORDER]

        preferred_key = next(
            (
                self._normalize_key_name(candidate)
                for candidate in candidates
                if self._normalize_key_name(candidate) in self.KEY_DISPLAY_NAMES
            ),
            None,
        )
        if preferred_key is None:
            preferred_key = self._normalize_key_name(plan_key)
        if preferred_key is None:
            preferred_key = self.KEY_OPTION_ORDER[0]

        try:
            root = tk._get_temp_root()
            dialog = tk.Toplevel(root)
            dialog.title("Resolve Stem Key")
            dialog.resizable(False, False)
            dialog.transient(root)
            dialog.grab_set()

            message = tk.Label(dialog, text=prompt, justify='left', anchor='w', wraplength=420)
            message.pack(padx=16, pady=(16, 12), fill='both')

            selected_value = tk.StringVar(value=self.KEY_DISPLAY_NAMES[preferred_key])
            combo = ttk.Combobox(dialog, textvariable=selected_value, values=options, state='readonly', width=12)
            combo.pack(padx=16, pady=(0, 16), fill='x')
            combo.focus_set()

            button_row = tk.Frame(dialog)
            button_row.pack(padx=16, pady=(0, 16), fill='x')

            def confirm() -> None:
                selected_key['value'] = self._normalize_key_name(selected_value.get())
                dialog.destroy()

            def cancel() -> None:
                dialog.destroy()

            ttk.Button(button_row, text='OK', command=confirm).pack(side='right')
            ttk.Button(button_row, text='Cancel', command=cancel).pack(side='right', padx=(0, 8))

            dialog.protocol('WM_DELETE_WINDOW', cancel)
            dialog.bind('<Return>', lambda event: confirm())
            dialog.bind('<Escape>', lambda event: cancel())
            dialog.wait_window()
        except Exception as exc:
            logger.warning(f"Unable to prompt for source key for '{song_title}': {exc}")
            return None

        if selected_key['value'] is None:
            raise GenerationCancelledError(f"Source key selection cancelled for '{song_title}'")

        return selected_key['value']

    def _resolve_song_source_key(self, song, stems: List[AudioStem]) -> Optional[str]:
        """Resolve a song's stem source key from metadata or a one-time user prompt."""
        if song.title in self.source_key_cache:
            return self.source_key_cache[song.title]

        candidates = self._collect_song_key_candidates(stems)
        if len(candidates) == 1:
            resolved_key = candidates[0]
        elif len(candidates) > 1:
            logger.warning(f"Multiple source keys detected for '{song.title}': {candidates}")
            resolved_key = self._run_on_ui_thread(
                lambda: self._prompt_for_song_source_key(song.title, song.key_name, stems, candidates)
            )
        else:
            logger.warning(f"No source key detected for '{song.title}'")
            resolved_key = self._run_on_ui_thread(
                lambda: self._prompt_for_song_source_key(song.title, song.key_name, stems, candidates)
            )

        self.source_key_cache[song.title] = resolved_key
        if resolved_key is not None:
            logger.info(f"Resolved source key for '{song.title}': {resolved_key}")
        return resolved_key

    def _calculate_song_pitch_shift(self, source_key: Optional[str], target_key: Optional[str]) -> int:
        """Return the shortest semitone move from source key to target key."""
        normalized_source = self._normalize_key_name(source_key)
        normalized_target = self._normalize_key_name(target_key)
        if normalized_source is None or normalized_target is None:
            return 0

        diff = (self.KEY_TO_SEMITONE[normalized_target] - self.KEY_TO_SEMITONE[normalized_source]) % 12
        if diff > 6:
            diff -= 12
        return diff

    def _apply_clip_warp_settings(self, clip: ET.Element, stem_type: str, pitch_shift: int) -> None:
        """Apply Ableton warp and transposition settings to a generated audio clip."""
        should_preserve_original = stem_type in {'perc', 'guide'}
        should_warp = not should_preserve_original and stem_type in self.STEM_WARP_MODES

        is_warped_elem = clip.find('IsWarped')
        if is_warped_elem is not None:
            is_warped_elem.set('Value', 'true' if should_warp else 'false')

        warp_mode_elem = clip.find('WarpMode')
        if warp_mode_elem is not None and should_warp:
            warp_mode_elem.set('Value', str(self.STEM_WARP_MODES[stem_type]))

        pitch_coarse_elem = clip.find('PitchCoarse')
        if pitch_coarse_elem is not None:
            pitch_coarse_elem.set('Value', str(0 if should_preserve_original else pitch_shift))

        pitch_fine_elem = clip.find('PitchFine')
        if pitch_fine_elem is not None:
            pitch_fine_elem.set('Value', '0')

    def _build_placeholder_track_name(self, song_title: str, stem_type: str) -> str:
        """Build a readable placeholder track name for empty generated groups."""
        group_name = self.STEM_GROUP_NAMES.get(stem_type, stem_type.title())
        return f"{song_title} - {group_name} Placeholder"

    def _group_song_audio_wavs(self, stems: List[AudioStem]) -> Dict[str, List[AudioStem]]:
        """Group routable song WAVs by stem type using stable natural stem ordering."""
        grouped_stems: Dict[str, List[AudioStem]] = {}

        for stem in stems:
            grouped_stems.setdefault(stem.stem_type, []).append(stem)

        for stem_type, stems_for_type in grouped_stems.items():
            grouped_stems[stem_type] = sorted(stems_for_type, key=self._audio_stem_sort_key)

        return grouped_stems

    def _add_flat_song_audio_tracks(
        self,
        liveset: ET.Element,
        tracks: ET.Element,
        song_title: str,
        audio_stems: List[AudioStem],
        beat_position: float,
        bpm: float,
        als_file_path: Path,
        song_color: Optional[str],
        pitch_shift: int,
    ) -> None:
        """Fallback path when no GroupTrack template exists in the source set."""
        for audio_stem in sorted(audio_stems, key=self._audio_stem_sort_key):
            logger.info(
                f"Adding {audio_stem.stem_type} wav for '{song_title}' at beat {beat_position}: {audio_stem.filename}"
            )
            track_name = self._build_song_audio_track_name(song_title, audio_stem)
            new_track = self._create_audio_track(
                liveset,
                tracks,
                track_name,
                audio_stem.stem_type,
                song_color,
                send_indexes=self._send_indexes_for_audio_stem(audio_stem),
            )
            if new_track is not None:
                self._add_audio_clip_to_track(
                    new_track,
                    audio_stem,
                    beat_position,
                    bpm,
                    als_file_path,
                    song_color,
                    pitch_shift=pitch_shift,
                )

    def _add_grouped_song_audio_tracks(
        self,
        liveset: ET.Element,
        tracks: ET.Element,
        song_title: str,
        audio_stems: List[AudioStem],
        beat_position: float,
        bpm: float,
        als_file_path: Path,
        song_color: Optional[str],
        pitch_shift: int,
    ) -> bool:
        """Create Song -> Bus Group -> Audio Track hierarchy for a song's routed WAVs.

        Sub-groups are created one-per-content-bus (not one-per-stem-type), so the
        session hierarchy always matches the user's configured return track layout.
        A user with 3 buses (Perc / Bass / Lead) gets 3 sub-groups; one with 6 gets 6.
        """
        if self._find_group_track_template(tracks) is None:
            return False

        insert_index = self._get_generated_track_insert_index(tracks)
        song_group = self._create_group_track(
            liveset,
            tracks,
            song_title,
            track_color=song_color,
            insert_index=insert_index,
        )
        if song_group is None:
            return False

        insert_index += 1
        song_group_id = int(song_group.get('Id', '-1'))

        # --- Resolve each stem to its content bus and bucket accordingly ---
        stems_by_bus: Dict[int, List[AudioStem]] = {}
        for audio_stem in audio_stems:
            bus = self._resolve_content_bus_for_stem(audio_stem)
            if bus is not None:
                stems_by_bus.setdefault(bus['send_index'], []).append(audio_stem)

        # Sort stems inside each bucket using the stable sort key.
        for key in stems_by_bus:
            stems_by_bus[key] = sorted(stems_by_bus[key], key=self._audio_stem_sort_key)

        # --- Determine which buses need a sub-group ---
        active_content_buses = [b for b in self.active_return_buses if b['role'] == 'content']

        # Leads placeholder: if no leads stems exist, we still want a blank track
        # so the engineer remembers the slot is available.  Find which bus leads live on.
        has_leads_stems = any(s.stem_type == 'leads' for s in audio_stems)
        leads_bus: Optional[Dict[str, Any]] = None
        if not has_leads_stems:
            leads_tags = self._STEM_TYPE_ROUTING_TAGS.get('leads', ['leads'])
            leads_bus = self._resolve_content_bus_for_tags(leads_tags)

        bus_indexes_needed: set = set(stems_by_bus.keys())
        if leads_bus is not None:
            bus_indexes_needed.add(leads_bus['send_index'])

        buses_to_create = [b for b in active_content_buses if b['send_index'] in bus_indexes_needed]

        sub_master_index = self.return_bus_indexes.get('sub_master')

        for bus in buses_to_create:
            bus_stems = stems_by_bus.get(bus['send_index'], [])

            bus_send_indexes: List[int] = [bus['send_index']]
            if sub_master_index is not None:
                bus_send_indexes.append(sub_master_index)

            stem_group = self._create_group_track(
                liveset,
                tracks,
                bus['name'],
                track_color=song_color,
                parent_group_id=song_group_id,
                send_indexes=bus_send_indexes,
                insert_index=insert_index,
            )

            group_parent_id = song_group_id
            if stem_group is not None:
                group_parent_id = int(stem_group.get('Id', '-1'))
                insert_index += 1

            # Placeholder when this bus is the leads bus and has no actual stems.
            is_leads_bus = leads_bus is not None and bus['send_index'] == leads_bus['send_index']
            if is_leads_bus and not bus_stems:
                placeholder_track = self._create_audio_track(
                    liveset,
                    tracks,
                    self._build_placeholder_track_name(song_title, 'leads'),
                    'leads',
                    song_color,
                    parent_group_id=group_parent_id,
                    insert_index=insert_index,
                )
                if placeholder_track is not None:
                    insert_index += 1
                continue

            for audio_stem in bus_stems:
                logger.info(
                    f"Adding {audio_stem.stem_type} wav for '{song_title}' at beat {beat_position}: {audio_stem.filename}"
                )
                track_name = self._build_song_audio_track_name(song_title, audio_stem)
                new_track = self._create_audio_track(
                    liveset,
                    tracks,
                    track_name,
                    audio_stem.stem_type,
                    song_color,
                    parent_group_id=group_parent_id,
                    send_indexes=[],   # leaf tracks output to group; routing is on the group
                    insert_index=insert_index,
                )
                if new_track is not None:
                    self._add_audio_clip_to_track(
                        new_track,
                        audio_stem,
                        beat_position,
                        bpm,
                        als_file_path,
                        song_color,
                        pitch_shift=pitch_shift,
                    )
                    insert_index += 1

        return True

    def _get_song_color_from_click_track(self, tracks: ET.Element, beat_position: float) -> Optional[str]:
        """Get the click-track clip color for the song section starting at the given beat."""
        click_track = None
        for track in tracks.findall('.//MidiTrack'):
            name_elem = track.find('Name/EffectiveName')
            track_name = name_elem.get('Value', '') if name_elem is not None else ''
            if 'click' in track_name.lower():
                click_track = track
                break

        if click_track is None:
            return None

        events = click_track.find('.//ClipTimeable/ArrangerAutomation/Events')
        if events is None:
            return None

        candidates = []
        for clip in events.findall('MidiClip'):
            clip_time = clip.get('Time')
            if clip_time is None:
                continue

            try:
                clip_time_value = float(clip_time)
            except ValueError:
                continue

            color_elem = clip.find('Color')
            color_value = color_elem.get('Value') if color_elem is not None else None
            if color_value is None:
                continue

            candidates.append((clip_time_value, color_value))

        exact_match = next((color for time, color in candidates if abs(time - beat_position) < 0.0001), None)
        if exact_match is not None:
            return exact_match

        next_match = next((color for time, color in sorted(candidates) if time >= beat_position), None)
        return next_match

    def _remap_audio_track_internal_ids(self, track: ET.Element, start_id: int) -> int:
        """Remap global-style IDs inside the inserted blank audio track."""
        remap_tags = {
            'AutomationTarget',
            'ModulationTarget',
            'Pointee',
            'VolumeModulationTarget',
            'TranspositionModulationTarget',
            'GrainSizeModulationTarget',
            'FluxModulationTarget',
            'SampleOffsetModulationTarget',
        }
        id_map: Dict[str, str] = {}
        next_id = start_id

        for elem in track.iter():
            if elem is track or elem.tag not in remap_tags:
                continue

            old_id = elem.get('Id')
            if not old_id or not old_id.lstrip('-').isdigit():
                continue

            if old_id not in id_map:
                id_map[old_id] = str(next_id)
                next_id += 1

            elem.set('Id', id_map[old_id])

        for elem in track.iter('PointeeId'):
            old_value = elem.get('Value')
            if old_value in id_map:
                elem.set('Value', id_map[old_value])

        return next_id

    def _update_next_pointee_id(self, liveset: ET.Element) -> None:
        """Keep LiveSet/NextPointeeId strictly above every pointee-style Id in the set."""
        remap_tags = {
            'AutomationTarget',
            'ModulationTarget',
            'Pointee',
            'VolumeModulationTarget',
            'TranspositionModulationTarget',
            'GrainSizeModulationTarget',
            'FluxModulationTarget',
            'SampleOffsetModulationTarget',
        }

        max_pointee_id = 0
        for elem in liveset.iter():
            if elem.tag not in remap_tags:
                continue

            elem_id = elem.get('Id')
            if elem_id and elem_id.isdigit():
                max_pointee_id = max(max_pointee_id, int(elem_id))

        next_pointee_elem = liveset.find('NextPointeeId')
        if next_pointee_elem is None:
            next_pointee_elem = ET.Element('NextPointeeId')
            insert_index = 0
            for index, child in enumerate(list(liveset)):
                if child.tag in {'OverwriteProtectionNumber', 'LomId', 'LomIdView', 'Tracks'}:
                    insert_index = index
                    break
            liveset.insert(insert_index, next_pointee_elem)

        next_pointee_elem.set('Value', str(max_pointee_id + 1))

    def _is_click_stem(self, stem: AudioStem) -> bool:
        """Identify click-like guide files so they do not create duplicate guide tracks."""
        filename = stem.filename.lower()
        return 'click' in filename or filename.startswith('classic-')

    def _is_suspicious_reference_guide(self, stem: AudioStem) -> bool:
        """Ignore reference stems that are clearly source-separated instrument files, not real guides."""
        filename = stem.filename.lower()
        if 'split_by_lalalai' in filename:
            return True
        if 'reference' not in filename:
            return False
        return any(token in filename for token in ('bass', 'gtr', 'guitar', 'piano', 'drums', 'perc', 'keys'))

    def _select_primary_guide_stem(self, stems: List[AudioStem]) -> Optional[AudioStem]:
        """Prefer an actual guide file over click/cue variants."""
        guide_stems = [
            stem
            for stem in stems
            if stem.stem_type == 'guide' and not self._is_suspicious_reference_guide(stem)
        ]
        if not guide_stems:
            return None

        def score(stem: AudioStem) -> tuple[int, str]:
            filename = stem.filename.lower()
            if 'guide' in filename:
                return (0, filename)
            if 'cue' in filename or 'reference' in filename:
                return (1, filename)
            if self._is_click_stem(stem):
                return (2, filename)
            return (3, filename)

        return sorted(guide_stems, key=score)[0]

    def _select_primary_guide_wav(self, stems: List[AudioStem]) -> Optional[AudioStem]:
        """Select one guide WAV per song, preferring GUIDE over CLICK."""
        guide_wavs = [stem for stem in stems if stem.stem_type == 'guide' and stem.path.suffix.lower() == '.wav']
        if not guide_wavs:
            return None

        preferred = self._select_primary_guide_stem(guide_wavs)
        if preferred is None:
            return None

        logger.debug(f"Selected guide wav '{preferred.filename}' for song '{preferred.song_title}'")
        return preferred

    def _get_wav_metadata(self, wav_path: Path) -> tuple[int, int, float]:
        """Return frame count, sample rate, and duration seconds for a WAV file."""
        try:
            with wave.open(str(wav_path), 'rb') as wav_file:
                frame_count = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
            duration_seconds = frame_count / sample_rate if sample_rate else 0.0
            return frame_count, sample_rate, duration_seconds
        except wave.Error:
            probe = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'error',
                    '-select_streams', 'a:0',
                    '-show_entries', 'stream=sample_rate:format=duration',
                    '-of', 'json',
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            metadata = json.loads(probe.stdout)
            streams = metadata.get('streams') or []
            stream = streams[0] if streams else {}
            sample_rate = int(float(stream.get('sample_rate') or 0))
            duration_seconds = float((metadata.get('format') or {}).get('duration') or 0.0)
            frame_count = int(round(duration_seconds * sample_rate)) if sample_rate and duration_seconds else 0
            return frame_count, sample_rate, duration_seconds

    def _create_audio_clip_element(
        self,
        guide_wav: AudioStem,
        beat_position: float,
        bpm: float,
        als_file_path: Path,
        clip_color: Optional[str] = None,
        pitch_shift: int = 0,
    ) -> ET.Element:
        """Create an Ableton-style AudioClip element for a guide WAV."""
        clip = copy.deepcopy(self.audio_clip_template)

        frame_count, sample_rate, duration_seconds = self._get_wav_metadata(guide_wav.path)
        duration_beats = (duration_seconds * bpm / 60.0) if bpm else 0.0
        clip_end_beat = beat_position + duration_beats
        should_warp = guide_wav.stem_type in self.STEM_WARP_MODES and guide_wav.stem_type not in {'perc', 'guide'}
        loop_end_value = duration_beats if should_warp else duration_seconds
        relative_path = os.path.relpath(guide_wav.path, als_file_path.parent).replace(os.sep, '/')
        file_stat = guide_wav.path.stat()
        file_crc = 0
        with open(guide_wav.path, 'rb') as audio_file:
            file_crc = zlib.crc32(audio_file.read()) & 0xFFFFFFFF

        clip.set('Time', str(beat_position))

        updates = {
            'CurrentStart': beat_position,
            'CurrentEnd': clip_end_beat,
            'Loop/LoopStart': 0,
            'Loop/LoopEnd': loop_end_value,
            'Loop/StartRelative': 0,
            'Loop/OutMarker': loop_end_value,
            'Loop/HiddenLoopStart': 0,
            'Loop/HiddenLoopEnd': loop_end_value,
            'Name': guide_wav.filename,
            'ScrollerTimePreserver/LeftTime': 0,
            'ScrollerTimePreserver/RightTime': duration_seconds,
            'SampleRef/FileRef/RelativePath': relative_path,
            'SampleRef/FileRef/Path': str(guide_wav.path),
            'SampleRef/FileRef/OriginalFileSize': file_stat.st_size,
            'SampleRef/FileRef/OriginalCrc': file_crc,
            'SampleRef/LastModDate': int(file_stat.st_mtime),
            'SampleRef/DefaultDuration': frame_count,
            'SampleRef/DefaultSampleRate': sample_rate,
        }

        if clip_color is not None:
            updates['Color'] = clip_color

        for path, value in updates.items():
            target = clip.find(path)
            if target is not None:
                target.set('Value', str(value))

        warp_markers = clip.find('WarpMarkers')
        if warp_markers is not None:
            markers = warp_markers.findall('WarpMarker')
            if len(markers) >= 3:
                terminal_marker_seconds = (1.0 / sample_rate) if sample_rate else 0.000001
                terminal_marker_beats = (terminal_marker_seconds * bpm / 60.0) if bpm else 0.000001

                markers[1].set('SecTime', str(duration_seconds))
                markers[1].set('BeatTime', str(duration_beats))
                if should_warp:
                    markers[2].set('SecTime', str(duration_seconds + terminal_marker_seconds))
                    markers[2].set('BeatTime', str(duration_beats + terminal_marker_beats))
                else:
                    markers[2].set('SecTime', str(duration_seconds))
                    markers[2].set('BeatTime', str(duration_beats))

        self._apply_clip_warp_settings(clip, guide_wav.stem_type, pitch_shift)

        return clip

    def _format_beat_value(self, value: float) -> str:
        """Format beat-domain values while preserving fractional alignment."""
        if abs(value - round(value)) < 0.0001:
            return str(int(round(value)))
        return f"{value:.6f}".rstrip('0').rstrip('.')

    def _detect_guide_cue_starts(self, guide_wav: AudioStem) -> List[float]:
        """Detect section-style cue phrase starts inside a guide WAV."""
        return [phrase['start'] for phrase in self._detect_guide_cue_phrases(guide_wav)]

    def _detect_guide_cue_phrases(self, guide_wav: AudioStem) -> List[Dict[str, Any]]:
        """Detect merged guide cue phrases with start/end timing."""
        cache_key = str(guide_wav.path)
        if cache_key in self.guide_cue_cache:
            return [{'start': start} for start in self.guide_cue_cache[cache_key]]

        try:
            with wave.open(str(guide_wav.path), 'rb') as wav_file:
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                window_frames = max(1, int(sample_rate * self.GUIDE_CUE_WINDOW_SECONDS))
                rms_values: List[int] = []

                while True:
                    frames = wav_file.readframes(window_frames)
                    if not frames:
                        break
                    rms_values.append(self._calculate_rms(frames, sample_width))
        except Exception as exc:
            logger.warning(f"Failed to analyze guide cues for '{guide_wav.filename}': {exc}")
            self.guide_cue_cache[cache_key] = []
            return []

        if not rms_values:
            self.guide_cue_cache[cache_key] = []
            return []

        sorted_rms = sorted(rms_values)
        median_rms = sorted_rms[len(sorted_rms) // 2]
        percentile_90 = sorted_rms[min(len(sorted_rms) - 1, int(len(sorted_rms) * 0.9))]
        active_threshold = max(250, int(median_rms * 3.0), int(percentile_90 * 0.18))
        min_active_windows = max(1, int(self.GUIDE_CUE_MIN_ACTIVE_SECONDS / self.GUIDE_CUE_WINDOW_SECONDS))

        raw_segments: List[Dict[str, float]] = []
        active_start_index: Optional[int] = None
        active_window_count = 0

        for index, rms_value in enumerate(rms_values):
            if rms_value >= active_threshold:
                if active_start_index is None:
                    active_start_index = index
                active_window_count += 1
                continue

            if active_start_index is None:
                continue

            if active_window_count >= min_active_windows:
                raw_segments.append({
                    'start': active_start_index * self.GUIDE_CUE_WINDOW_SECONDS,
                    'end': index * self.GUIDE_CUE_WINDOW_SECONDS,
                })

            active_start_index = None
            active_window_count = 0

        if active_start_index is not None and active_window_count >= min_active_windows:
            raw_segments.append({
                'start': active_start_index * self.GUIDE_CUE_WINDOW_SECONDS,
                'end': len(rms_values) * self.GUIDE_CUE_WINDOW_SECONDS,
            })

        merged_phrases: List[Dict[str, float]] = []
        for segment in raw_segments:
            if merged_phrases and segment['start'] - merged_phrases[-1]['end'] <= self.GUIDE_CUE_MERGE_GAP_SECONDS:
                merged_phrases[-1]['end'] = segment['end']
                merged_phrases[-1]['subsegments'] += 1
                continue

            merged_phrases.append({
                'start': segment['start'],
                'end': segment['end'],
                'subsegments': 1,
            })

        filtered_phrases = [
            phrase
            for phrase in merged_phrases
            if (phrase['end'] - phrase['start']) >= self.GUIDE_SECTION_MIN_DURATION_SECONDS
            and phrase['subsegments'] >= self.GUIDE_SECTION_MIN_SUBSEGMENTS
        ]

        logger.info(
            f"Detected {len(filtered_phrases)} section-style guide cues in '{guide_wav.filename}' "
            f"from {len(raw_segments)} speech bursts"
        )
        self.guide_cue_cache[cache_key] = [phrase['start'] for phrase in filtered_phrases]
        return filtered_phrases

    def _ensure_huggingface_cache_env(self) -> None:
        """Work around invalid user-level HF cache paths by forcing a local cache directory."""
        current_hf_home = os.getenv('HF_HOME')
        if current_hf_home:
            hf_home_path = Path(current_hf_home)
            if hf_home_path.exists() and hf_home_path.is_dir():
                return

        fallback_hf_home = Path(tempfile.gettempdir()) / 'projectfeb-hf-home'
        fallback_hf_home.mkdir(parents=True, exist_ok=True)
        os.environ['HF_HOME'] = str(fallback_hf_home)
        os.environ['HUGGINGFACE_HUB_CACHE'] = str(fallback_hf_home / 'hub')

    def _get_guide_transcription_model(self):
        """Lazily load the whisper model used for guide cue transcription."""
        if self.guide_transcription_unavailable:
            return None
        if self.guide_transcription_model is not None:
            return self.guide_transcription_model

        try:
            self._ensure_huggingface_cache_env()
            from faster_whisper import WhisperModel

            self.guide_transcription_model = WhisperModel(
                self.GUIDE_TRANSCRIPTION_MODEL,
                device='cpu',
                compute_type='int8',
            )
            return self.guide_transcription_model
        except Exception as exc:
            logger.warning(f"Guide transcription unavailable: {exc}")
            self.guide_transcription_unavailable = True
            return None

    def _guide_cue_family(self, cue_name: str) -> str:
        """Reduce a spoken guide cue or section label to its canonical family."""
        lower_name = cue_name.lower().strip()
        if 'tag' in lower_name or 'refrain' in lower_name:
            return 'tag'
        if lower_name.startswith('bridge'):
            return 'bridge'
        if 'pre chorus' in lower_name or 'prechorus' in lower_name:
            return 'pre chorus'
        if 'post chorus' in lower_name or 'postchorus' in lower_name:
            return 'post chorus'
        if 'turnaround' in lower_name or lower_name.startswith('turn'):
            return 'turnaround'
        if lower_name in {'interlude', 'break', 'breakdown'} or 'breakdown' in lower_name:
            return 'interlude'
        if lower_name in {'instrumental'} or 'instr' in lower_name:
            return 'instrumental'
        if lower_name in {'ending', 'outro', 'end', 'big ending'} or 'ending' in lower_name or 'outro' in lower_name:
            return 'ending'
        if lower_name in {'vamp'}:
            return 'tag'
        if 'chorus' in lower_name:
            return 'chorus'
        if 'intro' in lower_name:
            return 'intro'
        if 'verse' in lower_name:
            return 'verse'
        return lower_name

    def _extract_guide_transcript_modifiers(self, text: str) -> List[str]:
        """Extract performance-direction modifiers that should survive alongside guide labels."""
        lower_text = text.lower()
        modifier_patterns = [
            ('all in', r'\ball\s*in\b'),
            ('drums in', r'\bdrums\s*in\b'),
            ('breakdown', r'\bbreak\s*down\b|\bbreakdown\b'),
            ('break', r'\bbreak\b'),
            ('build', r'\bslowly\s*build\b|\bcontinue\s*to\s*build\b|\bbuild\b'),
            ('softly', r'\bsoftly\b'),
            ('bass', r'\bbass\b|\bbase\b'),
        ]

        modifiers: List[str] = []
        for modifier, pattern in modifier_patterns:
            if re.search(pattern, lower_text) and modifier not in modifiers:
                modifiers.append(modifier)
        return modifiers

    def _decorate_guide_transcribed_section(self, section: Dict[str, Any], text: str) -> Dict[str, Any]:
        """Attach normalized family and modifier context to a transcribed guide section."""
        decorated_section = dict(section)
        decorated_section['family'] = self._guide_cue_family(section['label'])
        decorated_section['modifiers'] = self._extract_guide_transcript_modifiers(text)
        return decorated_section

    def _find_guide_transcript_label_matches(self, text: str) -> List[tuple[int, int, str]]:
        """Find ordered canonical section labels and their spans in transcribed guide text."""
        lower_text = text.lower()
        separator = r'[\s,.;:-]*'

        patterns = [
            ('turnaround', r'\bturn\s*around\b|\bturnaround\b'),
            ('tag', r'\btag\b|\brefrain\b'),
            ('pre chorus', rf'\bpre{separator}chorus(?:{separator}(?:1|one|2|two|3|three|4|four))?\b|\bprechorus(?:{separator}(?:1|one|2|two|3|three|4|four))?\b'),
            ('post chorus', rf'\bpost{separator}chorus(?:{separator}(?:1|one|2|two|3|three|4|four))?\b|\bpostchorus(?:{separator}(?:1|one|2|two|3|three|4|four))?\b'),
            ('interlude', r'\bbreak\s*down\b|\bbreakdown\b|\bbreak\b|\binterlude\b'),
            ('bridge 1', rf'\bbridge{separator}(?:1|one)\b'),
            ('bridge 2', rf'\bbridge{separator}(?:2|two)\b'),
            ('bridge 3', rf'\bbridge{separator}(?:3|three)\b'),
            ('bridge', r'\bbridge\b'),
            ('instrumental', r'\binstrumental\b'),
            ('ending', r'\bbig\s*ending\b|\bending\b|\boutro\b|\bend\b'),
            ('chorus', rf'\bchorus(?:{separator}(?:1|one|2|two|3|three))?\b'),
            ('vamp', r'\bvamp\b'),
            ('intro', r'\bintro\b'),
            ('verse', rf'\bverse(?:{separator}(?:1|one|2|two|3|three))?\b'),
        ]

        matches: List[tuple[int, int, str]] = []
        occupied_spans: List[tuple[int, int]] = []
        for label, pattern in patterns:
            for match in re.finditer(pattern, lower_text):
                start, end = match.span()
                if any(start < existing_end and end > existing_start for existing_start, existing_end in occupied_spans):
                    continue
                occupied_spans.append((start, end))
                matches.append((start, end, label))

        matches.sort(key=lambda item: (item[0], item[1]))
        return matches

    def _extract_guide_word_timed_labels(self, segment) -> List[Dict[str, Any]]:
        """Extract canonical guide labels from word timestamps when available."""
        words = getattr(segment, 'words', None) or []
        if not words:
            return []

        normalized_words: List[Dict[str, Any]] = []
        for word in words:
            token = (word.word or '').strip()
            if not token:
                continue
            normalized = token.lower().strip('.,!?;:')
            if not normalized:
                continue
            normalized_words.append({
                'word': normalized,
                'start': float(word.start),
                'end': float(word.end),
            })

        labels: List[Dict[str, Any]] = []
        index = 0
        while index < len(normalized_words):
            current = normalized_words[index]
            word = current['word']
            next_word = normalized_words[index + 1]['word'] if index + 1 < len(normalized_words) else ''

            label: Optional[str] = None
            consumed = 1
            if word == 'turnaround' or (word == 'turn' and next_word == 'around'):
                label = 'turnaround'
                consumed = 2 if word == 'turn' and next_word == 'around' else 1
            elif word in {'tag', 'refrain'}:
                label = 'tag'
            elif word == 'prechorus' or (word == 'pre' and next_word == 'chorus'):
                label = 'pre chorus'
                consumed = 2 if word == 'pre' and next_word == 'chorus' else 1
            elif word == 'postchorus' or (word == 'post' and next_word == 'chorus'):
                label = 'post chorus'
                consumed = 2 if word == 'post' and next_word == 'chorus' else 1
            elif word == 'interlude':
                label = 'interlude'
            elif word == 'break' or word == 'breakdown' or (word == 'break' and next_word == 'down'):
                label = 'interlude'
                consumed = 2 if word == 'break' and next_word == 'down' else 1
            elif word == 'bridge':
                number_word = next_word
                if number_word in {'1', 'one'}:
                    label = 'bridge 1'
                    consumed = 2
                elif number_word in {'2', 'two'}:
                    label = 'bridge 2'
                    consumed = 2
                elif number_word in {'3', 'three'}:
                    label = 'bridge 3'
                    consumed = 2
                else:
                    label = 'bridge'
            elif word == 'instrumental':
                label = 'instrumental'
            elif word == 'big' and next_word == 'ending':
                label = 'ending'
                consumed = 2
            elif word in {'ending', 'outro', 'end'}:
                label = 'ending'
            elif word == 'chorus':
                label = 'chorus'
            elif word == 'vamp':
                label = 'vamp'
            elif word == 'intro':
                label = 'intro'
            elif word == 'verse':
                label = 'verse'

            if label is not None:
                end_index = min(len(normalized_words) - 1, index + consumed - 1)
                labels.append({
                    'label': label,
                    'start_seconds': current['start'],
                    'end_seconds': normalized_words[end_index]['end'],
                })
                index += consumed
                continue

            index += 1

        return labels

    def _extract_guide_transcript_labels(self, text: str) -> List[str]:
        """Extract ordered canonical section labels from transcribed guide text."""
        matches = self._find_guide_transcript_label_matches(text)
        return [label for _, _, label in matches]

    def _canonicalize_guide_transcript_label(self, text: str) -> Optional[str]:
        """Choose the best single section label from transcribed guide cue text."""
        labels = self._extract_guide_transcript_labels(text)
        if not labels:
            return None

        for label in labels:
            if self._section_family_from_name(label) != 'interlude':
                return label

        return labels[0]

    def _transcribe_guide_phrase_sections(self, guide_wav: AudioStem) -> List[Dict[str, Any]]:
        """Transcribe spoken guide cue phrases into ordered section segments."""
        cache_key = f"phrases::{guide_wav.path}"
        if cache_key in self.guide_transcription_cache:
            return self.guide_transcription_cache[cache_key]

        model = self._get_guide_transcription_model()
        if model is None:
            self.guide_transcription_cache[cache_key] = []
            return []

        cue_phrases = self._detect_guide_cue_phrases(guide_wav)
        if not cue_phrases:
            self.guide_transcription_cache[cache_key] = []
            return []

        guide_sections: List[Dict[str, Any]] = []
        padding_seconds = 0.25
        try:
            with wave.open(str(guide_wav.path), 'rb') as wav_file:
                params = wav_file.getparams()
                sample_rate = wav_file.getframerate()
                sample_width = wav_file.getsampwidth()
                channels = wav_file.getnchannels()
                all_audio = wav_file.readframes(wav_file.getnframes())
        except Exception as exc:
            logger.warning(f"Failed to load guide audio for cue transcription '{guide_wav.filename}': {exc}")
            self.guide_transcription_cache[cache_key] = []
            return []

        bytes_per_frame = sample_width * channels
        total_frames = len(all_audio) // bytes_per_frame if bytes_per_frame else 0

        for phrase in cue_phrases:
            start_frame = max(0, int((phrase['start'] - padding_seconds) * sample_rate))
            end_frame = min(total_frames, int((phrase['end'] + padding_seconds) * sample_rate))
            snippet_audio = all_audio[start_frame * bytes_per_frame:end_frame * bytes_per_frame]
            if not snippet_audio:
                continue

            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=True) as temp_wav:
                    with wave.open(temp_wav.name, 'wb') as temp_file:
                        temp_file.setparams(params)
                        temp_file.writeframes(snippet_audio)

                    segments, _ = model.transcribe(temp_wav.name, language='en', vad_filter=True)
            except Exception as exc:
                logger.warning(f"Failed to transcribe guide cue phrase for '{guide_wav.filename}': {exc}")
                continue

            text = ' '.join(segment.text.strip() for segment in segments if segment.text and segment.text.strip()).strip()
            if not text:
                continue

            label = self._canonicalize_guide_transcript_label(text)
            if label is None and not guide_sections and phrase['start'] <= 16.0:
                label = 'intro'
            if label is None:
                continue

            guide_sections.append(self._decorate_guide_transcribed_section({
                'start_seconds': phrase['start'],
                'end_seconds': phrase['end'],
                'label': label,
                'text': text,
            }, text))

        logger.info(f"Transcribed {len(guide_sections)} guide sections from '{guide_wav.filename}'")
        self.guide_transcription_cache[cache_key] = guide_sections
        return guide_sections

    def _transcribe_guide_whole_file_sections(self, guide_wav: AudioStem) -> List[Dict[str, Any]]:
        """Transcribe the full guide WAV and extract ordered labels from each segment."""
        cache_key = f"whole::{guide_wav.path}"
        if cache_key in self.guide_transcription_cache:
            return self.guide_transcription_cache[cache_key]

        model = self._get_guide_transcription_model()
        if model is None:
            self.guide_transcription_cache[cache_key] = []
            return []

        try:
            segments, _ = model.transcribe(
                str(guide_wav.path),
                language='en',
                vad_filter=True,
                word_timestamps=True,
            )
        except Exception as exc:
            logger.warning(f"Failed to transcribe full guide for '{guide_wav.filename}': {exc}")
            self.guide_transcription_cache[cache_key] = []
            return []

        guide_sections: List[Dict[str, Any]] = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue

            word_timed_labels = self._extract_guide_word_timed_labels(segment)
            if not word_timed_labels and not guide_sections and float(segment.start) <= 8.0:
                word_timed_labels = [{
                    'label': 'intro',
                    'start_seconds': float(segment.start),
                    'end_seconds': max(float(segment.start) + 0.25, float(segment.end)),
                }]
            if not word_timed_labels:
                continue

            for label_entry in word_timed_labels:
                guide_sections.append(self._decorate_guide_transcribed_section({
                    'start_seconds': label_entry['start_seconds'],
                    'end_seconds': label_entry['end_seconds'],
                    'label': label_entry['label'],
                    'text': text,
                }, text))

        logger.info(f"Transcribed {len(guide_sections)} whole-file guide sections from '{guide_wav.filename}'")
        self.guide_transcription_cache[cache_key] = guide_sections
        return guide_sections

    def _guide_transcription_alignment_score(self, target_family: str, observed_family: str) -> int:
        """Return an alignment score between a PCO section family and a transcribed guide family."""
        if target_family == observed_family:
            return self.GUIDE_TRANSCRIPTION_EXACT_MATCH_SCORE

        if target_family == 'tag' and observed_family == 'interlude':
            return self.GUIDE_TRANSCRIPTION_WEAK_MATCH_SCORE

        return 0

    def _guide_transcription_terminal_bonus(self, target_family: str, observed_family: str) -> int:
        """Prefer preserving final guide cues like Tag or Ending over duplicate mid-song labels."""
        if target_family not in {'tag', 'ending'}:
            return 0

        if target_family == observed_family:
            return self.GUIDE_TRANSCRIPTION_EXACT_MATCH_SCORE

        if target_family == 'tag' and observed_family in {'interlude', 'vamp'}:
            return self.GUIDE_TRANSCRIPTION_EXACT_MATCH_SCORE

        return 0

    def _guide_transcription_structural_bonus(self, target_name: str, observed_label: str) -> int:
        """Reward structurally important matches that should outrank extra generic choruses."""
        target_family = self._section_family_from_name(target_name)
        observed_family = self._section_family_from_name(observed_label)
        if target_family != observed_family:
            return 0

        normalized_target = target_name.lower().strip()
        normalized_observed = observed_label.lower().strip()

        if target_family in {'tag', 'ending'}:
            return self.GUIDE_TRANSCRIPTION_STRUCTURAL_MATCH_BONUS

        if normalized_target.startswith('bridge ') and normalized_target == normalized_observed:
            return self.GUIDE_TRANSCRIPTION_STRUCTURAL_MATCH_BONUS

        return 0

    def _should_prefer_guide_native_tail(
        self,
        sequence: List[str],
        whole_file_sections: List[Dict[str, Any]],
        aligned_sections: List[Dict[str, Any]],
    ) -> bool:
        """Prefer the richer whole-file guide when it preserves an explicit ending tail the aligned path loses."""
        if not sequence or len(whole_file_sections) <= len(sequence):
            return False

        if self._section_family_from_name(sequence[-1]) != 'tag':
            return False

        if not whole_file_sections:
            return False

        whole_tail = whole_file_sections[-3:]
        whole_tail_families = [self._section_family_from_name(section['label']) for section in whole_tail]
        if not whole_tail_families or whole_tail_families[-1] != 'ending':
            return False

        whole_tail_labels = [(section.get('label') or '').lower().strip() for section in whole_tail]
        if 'vamp' not in whole_tail_labels:
            return False

        if aligned_sections:
            aligned_tail_families = [self._section_family_from_name(section['target_name']) for section in aligned_sections[-3:]]
            if aligned_tail_families and aligned_tail_families[-1] == 'ending':
                return False

        return True

    def _normalize_guide_transcribed_sections(
        self,
        sections: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Collapse near-duplicate guide labels that come from the same spoken phrase."""
        normalized_sections: List[Dict[str, Any]] = []
        for section in sections:
            if not normalized_sections:
                normalized_sections.append(dict(section))
                continue

            previous = normalized_sections[-1]
            previous_family = self._section_family_from_name(previous['label'])
            current_family = self._section_family_from_name(section['label'])
            start_gap = float(section['start_seconds']) - float(previous['start_seconds'])
            if current_family == previous_family and start_gap <= self.GUIDE_TRANSCRIPTION_DUPLICATE_GAP_SECONDS:
                previous['end_seconds'] = max(float(previous.get('end_seconds', 0.0)), float(section.get('end_seconds', 0.0)))
                continue

            normalized_sections.append(dict(section))

        return normalized_sections

    def _cleanup_guide_transcribed_sections(
        self,
        sections: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Merge ultra-close modifier-only cues back into the surrounding structural section."""
        cleaned_sections: List[Dict[str, Any]] = []
        for section in sections:
            current = dict(section)
            current_family = self._section_family_from_name(current['label'])
            if not cleaned_sections:
                cleaned_sections.append(current)
                continue

            previous = cleaned_sections[-1]
            previous_family = self._section_family_from_name(previous['label'])
            current_text = (current.get('text') or '').strip().lower()
            previous_text = (previous.get('text') or '').strip().lower()
            start_gap = float(current['start_seconds']) - float(previous['start_seconds'])
            current_modifiers = set(current.get('modifiers', []))

            if (
                current_family == 'interlude'
                and previous_family not in {'interlude', 'ending'}
                and current_modifiers.intersection({'breakdown', 'break', 'build', 'all in', 'drums in', 'softly', 'bass'})
                and start_gap <= self.GUIDE_TRANSCRIPTION_MODIFIER_MERGE_GAP_SECONDS
                and current_text
                and current_text == previous_text
            ):
                previous_modifiers = list(previous.get('modifiers', []))
                for modifier in current.get('modifiers', []):
                    if modifier not in previous_modifiers:
                        previous_modifiers.append(modifier)
                previous['modifiers'] = previous_modifiers
                previous['end_seconds'] = max(
                    float(previous.get('end_seconds', 0.0)),
                    float(current.get('end_seconds', 0.0)),
                )
                continue

            cleaned_sections.append(current)

        structurally_cleaned_sections: List[Dict[str, Any]] = []
        for index, section in enumerate(cleaned_sections):
            current = dict(section)
            current_family = self._section_family_from_name(current['label'])
            if not structurally_cleaned_sections:
                structurally_cleaned_sections.append(current)
                continue

            previous = structurally_cleaned_sections[-1]
            previous_family = self._section_family_from_name(previous['label'])
            next_section = cleaned_sections[index + 1] if index + 1 < len(cleaned_sections) else None
            current_text = (current.get('text') or '').strip().lower()
            previous_text = (previous.get('text') or '').strip().lower()
            current_modifiers = set(current.get('modifiers', []))

            current_duration = None
            if next_section is not None:
                current_duration = float(next_section['start_seconds']) - float(current['start_seconds'])

            if (
                current_family == 'interlude'
                and next_section is not None
                and previous_family not in {'interlude', 'ending', 'chorus'}
                and current_duration is not None
                and current_duration <= self.GUIDE_TRANSCRIPTION_TINY_FRAGMENT_SECONDS
                and current_modifiers.intersection({'breakdown', 'break', 'build', 'all in', 'drums in', 'softly', 'bass'})
                and current_text
                and current_text == previous_text
            ):
                previous_modifiers = list(previous.get('modifiers', []))
                for modifier in current.get('modifiers', []):
                    if modifier not in previous_modifiers:
                        previous_modifiers.append(modifier)
                previous['modifiers'] = previous_modifiers
                previous['end_seconds'] = max(
                    float(previous.get('end_seconds', 0.0)),
                    float(current.get('end_seconds', 0.0)),
                )
                continue

            structurally_cleaned_sections.append(current)

        return structurally_cleaned_sections

    def _align_transcribed_sections_to_sequence(
        self,
        sequence: List[str],
        sections: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], float]:
        """Align transcribed guide sections to the target PCO arrangement sequence."""
        if not sequence or not sections:
            return [], 0.0

        target_families = [self._section_family_from_name(name) for name in sequence]
        observed_families = [self._section_family_from_name(section['label']) for section in sections]
        target_count = len(target_families)
        observed_count = len(observed_families)

        scores = [[0] * (observed_count + 1) for _ in range(target_count + 1)]
        moves = [[''] * (observed_count + 1) for _ in range(target_count + 1)]

        for target_index in range(1, target_count + 1):
            for observed_index in range(1, observed_count + 1):
                best_score = scores[target_index - 1][observed_index]
                best_move = 'up'

                if scores[target_index][observed_index - 1] > best_score:
                    best_score = scores[target_index][observed_index - 1]
                    best_move = 'left'

                match_score = self._guide_transcription_alignment_score(
                    target_families[target_index - 1],
                    observed_families[observed_index - 1],
                )
                if match_score > 0:
                    match_score += self._guide_transcription_structural_bonus(
                        sequence[target_index - 1],
                        sections[observed_index - 1]['label'],
                    )
                if match_score > 0 and target_index == target_count:
                    match_score += self._guide_transcription_terminal_bonus(
                        target_families[target_index - 1],
                        observed_families[observed_index - 1],
                    )
                diagonal_score = scores[target_index - 1][observed_index - 1] + match_score
                if match_score > 0 and diagonal_score > best_score:
                    best_score = diagonal_score
                    best_move = 'diag'

                scores[target_index][observed_index] = best_score
                moves[target_index][observed_index] = best_move

        aligned_sections: List[Dict[str, Any]] = []
        target_index = target_count
        observed_index = observed_count
        while target_index > 0 and observed_index > 0:
            move = moves[target_index][observed_index]
            if move == 'diag':
                section = dict(sections[observed_index - 1])
                section['target_name'] = sequence[target_index - 1]
                section['target_index'] = target_index - 1
                aligned_sections.append(section)
                target_index -= 1
                observed_index -= 1
            elif move == 'left':
                observed_index -= 1
            else:
                target_index -= 1

        aligned_sections.reverse()
        max_score = target_count * self.GUIDE_TRANSCRIPTION_EXACT_MATCH_SCORE
        score_ratio = (scores[target_count][observed_count] / max_score) if max_score else 0.0
        return aligned_sections, score_ratio

    def _expand_aligned_sections_to_full_sequence(
        self,
        sequence: List[str],
        aligned_sections: List[Dict[str, Any]],
        song_duration_seconds: float,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fill any unmatched PCO sections between aligned guide cues using weighted interpolation."""
        if not sequence or not aligned_sections:
            return None

        indexed_sections = [
            dict(section)
            for section in aligned_sections
            if isinstance(section.get('target_index'), int)
        ]
        if not indexed_sections:
            return None

        indexed_sections.sort(key=lambda section: section['target_index'])
        starts: List[Optional[float]] = [None] * len(sequence)
        section_by_index: Dict[int, Dict[str, Any]] = {}

        for section in indexed_sections:
            target_index = section['target_index']
            if target_index < 0 or target_index >= len(sequence):
                continue

            start_seconds = float(section['start_seconds'])
            starts[target_index] = start_seconds
            section_by_index[target_index] = section

        aligned_indexes = sorted(section_by_index)
        if not aligned_indexes:
            return None

        def target_weight(index: int) -> float:
            return max(1.0, self._expected_section_duration_profile(sequence[index])[2])

        def fill_leading_gap(end_index: int, end_time: float) -> None:
            if end_index <= 0:
                return

            interval = max(0.0, end_time)
            weights = [target_weight(index) for index in range(0, end_index)]
            total_weight = sum(weights)
            if total_weight <= 0:
                return

            elapsed = 0.0
            for offset, index in enumerate(range(0, end_index)):
                starts[index] = interval * elapsed / total_weight
                elapsed += weights[offset]

        def fill_gap_after_anchor(anchor_index: int, end_index: int, start_time: float, end_time: float) -> None:
            if end_index <= anchor_index + 1:
                return

            interval = max(0.0, end_time - start_time)
            weights = [target_weight(index) for index in range(anchor_index, end_index)]
            total_weight = sum(weights)
            if total_weight <= 0:
                return

            elapsed = weights[0]
            for offset, index in enumerate(range(anchor_index + 1, end_index), start=1):
                starts[index] = start_time + (interval * elapsed / total_weight)
                elapsed += weights[offset]

        first_index = aligned_indexes[0]
        first_start = starts[first_index]
        if first_start is None:
            return None
        fill_leading_gap(first_index, first_start)

        for previous_index, current_index in zip(aligned_indexes, aligned_indexes[1:]):
            previous_start = starts[previous_index]
            current_start = starts[current_index]
            if previous_start is None or current_start is None:
                return None

            fill_gap_after_anchor(previous_index, current_index, previous_start, current_start)

        last_index = aligned_indexes[-1]
        last_start = starts[last_index]
        if last_start is None:
            return None
        fill_gap_after_anchor(last_index, len(sequence), last_start, song_duration_seconds)

        expanded_sections: List[Dict[str, Any]] = []
        for index, section_name in enumerate(sequence):
            start_seconds = starts[index]
            if start_seconds is None:
                return None

            section = dict(section_by_index.get(index, {}))
            section['label'] = section.get('label', section_name)
            section['target_name'] = section_name
            section['target_index'] = index
            section['start_seconds'] = start_seconds
            expanded_sections.append(section)

        return expanded_sections

    def _transcribe_guide_sections(self, guide_wav: AudioStem, sequence: List[str]) -> List[Dict[str, Any]]:
        """Choose the best transcription strategy for the guide WAV against the target sequence."""
        phrase_sections = self._transcribe_guide_phrase_sections(guide_wav)
        whole_file_sections = self._cleanup_guide_transcribed_sections(
            self._normalize_guide_transcribed_sections(
                self._transcribe_guide_whole_file_sections(guide_wav)
            )
        )

        candidates = [
            ('phrase', phrase_sections),
            ('whole-file', whole_file_sections),
        ]

        best_sections: List[Dict[str, Any]] = []
        best_mode: Optional[str] = None
        best_ratio = 0.0
        best_count = 0
        best_count_gap: Optional[int] = None

        for mode, sections in candidates:
            aligned_sections, score_ratio = self._align_transcribed_sections_to_sequence(sequence, sections)
            if not aligned_sections:
                continue

            count_gap = abs(len(sections) - len(sequence))

            ratio_improvement = score_ratio - best_ratio
            should_replace = False

            if ratio_improvement > self.GUIDE_TRANSCRIPTION_CLOSE_MATCH_RATIO:
                should_replace = True
            elif abs(ratio_improvement) <= self.GUIDE_TRANSCRIPTION_CLOSE_MATCH_RATIO:
                if best_count_gap is None or count_gap < best_count_gap:
                    should_replace = True
                elif count_gap == best_count_gap and len(aligned_sections) > best_count:
                    should_replace = True

            if should_replace:
                best_sections = aligned_sections
                best_mode = mode
                best_ratio = score_ratio
                best_count = len(aligned_sections)
                best_count_gap = count_gap

        if self._should_prefer_guide_native_tail(sequence, whole_file_sections, best_sections):
            logger.info(
                f"Using guide-native whole-file ending tail for '{guide_wav.filename}' "
                f"with {len(whole_file_sections)} sections versus {len(sequence)} PCO targets"
            )
            return whole_file_sections

        if (
            len(whole_file_sections) >= len(sequence) + self.GUIDE_TRANSCRIPTION_GUIDE_NATIVE_MARGIN
            and len(whole_file_sections) > len(phrase_sections)
        ):
            logger.info(
                f"Using guide-native whole-file sections for '{guide_wav.filename}' "
                f"with {len(whole_file_sections)} sections versus {len(sequence)} PCO targets"
            )
            return whole_file_sections

        if best_sections and best_ratio >= self.GUIDE_TRANSCRIPTION_MIN_MATCH_RATIO:
            logger.info(
                f"Using {best_mode} guide transcription for '{guide_wav.filename}' "
                f"with match ratio {best_ratio:.2f} ({len(best_sections)} returned sections)"
            )
            return best_sections

        return []

    def _section_family_from_name(self, section_name: str) -> str:
        """Reduce a section name to its broad family for numbering reuse."""
        return self._guide_cue_family(section_name)

    def _beats_per_measure(self, meter: Optional[str]) -> float:
        """Return the beat count for one bar in the song meter."""
        return 6.0 if self._is_six_eight_meter(meter) else 4.0

    def _is_close_to_measure_multiple(
        self,
        beat_count: float,
        measure_beats: float,
        tolerance_beats: Optional[float] = None,
    ) -> bool:
        """Return True when a beat count is close to a whole-bar multiple."""
        if measure_beats <= 0:
            return False

        tolerance = tolerance_beats if tolerance_beats is not None else min(
            self.GUIDE_TRANSCRIPTION_MEASURE_ALIGNMENT_TOLERANCE_BEATS,
            measure_beats / 4.0,
        )
        nearest_multiple = round(beat_count / measure_beats) * measure_beats
        return abs(beat_count - nearest_multiple) <= tolerance

    def _display_name_for_guide_label(
        self,
        label: str,
        modifiers: Optional[List[str]] = None,
        text: Optional[str] = None,
    ) -> str:
        """Build a readable fallback display label from a canonical guide label."""
        modifiers = modifiers or []
        family = self._guide_cue_family(label)
        lower_label = label.lower().strip()
        lower_text = (text or '').lower()
        if label.startswith('bridge '):
            return label.title()
        if lower_label == 'vamp':
            return 'Vamp'
        if family == 'turnaround':
            return 'Turnaround'
        if family == 'pre chorus':
            return 'Pre Chorus'
        if family == 'post chorus':
            return 'Post Chorus'
        if family == 'interlude':
            if 'breakdown' in modifiers or 'break' in modifiers:
                return 'Breakdown'
            if 'drums in' in modifiers:
                return 'Drums In'
            if 'all in' in modifiers:
                return 'All In'
            return 'Interlude'
        if family == 'tag':
            if 'refrain' in lower_text or 'refrain' in lower_label:
                return 'Refrain'
            return 'Tag'
        if family == 'instrumental':
            return 'Instrumental'
        if family == 'ending':
            return 'Ending'
        if family == 'chorus':
            return 'Chorus'
        if family == 'intro':
            return 'Intro'
        if family == 'verse':
            return 'Verse'
        return label.title()

    def _guide_section_name_match_score(self, section: Dict[str, Any], target_name: str) -> int:
        """Score how well a guide-native section should borrow the next PCO display name."""
        observed_family = self._section_family_from_name(section['label'])
        target_family = self._section_family_from_name(target_name)
        if observed_family == target_family:
            return 3

        if target_family == 'turnaround' and observed_family == 'post chorus':
            return 2

        modifiers = set(section.get('modifiers', []))
        if target_family == 'tag' and observed_family in {'chorus', 'interlude'}:
            if modifiers.intersection({'all in', 'breakdown', 'build', 'drums in'}):
                return 2

        return 0

    def _resolve_guide_section_names(self, sequence: List[str], sections: List[Dict[str, Any]]) -> List[str]:
        """Use PCO names only to decorate generic guide labels like Verse/Chorus numbering."""
        resolved_names: List[str] = []
        sequence_index = 0

        for section in sections:
            label = section['label']
            modifiers = section.get('modifiers', [])
            text = section.get('text')

            if sequence_index < len(sequence):
                candidate_name = sequence[sequence_index]
                if self._guide_section_name_match_score(section, candidate_name) > 0:
                    resolved_name = candidate_name
                    sequence_index += 1
                else:
                    resolved_name = self._display_name_for_guide_label(label, modifiers, text)
            else:
                resolved_name = self._display_name_for_guide_label(label, modifiers, text)

            resolved_names.append(resolved_name)

        family_counts: Dict[str, int] = {}
        normalized_names: List[str] = []
        for resolved_name in resolved_names:
            family = self._section_family_from_name(resolved_name)
            lower_name = resolved_name.lower().strip()

            if family == 'verse':
                if lower_name.startswith('verse '):
                    suffix = lower_name.removeprefix('verse ').strip()
                    if suffix.isdigit():
                        family_counts['verse'] = max(family_counts.get('verse', 0), int(suffix))
                        normalized_names.append(resolved_name)
                        continue
                if lower_name == 'verse':
                    next_index = family_counts.get('verse', 0) + 1
                    family_counts['verse'] = next_index
                    normalized_names.append(f'Verse {next_index}')
                    continue

            if family == 'bridge':
                if lower_name.startswith('bridge '):
                    suffix = lower_name.removeprefix('bridge ').strip()
                    if suffix.isdigit():
                        bridge_index = int(suffix)
                        family_counts['bridge'] = max(family_counts.get('bridge', 0), bridge_index)
                        normalized_names.append('Bridge' if bridge_index == 1 else f'Bridge {bridge_index}')
                        continue
                if lower_name == 'bridge':
                    next_index = family_counts.get('bridge', 0) + 1
                    family_counts['bridge'] = next_index
                    normalized_names.append('Bridge' if next_index == 1 else f'Bridge {next_index}')
                    continue

            normalized_names.append(resolved_name)

        if normalized_names and self._section_family_from_name(sections[-1]['label']) == 'ending':
            normalized_names[-1] = 'Ending'

        return normalized_names

    def _get_guide_aligned_section_timings(
        self,
        guide_wav: Optional[AudioStem],
        sequence: List[str],
        beat_position: float,
        bpm: float,
        meter: Optional[str] = None,
    ) -> Optional[List[Dict[str, float]]]:
        """Build section timings from guide cues when the cue count matches the sequence count."""
        if guide_wav is None or not sequence or bpm <= 0:
            return None

        transcribed_sections = self._transcribe_guide_sections(guide_wav, sequence)
        if transcribed_sections:
            _, _, duration_seconds = self._get_wav_metadata(guide_wav.path)
            expanded_sections = self._expand_aligned_sections_to_full_sequence(
                sequence,
                transcribed_sections,
                duration_seconds,
            )
            if expanded_sections is not None:
                transcribed_sections = expanded_sections

            song_end_beat = beat_position + ((duration_seconds * bpm) / 60.0)
            resolved_names = None
            if any('target_name' not in section for section in transcribed_sections):
                resolved_names = self._resolve_guide_section_names(
                    sequence,
                    transcribed_sections,
                )

            section_timings: List[Dict[str, float]] = []
            for index, section in enumerate(transcribed_sections):
                section_start = beat_position + ((section['start_seconds'] * bpm) / 60.0)
                next_start = (
                    beat_position + ((transcribed_sections[index + 1]['start_seconds'] * bpm) / 60.0)
                    if index + 1 < len(transcribed_sections)
                    else song_end_beat
                )
                section_timings.append({
                    'name': (
                        section['target_name']
                        if 'target_name' in section
                        else resolved_names[index]
                    ),
                    'source_label': section.get('label'),
                    'source_text': section.get('text'),
                    'source_modifiers': list(section.get('modifiers', [])),
                    'start': section_start,
                    'duration': max(1.0, next_start - section_start),
                })

            section_timings = self._normalize_measure_aware_section_timings(
                section_timings,
                meter,
            )
            section_timings = self._restore_trailing_tag_before_ending(
                section_timings,
                sequence,
                meter,
            )

            extra_sections: List[Dict[str, Any]] = []
            seen_extra_keys: set[tuple[float, str]] = set()
            raw_section_sets = [
                self._transcribe_guide_phrase_sections(guide_wav),
                self._cleanup_guide_transcribed_sections(
                    self._normalize_guide_transcribed_sections(
                        self._transcribe_guide_whole_file_sections(guide_wav)
                    )
                ),
            ]
            for raw_sections in raw_section_sets:
                for raw_section in raw_sections:
                    raw_key = (round(float(raw_section['start_seconds']), 3), raw_section['label'])
                    if raw_key in seen_extra_keys:
                        continue
                    seen_extra_keys.add(raw_key)
                    extra_sections.append(raw_section)

            section_timings = self._split_section_timings_with_extra_cues(
                section_timings,
                extra_sections,
                beat_position,
                bpm,
            )

            logger.info(f"Using transcribed guide timeline for '{guide_wav.filename}'")
            return section_timings

        cue_starts_seconds = self._detect_guide_cue_starts(guide_wav)
        song_content_start = beat_position + self.TEMPLATE_ARRANGEMENT_INTRO_BEATS
        cue_start_beats = [
            beat_position + ((start_seconds * bpm) / 60.0)
            for start_seconds in cue_starts_seconds
        ]
        cue_start_beats = [cue for cue in cue_start_beats if cue >= song_content_start - 1.0]

        _, _, duration_seconds = self._get_wav_metadata(guide_wav.path)
        song_end_beat = beat_position + ((duration_seconds * bpm) / 60.0)

        selected_starts = self._select_section_start_beats(sequence, cue_start_beats, song_end_beat)
        if selected_starts is None:
            logger.info(
                f"Guide cue count mismatch for '{guide_wav.filename}': detected {len(cue_starts_seconds)} "
                f"cues ({len(cue_start_beats)} after intro trim) for {len(sequence)} sections; "
                "falling back to even MIDI spacing"
            )
            return None

        section_timings: List[Dict[str, float]] = []
        for index, section_name in enumerate(sequence):
            section_start = selected_starts[index]
            next_start = selected_starts[index + 1] if index + 1 < len(selected_starts) else song_end_beat
            section_timings.append({
                'name': section_name,
                'start': section_start,
                'duration': max(1.0, next_start - section_start),
            })

        logger.info(f"Using cue-detected guide timing fallback for '{guide_wav.filename}'")
        return section_timings

    def _normalize_measure_aware_section_timings(
        self,
        section_timings: List[Dict[str, Any]],
        meter: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Merge and rebalance guide-native section timings on musical bar boundaries."""
        if not section_timings:
            return section_timings

        measure_beats = self._beats_per_measure(meter)
        normalized: List[Dict[str, Any]] = []
        for section in section_timings:
            current = dict(section)
            current_family = self._section_family_from_name(current.get('source_label') or current['name'])
            current_text = (current.get('source_text') or '').strip().lower()
            if not normalized:
                normalized.append(current)
                continue

            previous = normalized[-1]
            previous_family = self._section_family_from_name(previous.get('source_label') or previous['name'])
            previous_text = (previous.get('source_text') or '').strip().lower()
            next_family = None
            if section is not section_timings[-1]:
                next_index = section_timings.index(section) + 1
                next_section = section_timings[next_index]
                next_family = self._section_family_from_name(next_section.get('source_label') or next_section['name'])

            # Same-phrase post-chorus announcements often describe the tail of the current chorus
            # rather than a separate marker region.
            if (
                current_family == 'post chorus'
                and previous_family == 'chorus'
                and self._is_close_to_measure_multiple(float(current['duration']), measure_beats)
                and (
                    (current_text and current_text == previous_text)
                    or ('turnaround' in current_text and next_family == 'turnaround')
                )
            ):
                previous['duration'] = float(previous['duration']) + float(current['duration'])
                continue

            normalized.append(current)

        micro_fragment_threshold = measure_beats * self.GUIDE_TRANSCRIPTION_MICRO_FRAGMENT_MEASURES
        for index in range(len(normalized) - 1):
            current = normalized[index]
            next_section = normalized[index + 1]
            current_duration = float(current['duration'])
            next_duration = float(next_section['duration'])
            pair_total = current_duration + next_duration
            current_family = self._section_family_from_name(current['name'])

            if (
                current_duration >= micro_fragment_threshold
                or pair_total < (2.0 * measure_beats)
                or current_family in {'tag', 'turnaround', 'ending'}
                or (current.get('source_label') and self._section_family_from_name(current['source_label']) in {'tag', 'turnaround'})
                or (current.get('source_label') or '').lower().strip() == 'vamp'
            ):
                continue

            target_current_duration: Optional[float] = None
            previous = normalized[index - 1] if index > 0 else None
            if previous is not None:
                previous_family = self._section_family_from_name(previous['name'])
                if previous_family == current_family:
                    previous_duration = float(previous['duration'])
                    target_current_duration = round(previous_duration / measure_beats) * measure_beats

            if target_current_duration is None:
                target_current_duration = round(pair_total / (2.0 * measure_beats)) * measure_beats

            target_current_duration = min(
                max(measure_beats, target_current_duration),
                pair_total - measure_beats,
            )
            if not self._is_close_to_measure_multiple(
                target_current_duration,
                measure_beats,
                tolerance_beats=self.GUIDE_TRANSCRIPTION_MEASURE_ALIGNMENT_TOLERANCE_BEATS * 1.5,
            ):
                continue

            current['duration'] = target_current_duration
            next_section['start'] = float(current['start']) + target_current_duration
            next_section['duration'] = max(1.0, pair_total - target_current_duration)

        return normalized

    def _restore_trailing_tag_before_ending(
        self,
        section_timings: List[Dict[str, Any]],
        sequence: List[str],
        meter: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Restore a short trailing Tag before an explicit Ending for guide-native chorus/vamp/ending tails."""
        if len(section_timings) < 3 or not sequence:
            return section_timings

        if self._section_family_from_name(sequence[-1]) != 'tag':
            return section_timings

        ending = section_timings[-1]
        last_chorus = section_timings[-2]
        prior = section_timings[-3]

        if self._section_family_from_name(ending['name']) != 'ending':
            return section_timings
        if self._section_family_from_name(last_chorus['name']) != 'chorus':
            return section_timings
        if (prior.get('source_label') or '').lower().strip() != 'vamp':
            return section_timings

        if any((item.get('source_label') or '').lower().strip() in {'tag', 'refrain'} for item in section_timings[-3:-1]):
            return section_timings

        measure_beats = self._beats_per_measure(meter)
        target_tag_duration = min(2.0 * measure_beats, float(last_chorus['duration']) - measure_beats)
        if target_tag_duration < measure_beats:
            return section_timings

        restored = [dict(item) for item in section_timings]
        restored_chorus = restored[-2]
        restored_chorus['duration'] = float(restored_chorus['duration']) - target_tag_duration
        tag_start = float(restored_chorus['start']) + float(restored_chorus['duration'])
        restored.insert(-1, {
            'name': 'Tag',
            'source_label': 'tag',
            'source_text': restored_chorus.get('source_text'),
            'source_modifiers': list(restored_chorus.get('source_modifiers', [])),
            'start': tag_start,
            'duration': target_tag_duration,
        })
        return restored

    def _select_section_start_beats(
        self,
        sequence: List[str],
        cue_start_beats: List[float],
        song_end_beat: float,
    ) -> Optional[List[float]]:
        """Choose the best cue-start subset for the target section sequence."""
        required_count = len(sequence)
        available_count = len(cue_start_beats)
        if available_count < required_count:
            return None

        if available_count == required_count:
            return cue_start_beats

        extra_count = available_count - required_count
        if extra_count > self.GUIDE_CUE_MAX_EXTRA_MATCHES:
            return None

        best_selection: Optional[List[float]] = None
        best_score: Optional[float] = None

        for selection_indexes in combinations(range(available_count), required_count):
            starts = [cue_start_beats[index] for index in selection_indexes]
            score = self._score_section_start_selection(sequence, starts, song_end_beat)
            if best_score is None or score < best_score:
                best_score = score
                best_selection = starts

        return best_selection

    def _score_section_start_selection(
        self,
        sequence: List[str],
        starts: List[float],
        song_end_beat: float,
    ) -> float:
        """Score a candidate cue subset against section-name duration expectations."""
        durations = [
            (starts[index + 1] if index + 1 < len(starts) else song_end_beat) - starts[index]
            for index in range(len(starts))
        ]

        score = 0.0
        for section_name, duration in zip(sequence, durations):
            min_beats, max_beats, target_beats = self._expected_section_duration_profile(section_name)
            rounded_duration = round(duration / 4.0) * 4.0
            score += abs(duration - rounded_duration)
            score += abs(duration - target_beats) * 0.15

            if duration < min_beats:
                score += (min_beats - duration) * 5.0
            if duration > max_beats:
                score += (duration - max_beats) * 3.0

        return score

    def _split_section_timings_with_extra_cues(
        self,
        section_timings: List[Dict[str, float]],
        guide_sections: List[Dict[str, Any]],
        beat_position: float,
        bpm: float,
    ) -> List[Dict[str, float]]:
        """Split generated sections on extra same-family guide cues that fall inside them."""
        if not section_timings or not guide_sections or bpm <= 0:
            return section_timings

        split_timings: List[Dict[str, float]] = []
        for timing in section_timings:
            section_start = float(timing['start'])
            section_end = section_start + float(timing['duration'])
            section_family = self._section_family_from_name(timing['name'])

            matching_cues: List[tuple[float, Dict[str, Any]]] = []
            for guide_section in guide_sections:
                cue_start = beat_position + ((float(guide_section['start_seconds']) * bpm) / 60.0)
                if cue_start <= section_start + 0.5 or cue_start >= section_end - 0.5:
                    continue
                if (
                    cue_start - section_start < self.GUIDE_TRANSCRIPTION_MIN_SPLIT_BEATS
                    or section_end - cue_start < self.GUIDE_TRANSCRIPTION_MIN_SPLIT_BEATS
                ):
                    continue

                cue_family = self._section_family_from_name(guide_section['label'])
                if cue_family != section_family:
                    continue

                matching_cues.append((cue_start, guide_section))

            if not matching_cues:
                split_timings.append(timing)
                continue

            matching_cues.sort(key=lambda item: item[0])
            current_start = section_start
            split_name = timing['name']
            if section_family == 'tag':
                split_name = self._display_name_for_guide_label(
                    matching_cues[0][1]['label'],
                    matching_cues[0][1].get('modifiers'),
                    matching_cues[0][1].get('text'),
                )

            for cue_start, _ in matching_cues:
                split_timings.append({
                    'name': split_name,
                    'start': current_start,
                    'duration': max(1.0, cue_start - current_start),
                })
                current_start = cue_start

            split_timings.append({
                'name': split_name,
                'start': current_start,
                'duration': max(1.0, section_end - current_start),
            })

        return split_timings

    def _expected_section_duration_profile(self, section_name: str) -> tuple[float, float, float]:
        """Return preferred duration bounds for a section label in beats."""
        section_lower = section_name.lower()

        if 'ending' in section_lower or 'outro' in section_lower:
            return (4.0, 20.0, 12.0)
        if 'turnaround' in section_lower or 'turn' in section_lower or 'vamp' in section_lower or 'tag' in section_lower:
            return (4.0, 16.0, 8.0)
        if 'intro' in section_lower:
            return (8.0, 32.0, 16.0)
        if 'instrumental' in section_lower or 'interlude' in section_lower or 'bridge' in section_lower:
            return (8.0, 40.0, 24.0)

        return (8.0, 40.0, 24.0)

    def _add_audio_clip_to_track(
        self,
        track: ET.Element,
        guide_wav: AudioStem,
        beat_position: float,
        bpm: float,
        als_file_path: Path,
        clip_color: Optional[str] = None,
        pitch_shift: int = 0,
    ) -> None:
        """Add an arranger audio clip to a blank guide audio track."""
        events = track.find('.//MainSequencer/Sample/ArrangerAutomation/Events')
        if events is None:
            logger.error("MainSequencer Sample ArrangerAutomation Events not found in guide track")
            return

        clip = self._create_audio_clip_element(
            guide_wav,
            beat_position,
            bpm,
            als_file_path,
            clip_color,
            pitch_shift,
        )
        existing_ids = [int(existing.get('Id', '0')) for existing in events.findall('AudioClip') if existing.get('Id', '0').isdigit()]
        clip.set('Id', str(max(existing_ids, default=0) + 1))
        events.append(clip)
        logger.info(f"Added guide wav clip '{guide_wav.filename}' at beat {beat_position} to track '{track.find('Name/EffectiveName').get('Value', '')}'")

    def _create_arrangement_track(self, tracks: ET.Element) -> Optional[int]:
        """Create a brand new MIDI track at the top for generated marker clips.
        
        Returns the index of the new track (0), or None if creation failed.
        """
        # Find a template MIDI track to use as a base (prefer Markers)
        midi_tracks = tracks.findall(".//MidiTrack")
        if not midi_tracks:
            logger.error("No existing MIDI tracks found to use as template")
            return None
        
        template_track = None
        for track in midi_tracks:
            name_elem = track.find(".//Name/EffectiveName")
            if name_elem is not None and name_elem.get('Value') == 'Markers':
                template_track = track
                break
        
        # If Markers not found, use the first MIDI track
        if template_track is None:
            template_track = midi_tracks[0]
        
        # Deep copy the template track
        new_track = copy.deepcopy(template_track)
        
        # Get the highest track ID in use
        max_id = 0
        for track in midi_tracks:
            try:
                track_id = int(track.get('Id', '0'))
                max_id = max(max_id, track_id)
            except ValueError:
                pass
        
        # Assign a new unique ID
        new_track.set('Id', str(max_id + 100))
        
        # Label the generated row explicitly so it does not inherit the template track name.
        self._set_track_name(new_track, 'Markers')
        self._set_track_muted(new_track, True)
        self._set_midi_routing_channel(new_track, 'MidiInputRouting', 1)
        self._set_midi_routing_channel(new_track, 'MidiOutputRouting', 1)
        
        # Clear out any existing clips from the new track
        ct = new_track.find(".//ClipTimeable")
        if ct is not None:
            events = ct.find("ArrangerAutomation/Events")
            if events is not None:
                # Remove all existing clips
                for clip in list(events):
                    events.remove(clip)
        
        # Clear ClipSlotsListWrapper
        csw = new_track.find(".//ClipSlotsListWrapper")
        if csw is not None:
            # Remove any children to make it empty
            for child in list(csw):
                csw.remove(child)
            # Set LomId attribute
            csw.set('LomId', '0')
        
        # Insert the new track before the first existing MidiTrack to maintain structure
        # Find the position of the first MidiTrack
        first_midi_idx = None
        children = list(tracks)
        
        for i, child in enumerate(children):
            if child.tag == 'MidiTrack':
                first_midi_idx = i
                break
        
        # If found, insert before it; otherwise append to end
        if first_midi_idx is not None:
            tracks.insert(first_midi_idx, new_track)
            logger.info(f"Created new arrangement track with ID {max_id + 100} before first MidiTrack")
        else:
            tracks.append(new_track)
            logger.info(f"Created new arrangement track with ID {max_id + 100} (appended to end)")
        
        return 0  # The new track is now at index 0 (or first position)

    def _add_guide_stem_to_track(self, tracks: ET.Element, track_idx: int, guide_stem: AudioStem, beat_position: float) -> None:
        """Add a guide stem audio clip to the Guide track, referencing the existing .wav file."""
        # Get all audio tracks
        audio_tracks = tracks.findall(".//AudioTrack")
        
        if track_idx >= len(audio_tracks):
            logger.warning(f"Audio track index {track_idx} out of range")
            return
        
        guide_track = audio_tracks[track_idx]
        
        # Find ClipSlotsListWrapper (should exist in template)
        clip_slots_wrapper = guide_track.find(".//ClipSlotsListWrapper")
        if clip_slots_wrapper is None:
            logger.error("ClipSlotsListWrapper not found in audio track")
            return
        
        # Find existing ClipSlotList or create one
        clip_slot_list = clip_slots_wrapper.find("ClipSlotList")
        if clip_slot_list is None:
            logger.debug("ClipSlotList not found, creating one")
            clip_slot_list = ET.SubElement(clip_slots_wrapper, "ClipSlotList")
        
        # Get the current number of clip slots
        existing_slots = clip_slot_list.findall("ClipSlot")
        slot_id = len(existing_slots)
        
        # Create ClipSlot container
        clip_slot = ET.SubElement(clip_slot_list, "ClipSlot")
        clip_slot.set('Id', str(slot_id))
        
        # Create AudioClip element with proper file reference
        audio_clip = ET.SubElement(clip_slot, "AudioClip")
        audio_clip.set('Id', '0')
        audio_clip.set('Time', str(int(beat_position)))
        
        # Basic audio clip properties
        lom_id = ET.SubElement(audio_clip, "LomId")
        lom_id.set('Value', '0')
        
        name_elem = ET.SubElement(audio_clip, "Name")
        name_elem.set('Value', guide_stem.filename)
        
        annotation = ET.SubElement(audio_clip, "Annotation")
        annotation.set('Value', '')
        
        color = ET.SubElement(audio_clip, "Color")
        color.set('Value', '47')  # Blue color
        
        # File reference for the guide stem (absolute path)
        sample = ET.SubElement(audio_clip, "Sample")
        file_ref = ET.SubElement(sample, "FileRef")
        file_ref.set('Source', 'Absolute')
        
        # Path to the guide stem file
        path_elem = ET.SubElement(file_ref, "Path")
        path_elem.set('Value', str(guide_stem.path))
        
        logger.info(f"Added audio clip: {guide_stem.filename} at beat {beat_position} to Guide track (slot {slot_id})")

    def _create_audio_track(
        self,
        liveset: ET.Element,
        tracks: ET.Element,
        track_name: str,
        stem_type: str,
        track_color: Optional[str] = None,
        parent_group_id: Optional[int] = None,
        send_indexes: Optional[List[int]] = None,
        insert_index: Optional[int] = None,
    ) -> Optional[ET.Element]:
        """Create a new blank audio track without depending on the current template's tracks."""
        try:
            new_track = copy.deepcopy(self.blank_audio_track_template)
            next_id = self._next_available_id(liveset)
            new_track.set('Id', str(next_id))
            next_id += 1

            self._resize_track_sends(new_track, self._get_template_send_count(tracks), liveset)

            clip_slot_count = self._get_template_clip_slot_count(tracks)
            if clip_slot_count > 0:
                self._resize_track_clip_slots(new_track, clip_slot_count)

            next_id = self._remap_audio_track_internal_ids(new_track, next_id)

            self._set_track_name(new_track, track_name)
            self._set_track_color(new_track, track_color)
            self._set_track_volume(new_track, 1.0)
            self._set_track_group_id(new_track, parent_group_id)

            self._configure_generated_audio_track_routing(new_track, send_indexes or [])

            for selected_elem in new_track.iter('IsContentSelectedInDocument'):
                selected_elem.set('Value', 'false')

            target_index = insert_index if insert_index is not None else self._get_audio_track_insert_index(tracks, stem_type)
            tracks.insert(target_index, new_track)
            self._update_next_pointee_id(liveset)

            logger.info(
                f"Created generated audio track ID={new_track.get('Id')} '{track_name}'"
            )
            return new_track

        except Exception as e:
            logger.error(f"Failed to create audio track '{track_name}': {e}", exc_info=True)
            return None

    def _create_guide_audio_track(self, liveset: ET.Element, tracks: ET.Element, track_name: str) -> Optional[ET.Element]:
        """Create the shared guide audio track using the guide routing profile."""
        return self._create_audio_track(
            liveset,
            tracks,
            track_name,
            'guide',
            send_indexes=self._special_bus_send_indexes('guide'),
        )

    def _create_group_track(
        self,
        liveset: ET.Element,
        tracks: ET.Element,
        track_name: str,
        track_color: Optional[str] = None,
        parent_group_id: Optional[int] = None,
        stem_type: Optional[str] = None,
        send_indexes: Optional[List[int]] = None,
        insert_index: Optional[int] = None,
    ) -> Optional[ET.Element]:
        """Create a new GroupTrack by cloning a real template group from the source set."""
        try:
            template_group = self._find_group_track_template(tracks)
            if template_group is None:
                logger.error("No GroupTrack template found in source set")
                return None

            new_track = copy.deepcopy(template_group)
            next_id = self._next_available_id(liveset)
            new_track.set('Id', str(next_id))
            next_id += 1

            # Strip any effects (e.g. reverb on the PADS template) from the clone.
            devices_elem = new_track.find('DeviceChain/DeviceChain/Devices')
            if devices_elem is not None:
                for device in list(devices_elem):
                    devices_elem.remove(device)

            next_id = self._remap_audio_track_internal_ids(new_track, next_id)
            self._set_track_name(new_track, track_name)
            self._set_track_color(new_track, track_color)
            self._set_track_volume(new_track, 1.0)
            self._configure_generated_group_track(new_track, parent_group_id, stem_type, send_indexes)

            for selected_elem in new_track.iter('IsContentSelectedInDocument'):
                selected_elem.set('Value', 'false')

            target_index = insert_index if insert_index is not None else self._get_generated_track_insert_index(tracks)
            tracks.insert(target_index, new_track)
            self._update_next_pointee_id(liveset)

            logger.info(
                f"Created generated group track ID={new_track.get('Id')} '{track_name}'"
            )
            return new_track

        except Exception as e:
            logger.error(f"Failed to create group track '{track_name}': {e}", exc_info=True)
            return None

    def _add_midi_clips_for_song(
        self,
        tracks: ET.Element,
        midi_track_idx: int,
        song,
        beat_position: float,
        guide_wav: Optional[AudioStem] = None,
        bpm: float = 120,
    ) -> None:
        """Create MIDI clips in ArrangerAutomation/Events for arrangement playback."""
        if not song.arrangement or not song.arrangement.sequence:
            logger.debug(f"No arrangement sequence for {song.title}")
            return
        
        sequence = song.arrangement.sequence
        num_sections = len(sequence)
        
        # Get MIDI track
        midi_tracks = tracks.findall(".//MidiTrack")
        if midi_track_idx >= len(midi_tracks):
            logger.warning(f"MIDI track index {midi_track_idx} out of range")
            return
        
        midi_track = midi_tracks[midi_track_idx]
        
        # Find the ArrangerAutomation/Events structure (where MIDI arrangement clips go)
        clip_timeable = midi_track.find(".//ClipTimeable")
        if clip_timeable is None:
            logger.error("ClipTimeable not found in MIDI track")
            return
        
        arranger_automation = clip_timeable.find("ArrangerAutomation")
        if arranger_automation is None:
            logger.error("ArrangerAutomation not found in ClipTimeable")
            return
        
        events = arranger_automation.find("Events")
        if events is None:
            logger.warning("Events not found, creating it")
            events = ET.SubElement(arranger_automation, "Events")

        section_timings = self._get_guide_aligned_section_timings(
            guide_wav,
            sequence,
            beat_position,
            bpm,
            song.arrangement.meter if song.arrangement else None,
        )
        if section_timings is None:
            template_intro_duration = self.TEMPLATE_ARRANGEMENT_INTRO_BEATS
            available_song_duration = 240 - template_intro_duration
            beats_per_section = available_song_duration / num_sections if num_sections > 0 else available_song_duration
            section_timings = [
                {
                    'name': section_name,
                    'start': beat_position + template_intro_duration + (section_idx * beats_per_section),
                    'duration': beats_per_section,
                }
                for section_idx, section_name in enumerate(sequence)
            ]

            logger.info(f"Adding {num_sections} evenly-spaced MIDI clips for '{song.title}'")
            logger.info(
                f"  Song starts at beat {beat_position}, arrangement sections start at beat {beat_position + template_intro_duration}"
            )
            logger.info(f"  {beats_per_section:.1f} beats per section across {available_song_duration} available beats")
        else:
            logger.info(f"Adding {len(section_timings)} guide-aligned MIDI clips for '{song.title}'")
        
        # Get the highest existing MidiClip ID
        existing_clips = events.findall("MidiClip")
        max_id = 0
        for clip in existing_clips:
            try:
                clip_id = int(clip.get('Id', '0'))
                max_id = max(max_id, clip_id)
            except ValueError:
                pass

        logger.info(f"Adding {num_sections} MIDI clips for '{song.title}' to ArrangerAutomation (starting at ID {max_id + 1})")

        for section_idx, section_timing in enumerate(section_timings):
            # Create the MidiClip element directly in Events
            clip_id = max_id + section_idx + 1
            midi_clip = self._create_midi_clip_element(
                name=section_timing['name'],
                beat_position=section_timing['start'],
                duration=section_timing['duration'],
                clip_id=clip_id
            )
            events.append(midi_clip)

            logger.debug(
                f"  Added MIDI clip: {section_timing['name']} at beat {section_timing['start']:.2f} "
                f"for {section_timing['duration']:.2f} beats (ID {clip_id})"
            )

    def _get_clip_color(self, section_name: str) -> int:
        """Get color code for a clip based on section type.
        
        Ableton color codes (extracted from user's manually-selected colors):
        Intro=58, Verse=63, Chorus=56, Bridge=68, 
        Turnaround=66, Interlude=66, Instrumental=66, Tag=65, Ending=69
        """
        section_lower = section_name.lower()
        
        if 'verse' in section_lower:
            return 63  # Light blue/cyan
        elif 'chorus' in section_lower:
            return 56  # Pink/magenta
        elif 'bridge' in section_lower:
            return 68  # Purple
        elif 'turnaround' in section_lower or 'turn' in section_lower:
            return 66  # Teal
        elif 'tag' in section_lower:
            return 65  # Blue
        elif 'ending' in section_lower or 'outro' in section_lower:
            return 69  # Dark purple
        elif 'intro' in section_lower:
            return 58  # Cyan
        elif 'interlude' in section_lower or 'inter' in section_lower:
            return 66  # Teal
        elif 'instrumental' in section_lower or 'inst' in section_lower:
            return 66  # Teal
        else:
            return 58  # Default cyan

    def _create_midi_clip_from_template(
        self,
        template_clip: Optional[ET.Element],
        name: str,
        beat_position: float,
        duration: float,
        clip_id: int,
        color_code: Optional[int] = None,
        preserve_loop_values: bool = False,
    ) -> Optional[ET.Element]:
        """Create a MidiClip by copying a template clip and updating its timeline fields."""
        if template_clip is None:
            logger.error(f"No template MidiClip available for '{name}'")
            return None

        clip = copy.deepcopy(template_clip)
        clip_end = beat_position + duration

        clip.set('Id', str(clip_id))
        clip.set('Time', self._format_beat_value(beat_position))

        name_elem = clip.find('Name')
        if name_elem is not None:
            name_elem.set('Value', name)

        if color_code is not None:
            color_elem = clip.find('Color')
            if color_elem is not None:
                color_elem.set('Value', str(color_code))

        current_start = clip.find('CurrentStart')
        if current_start is not None:
            current_start.set('Value', self._format_beat_value(beat_position))

        current_end = clip.find('CurrentEnd')
        if current_end is not None:
            current_end.set('Value', self._format_beat_value(clip_end))

        logger.debug(f"Creating clip '{name}': beat_position={beat_position:.2f}, duration={duration:.2f}")
        logger.debug(f"  Set CurrentStart={beat_position:.2f}, CurrentEnd={clip_end:.2f}")

        for elem in clip.iter():
            if elem.tag == 'Loop' and not preserve_loop_values:
                for child in elem:
                    if child.tag in {'LoopEnd', 'OutMarker', 'HiddenLoopEnd'}:
                        child.set('Value', self._format_beat_value(duration))
                    elif child.tag in {'LoopStart', 'StartRelative', 'HiddenLoopStart'}:
                        child.set('Value', self._format_beat_value(0))

            if elem.tag == 'TimeSelection':
                for child in elem:
                    if child.tag == 'EndTime':
                        child.set('Value', self._format_beat_value(duration))

        return clip

    def _create_midi_clip_element(self, name: str, beat_position: float, duration: float, clip_id: int) -> ET.Element:
        """Create a MidiClip by copying the arrangement template clip and modifying key fields.
        
        This approach mirrors manual workflow: copy a working clip, then rename it and adjust position.
        """
        color_code = self._get_clip_color(name)
        return self._create_midi_clip_from_template(
            template_clip=self.template_midi_clip,
            name=name,
            beat_position=beat_position,
            duration=duration,
            clip_id=clip_id,
            color_code=color_code,
        )



    def _generate_output_path(self, service_type_name: str, service_date) -> Path:
        """Generate the output path for the .als file.
        
        First export keeps the base name; later exports get a numbered regen suffix.
        Examples:
        - SMC Weekend Services 2026-04-26.als
        - SMC Weekend Services 2026-04-26 - Regen 1.als
        
        File goes directly to: /output_folder/Service_Type YYYY-MM-DD.als
        """
        # Clean service type name (keep spaces but remove special chars)
        safe_title = "".join(c for c in service_type_name if c.isalnum() or c in (' ', '-')).rstrip()
        
        # Format date as YYYY-MM-DD
        date_str = service_date.strftime("%Y-%m-%d")
        
        # Create filename: "Service Type YYYY-MM-DD.als"
        base_name = f"{safe_title} {date_str}"
        base_path = self.output_folder / f"{base_name}.als"
        if not base_path.exists():
            return base_path

        regen_index = 1
        while True:
            regen_path = self.output_folder / f"{base_name} - Regen {regen_index}.als"
            if not regen_path.exists():
                return regen_path
            regen_index += 1

    def _save_project(self, tree: ET.ElementTree, als_file_path: Path) -> None:
        """Save the modified project as a .als file.
        
        Creates: /output_folder/Service_Type YYYY-MM-DD.als (gzip-compressed XML)
        """
        try:
            # Create output folder if it doesn't exist
            als_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert the modified XML tree to string WITH the XML declaration
            xml_string = ET.tostring(tree.getroot(), encoding='unicode')
            
            # Prepend the XML declaration if not present
            if not xml_string.startswith('<?xml'):
                xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_string
            
            # Convert back to bytes
            xml_content = xml_string.encode('utf-8')

            if self.template_format == 'gzip':
                # For gzip: Write XML with proper headers and compression
                with gzip.GzipFile(als_file_path, 'wb', compresslevel=9, mtime=0) as f:
                    f.write(xml_content)
                logger.debug(f"Saved project as gzip format with XML declaration")

            elif self.template_format == 'zip':
                # For ZIP: Extract, modify, and re-zip
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_dir_path = Path(temp_dir)

                    # Copy the template ZIP structure
                    with zipfile.ZipFile(self.template_path, 'r') as template_zip:
                        template_zip.extractall(temp_dir_path)

                        # Find and replace the Project.xml file
                        project_xml_path = None
                        for file_path in template_zip.namelist():
                            if file_path.endswith('Project.xml'):
                                project_xml_path = file_path
                                break

                        if not project_xml_path:
                            # Try to find any .xml file
                            for file_path in template_zip.namelist():
                                if file_path.endswith('.xml'):
                                    project_xml_path = file_path
                                    break

                    # Write the modified XML
                    if project_xml_path:
                        xml_file_path = temp_dir_path / project_xml_path
                        xml_file_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(xml_file_path, 'wb') as f:
                            f.write(xml_content)
                        logger.debug(f"Updated {project_xml_path} in temporary directory")

                    # Create the output ZIP file inside the project folder
                    with zipfile.ZipFile(als_file_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:
                        # Walk through the temporary directory and add all files
                        for root_dir, dirs, files in os.walk(temp_dir_path):
                            for file in files:
                                file_path = Path(root_dir) / file
                                arcname = file_path.relative_to(temp_dir_path)
                                output_zip.write(file_path, arcname)
                                logger.debug(f"Added {arcname} to output ZIP")

            else:
                # Default to gzip if format is unknown
                logger.warning("Template format unknown, defaulting to gzip")
                with gzip.GzipFile(als_file_path, 'wb', compresslevel=9, mtime=0) as f:
                    f.write(xml_content)

            logger.info(f"Project file saved to: {als_file_path}")

        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            raise