"""Ableton Live project file generation and manipulation service."""

import gzip
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from loguru import logger
import shutil
import tempfile
import os
import copy

from ..core.config import AbletonConfig
from .multitracks_service import AudioStem, StemMatch

@dataclass
class AbletonTrack:
    """Represents an Ableton Live track."""
    id: str
    name: str
    track_type: str  # AudioTrack, MidiTrack, GroupTrack, etc.
    color: Optional[int] = None
    is_group_track: bool = False

class AbletonService:
    """Service for working with Ableton Live project files."""

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

        # Ensure output folder exists
        self.output_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"Ableton service initialized with template: {self.template_path}")

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
            # Load and parse the template
            template_tree = self._load_template()
            if not template_tree:
                return None

            # Convert to target Ableton version if needed
            self._convert_version(template_tree)

            # Create a project title for the Ableton window from service type and date
            project_title = f"{service_type_name} {service_date.strftime('%Y-%m-%d')}"
            
            # Modify the template with service data
            self._populate_setlist(template_tree, project_title, stem_matches, plan_songs)

            # Save the new project file
            als_file_path = self._generate_output_path(service_type_name, service_date)
            self._save_project(template_tree, als_file_path)

            logger.info(f"Generated setlist: {als_file_path}")
            return als_file_path

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
        """Extract a working template MidiClip (INTRO) to use as a base for copies.
        
        The INTRO clip is known to render properly in Ableton, so we duplicate
        its exact structure when creating new clips. This ensures new clips have
        all the necessary fields for Ableton to display them.
        """
        try:
            # Find the INTRO MidiClip in ArrangerAutomation/Events
            # This is a known working clip that displays properly in Ableton
            for midi_track in root.findall('.//MidiTrack'):
                clip_timeable = midi_track.find('.//ClipTimeable')
                if clip_timeable is not None:
                    events = clip_timeable.find('.//ArrangerAutomation/Events')
                    if events is not None:
                        # Look for the INTRO clip specifically (it's known to work)
                        for midi_clip in events.findall('MidiClip'):
                            name_elem = midi_clip.find('Name')
                            if name_elem is not None:
                                clip_name = name_elem.get('Value', '')
                                if clip_name == 'INTRO':
                                    # Store a deep copy of this working clip
                                    self.template_midi_clip = copy.deepcopy(midi_clip)
                                    logger.info(f"Extracted working template INTRO MidiClip: Id={midi_clip.get('Id')}")
                                    return
                        
                        # Fallback: if no INTRO found, use first clip
                        midi_clip = events.find('MidiClip')
                        if midi_clip is not None:
                            name_elem = midi_clip.find('Name')
                            clip_name = name_elem.get('Value', 'unknown') if name_elem is not None else 'unknown'
                            self.template_midi_clip = copy.deepcopy(midi_clip)
                            logger.info(f"Extracted template MidiClip (fallback): Id={midi_clip.get('Id')}, Name={clip_name}")
                            return
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

    def _populate_setlist(self, tree: ET.ElementTree, service_title: str, stem_matches: Dict[str, StemMatch], plan_songs: Optional[List] = None) -> None:
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
        
        # Add guide stems and MIDI clips for each song (if arrangement data available)
        if plan_songs:
            self._add_guides_and_midi_clips(liveset, stem_matches, plan_songs)
            # Add tempo mapping for each song
            self._add_tempo_mapping(liveset, plan_songs)

    def _populate_existing_markers(self, liveset: ET.Element, stem_matches: Dict[str, StemMatch], plan_songs: Optional[List] = None) -> None:
        """Replace template's placeholder markers (1), 2), 3), 4)) with actual song titles and keys."""
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
        songs_with_keys = []
        if plan_songs:
            # Use the ordered songs from the plan
            for song in plan_songs:
                if song.title in stem_matches:
                    key_suffix = f" ({song.key_name})" if song.key_name else ""
                    songs_with_keys.append((song.title, key_suffix))
            logger.info(f"Using {len(songs_with_keys)} songs in API order")
        else:
            # Fallback to alphabetically sorted stems
            sorted_songs = sorted(stem_matches.keys())
            songs_with_keys = [(title, "") for title in sorted_songs]
            logger.info(f"Using {len(songs_with_keys)} songs in alphabetical order (no plan_songs provided)")

        # Create mapping of placeholder names (1), 2), 3), 4)) to song titles with keys
        placeholder_map = {str(i+1) + ")": songs_with_keys[i] for i in range(min(len(songs_with_keys), 4))}
        logger.debug(f"Placeholder mapping: {placeholder_map}")

        # Replace only the placeholder markers with actual song titles
        for locator in existing_locators:
            name_elem = locator.find("Name")
            if name_elem is not None:
                old_name = name_elem.get('Value', '')
                # Check if this is a placeholder marker
                if old_name in placeholder_map:
                    song_title, key_suffix = placeholder_map[old_name]
                    new_name = f"{old_name} {song_title}{key_suffix}"
                    name_elem.set('Value', new_name)
                    logger.info(f"Replaced placeholder '{old_name}' with '{new_name}'")
                else:
                    logger.debug(f"Marker '{old_name}' is not a placeholder, leaving unchanged")
            else:
                logger.warning(f"Locator has no Name element")

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

    def _add_guides_and_midi_clips(self, liveset: ET.Element, stem_matches: Dict[str, StemMatch], plan_songs: List) -> None:
        """Add guide stems to track 3 and create MIDI clips with arrangement sequence."""
        # Get locators to find song start positions
        locators_map = self._get_locators_map(liveset)
        
        logger.info(f"Starting to add guides and MIDI clips for {len(plan_songs)} songs")
        logger.info(f"Found {len(locators_map)} song markers: {list(locators_map.keys())}")
        
        # Track index for Guide track (typically 2, but find it)
        tracks = liveset.find(".//Tracks")
        if tracks is None:
            logger.error("No Tracks element found")
            return
        
        guide_track_idx = self._find_track_by_name(tracks, "Guide")
        
        # Create a brand new MIDI track for the arrangement clips at the top
        midi_track_idx = self._create_arrangement_track(tracks)
        
        if guide_track_idx is None:
            logger.warning("Guide track not found")
        if midi_track_idx is None:
            logger.warning("Failed to create arrangement track")
        
        # Process each song
        for song_idx, song in enumerate(plan_songs):
            if song.title not in stem_matches:
                logger.warning(f"Song '{song.title}' not in stem matches, skipping guide/MIDI")
                continue
            
            # Find the marker name for this song, including key if available (e.g., "1) The Blood (B)")
            marker_key = f"{song_idx + 1}) {song.title}"
            if song.key_name:
                marker_key += f" ({song.key_name})"
            
            if marker_key not in locators_map:
                logger.warning(f"Marker '{marker_key}' not found in template")
                continue
            
            song_start_beat = locators_map[marker_key]
            logger.info(f"Song {song_idx + 1} '{song.title}' starts at beat {song_start_beat}")
            
            stem_match = stem_matches[song.title]
            
            # Add guide stem to track 3
            if guide_track_idx is not None:
                guide_stems = [s for s in stem_match.stems if s.stem_type == 'guide']
                if guide_stems:
                    logger.info(f"Adding guide stem for '{song.title}' at beat {song_start_beat}")
                    self._add_guide_stem_to_track(tracks, guide_track_idx, guide_stems[0], song_start_beat)
                else:
                    logger.debug(f"No guide stem found for '{song.title}'")
            
            # Add MIDI clips with arrangement sequence
            if midi_track_idx is not None and song.arrangement and song.arrangement.sequence:
                logger.info(f"Adding MIDI clips for '{song.title}' with {len(song.arrangement.sequence)} sections")
                self._add_midi_clips_for_song(tracks, midi_track_idx, song, song_start_beat)

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
                if not song.arrangement or not song.arrangement.bpm:
                    logger.warning(f"Song '{song.title}' has no arrangement BPM")
                    song_bpms.append(120)  # Default to 120
                else:
                    song_bpms.append(song.arrangement.bpm)
                    logger.info(f"Song {song_idx + 1} '{song.title}' BPM: {song.arrangement.bpm}")
            
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

    def _create_arrangement_track(self, tracks: ET.Element) -> Optional[int]:
        """Create a brand new MIDI track at the top for arrangement clips.
        
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
        
        # Set the track name to "Arrangement"
        name_elem = new_track.find(".//Name/EffectiveName")
        if name_elem is not None:
            name_elem.set('Value', 'Arrangement')
        
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

    def _add_midi_clips_for_song(self, tracks: ET.Element, midi_track_idx: int, song, beat_position: float) -> None:
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
        
        # Estimate beats per section (allocate remaining time after template intro)
        # Template has COUNT (0-4) and INTRO (4-20), so real content starts at beat 20
        # Allocate remaining 220 beats (240 - 20) for arrangement sections
        template_intro_duration = 20  # beats 4-20
        available_song_duration = 240 - template_intro_duration
        beats_per_section = available_song_duration / num_sections if num_sections > 0 else available_song_duration
        
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
        logger.info(f"  Song starts at beat {beat_position}, arrangement sections start at beat {beat_position + template_intro_duration}")
        logger.info(f"  {beats_per_section:.1f} beats per section across {available_song_duration} available beats")
        
        for section_idx, section_name in enumerate(sequence):
            # Start arrangement sections after the template intro (which ends at beat 20)
            section_beat_position = beat_position + template_intro_duration + (section_idx * beats_per_section)
            section_duration = beats_per_section
            
            # Create the MidiClip element directly in Events
            clip_id = max_id + section_idx + 1
            midi_clip = self._create_midi_clip_element(
                name=section_name, 
                beat_position=int(section_beat_position),  # Convert to int for XML
                duration=section_duration,
                clip_id=clip_id
            )
            events.append(midi_clip)
            
            logger.debug(f"  Added MIDI clip: {section_name} at beat {section_beat_position:.1f} (ID {clip_id})")

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

    def _create_midi_clip_element(self, name: str, beat_position: float, duration: float, clip_id: int) -> ET.Element:
        """Create a MidiClip by copying the template clip and modifying key fields.
        
        This approach mirrors manual workflow: copy a working clip, then rename it and adjust position.
        """
        if self.template_midi_clip is None:
            logger.error("No template MidiClip available, cannot create clip")
            return None
        
        # Deep copy the template clip
        clip = copy.deepcopy(self.template_midi_clip)
        
        # Update the key attributes
        beat_position_int = int(beat_position)
        duration_int = int(duration)
        
        clip.set('Id', str(clip_id))
        clip.set('Time', str(beat_position_int))
        
        # Update the name
        name_elem = clip.find('Name')
        if name_elem is not None:
            name_elem.set('Value', name)
        
        # Set color based on section type
        color_code = self._get_clip_color(name)
        color_elem = clip.find('Color')
        if color_elem is not None:
            color_elem.set('Value', str(color_code))
        
        # CRITICAL: Update CurrentStart to match Time (Ableton requires this)
        # When you copy/paste a clip in Ableton, CurrentStart always equals Time
        current_start = clip.find('CurrentStart')
        if current_start is not None:
            current_start.set('Value', str(beat_position_int))
        
        # Update CurrentEnd = Time + duration (the clip's actual duration on timeline)
        current_end = clip.find('CurrentEnd')
        if current_end is not None:
            current_end.set('Value', str(beat_position_int + duration_int))
        
        # Log what we're setting for this clip
        logger.debug(f"Creating clip '{name}': beat_position={beat_position_int}, duration={duration_int}")
        logger.debug(f"  Set CurrentStart={beat_position_int}, CurrentEnd={beat_position_int + duration_int}")
        
        # Update Loop fields (these appear to have longer durations, likely from template)
        # Keep these as relative loop boundaries, not absolute timeline positions
        for elem in clip.iter():
            # For Loop/HiddenLoopEnd (this stays relative to loop, not timeline)
            if elem.tag == 'Loop':
                for child in elem:
                    if child.tag == 'HiddenLoopEnd':
                        child.set('Value', str(duration_int))
                        logger.debug(f"  Set HiddenLoopEnd={duration_int}")
            
            # For TimeSelection/EndTime
            if elem.tag == 'TimeSelection':
                for child in elem:
                    if child.tag == 'EndTime':
                        child.set('Value', str(duration_int))
        
        return clip



    def _generate_output_path(self, service_type_name: str, service_date) -> Path:
        """Generate the output path for the .als file.
        
        Format: Service_Type YYYY-MM-DD.als
        Example: SMC Weekend Services 2026-04-26.als
        
        File goes directly to: /output_folder/Service_Type YYYY-MM-DD.als
        """
        # Clean service type name (keep spaces but remove special chars)
        safe_title = "".join(c for c in service_type_name if c.isalnum() or c in (' ', '-')).rstrip()
        
        # Format date as YYYY-MM-DD
        date_str = service_date.strftime("%Y-%m-%d")
        
        # Create filename: "Service Type YYYY-MM-DD.als"
        als_filename = f"{safe_title} {date_str}.als"
        als_file_path = self.output_folder / als_filename
        
        return als_file_path

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