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

        # Ensure output folder exists
        self.output_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"Ableton service initialized with template: {self.template_path}")

    def generate_setlist(self, service_title: str, stem_matches: Dict[str, StemMatch]) -> Optional[Path]:
        """Generate an Ableton Live setlist from stem matches.

        Args:
            service_title: Title for the service/setlist
            stem_matches: Dictionary of song titles to stem matches

        Returns:
            Path to the generated .als file, or None if failed
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

            # Modify the template with service data
            self._populate_setlist(template_tree, service_title, stem_matches)

            # Save the new project file
            output_path = self._generate_output_path(service_title)
            self._save_project(template_tree, output_path)

            logger.info(f"Generated setlist: {output_path}")
            return output_path

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
                logger.info("Template loaded successfully from gzip format")
                return tree

        except Exception as e:
            logger.error(f"Failed to load template: {e}")
            return None

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

    def _populate_setlist(self, tree: ET.ElementTree, service_title: str, stem_matches: Dict[str, StemMatch]) -> None:
        """Populate the template with service data."""
        root = tree.getroot()

        # Find the LiveSet element
        liveset = root.find('LiveSet')
        if liveset is None:
            logger.error("No LiveSet element found in template")
            return

        # Update the project title
        self._set_project_title(liveset, service_title)

        # Find audio tracks in the template
        audio_tracks = self._find_audio_tracks(liveset)
        logger.info(f"Found {len(audio_tracks)} audio tracks in template")

        # Clear existing clips and populate with stems
        self._populate_tracks_with_stems(liveset, audio_tracks, stem_matches)

        # Add markers track if it doesn't exist
        self._add_markers_track(liveset, stem_matches)

    def _set_project_title(self, liveset: ET.Element, title: str) -> None:
        """Set the project title in the LiveSet."""
        # Look for MasterTrack or create a title annotation
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

    def _find_audio_tracks(self, liveset: ET.Element) -> List[ET.Element]:
        """Find all AudioTrack elements in the LiveSet."""
        tracks_elem = liveset.find('Tracks')
        if tracks_elem is None:
            return []

        audio_tracks = []
        for track in tracks_elem:
            if track.tag == 'AudioTrack':
                audio_tracks.append(track)

        return audio_tracks

    def _populate_tracks_with_stems(self, liveset: ET.Element, audio_tracks: List[ET.Element],
                                   stem_matches: Dict[str, StemMatch]) -> None:
        """Populate audio tracks with stems from matched songs."""
        track_index = 0
        time_position = 0  # Start position in beats

        # Sort songs by some logical order (you might want to customize this)
        sorted_songs = sorted(stem_matches.keys())

        for song_title in sorted_songs:
            stem_match = stem_matches[song_title]

            # Add a marker for the song start
            self._add_song_marker(liveset, song_title, time_position)

            # Add stems for this song
            for stem in stem_match.stems:
                if track_index < len(audio_tracks):
                    track = audio_tracks[track_index]
                    self._add_stem_to_track(track, stem, time_position)
                    track_index += 1

            # Estimate song duration (you might want to get this from audio file metadata)
            song_duration = 240  # 4 minutes at 120 BPM
            time_position += song_duration

    def _add_stem_to_track(self, track: ET.Element, stem: AudioStem, start_time: float) -> None:
        """Add a stem clip to an audio track."""
        # Update track name
        name_elem = track.find(".//Name")
        if name_elem is not None:
            effective_name = name_elem.find("EffectiveName")
            if effective_name is not None:
                effective_name.set('Value', f"{stem.song_title} - {stem.stem_type.title()}")

        # Find or create ArrangementClipsListWrapper
        arrangement_clips = track.find(".//ArrangementClipsListWrapper")
        if arrangement_clips is None:
            # Create arrangement clips wrapper
            arrangement_clips = ET.SubElement(track, "ArrangementClipsListWrapper")
            clips_list = ET.SubElement(arrangement_clips, "ArrangementClips")
            clips_list.set('TimeUnit', 'beats')

        clips_list = arrangement_clips.find("ArrangementClips")
        if clips_list is None:
            clips_list = ET.SubElement(arrangement_clips, "ArrangementClips")
            clips_list.set('TimeUnit', 'beats')

        # Create a new clip
        clip = ET.SubElement(clips_list, "Clip")
        clip.set('Time', str(start_time))
        clip.set('Loop', '1')

        # Add clip name
        clip_name = ET.SubElement(clip, "Name")
        clip_name.set('Value', f"{stem.stem_type.title()}")

        # Add audio file reference
        sample_ref = ET.SubElement(clip, "SampleRef")
        file_ref = ET.SubElement(sample_ref, "FileRef")
        relative_path = ET.SubElement(file_ref, "RelativePath")
        relative_path.set('Value', str(stem.path))

        # Add clip time parameters
        current_start = ET.SubElement(clip, "CurrentStart")
        current_start.set('Value', '0')
        current_end = ET.SubElement(clip, "CurrentEnd")
        current_end.set('Value', '4')  # Default 4 beats

    def _add_song_marker(self, liveset: ET.Element, song_title: str, time_position: float) -> None:
        """Add a marker for song start."""
        # Find or create Locators element
        locators = liveset.find("Locators")
        if locators is None:
            locators = ET.SubElement(liveset, "Locators")

        # Create a new locator
        locator = ET.SubElement(locators, "Locator")
        locator.set('Time', str(time_position))
        locator.set('Name', song_title)
        locator.set('Annotation', f"Start of {song_title}")

    def _add_markers_track(self, liveset: ET.Element, stem_matches: Dict[str, StemMatch]) -> None:
        """Add or update a markers track."""
        tracks_elem = liveset.find('Tracks')
        if tracks_elem is None:
            return

        # Check if markers track already exists
        markers_track = None
        for track in tracks_elem:
            name_elem = track.find(".//Name/EffectiveName")
            if name_elem is not None and 'marker' in name_elem.get('Value', '').lower():
                markers_track = track
                break

        if markers_track is None:
            # Create a new MIDI track for markers
            markers_track = ET.Element('MidiTrack')
            markers_track.set('Id', '9999')  # Use a high ID to avoid conflicts
            tracks_elem.append(markers_track)

            # Add basic track structure
            self._initialize_midi_track(markers_track, "Markers")

    def _initialize_midi_track(self, track: ET.Element, name: str) -> None:
        """Initialize a basic MIDI track structure."""
        # Add Name
        name_elem = ET.SubElement(track, "Name")
        effective_name = ET.SubElement(name_elem, "EffectiveName")
        effective_name.set('Value', name)
        user_name = ET.SubElement(name_elem, "UserName")
        user_name.set('Value', name)

        # Add Color (use a distinctive color)
        color = ET.SubElement(track, "Color")
        color.set('Value', '55')  # Blue color

        # Add other required elements
        ET.SubElement(track, "TrackDelay")
        ET.SubElement(track, "AutomationEnvelopes")
        ET.SubElement(track, "TrackGroupId")
        ET.SubElement(track, "TrackUnfolded")
        ET.SubElement(track, "DevicesListWrapper")
        ET.SubElement(track, "ClipSlotsListWrapper")
        ET.SubElement(track, "ArrangementClipsListWrapper")
        ET.SubElement(track, "TakeLanesListWrapper")
        ET.SubElement(track, "ViewData")
        ET.SubElement(track, "TakeLanes")
        ET.SubElement(track, "LinkedTrackGroupId")
        ET.SubElement(track, "SavedPlayingSlot")
        ET.SubElement(track, "SavedPlayingOffset")
        ET.SubElement(track, "Freeze")
        ET.SubElement(track, "NeedArrangerRefreeze")
        ET.SubElement(track, "PostProcessFreezeClips")
        ET.SubElement(track, "DeviceChain")

    def _generate_output_path(self, service_title: str) -> Path:
        """Generate output path for the new project file."""
        # Sanitize service title for filename
        safe_title = "".join(c for c in service_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_title = safe_title.replace(' ', '_')

        filename = f"{safe_title}.als"
        return self.output_folder / filename

    def _save_project(self, tree: ET.ElementTree, output_path: Path) -> None:
        """Save the modified project as a proper .als file (ZIP or gzip format)."""
        try:
            # Convert the modified XML tree to string
            xml_content = ET.tostring(tree.getroot(), encoding='utf-8')

            if self.template_format == 'zip':
                # Save as ZIP-based .als file
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

                    # Create the output ZIP file
                    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:
                        # Walk through the temporary directory and add all files
                        for root_dir, dirs, files in os.walk(temp_dir_path):
                            for file in files:
                                file_path = Path(root_dir) / file
                                arcname = file_path.relative_to(temp_dir_path)
                                output_zip.write(file_path, arcname)
                                logger.debug(f"Added {arcname} to output ZIP")

            elif self.template_format == 'gzip':
                # Save as gzip-based .als file
                with gzip.open(output_path, 'wb') as f:
                    f.write(xml_content)
                logger.debug(f"Saved project as gzip format")

            else:
                # Default to gzip if format is unknown
                logger.warning("Template format unknown, defaulting to gzip")
                with gzip.open(output_path, 'wb') as f:
                    f.write(xml_content)

            logger.info(f"Project saved to: {output_path}")

        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            raise