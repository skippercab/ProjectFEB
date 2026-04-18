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

    def generate_setlist(self, service_title: str, stem_matches: Dict[str, StemMatch], plan_songs: Optional[List] = None) -> Optional[Path]:
        """Generate an Ableton Live setlist from stem matches.

        Args:
            service_title: Title for the service/setlist
            stem_matches: Dictionary of song titles to stem matches
            plan_songs: Optional ordered list of PCOSong objects with key information

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
            self._populate_setlist(template_tree, service_title, stem_matches, plan_songs)

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
        # Calculate total timeline beats (assume 120 BPM baseline, each song gets ~240 beats or its duration)
        current_beat_position = 0
        
        logger.info(f"Starting to add guides and MIDI clips for {len(plan_songs)} songs")
        
        for song in plan_songs:
            if song.title not in stem_matches:
                logger.warning(f"Song '{song.title}' not in stem matches, skipping guide/MIDI")
                continue
            
            stem_match = stem_matches[song.title]
            
            # Find guide stem for this song
            guide_stems = [s for s in stem_match.stems if s.stem_type == 'guide']
            if not guide_stems:
                logger.debug(f"No guide stem found for '{song.title}'")
            else:
                logger.info(f"Adding guide stem for '{song.title}' at beat {current_beat_position}")
                self._add_guide_stem_to_track(liveset, guide_stems[0], current_beat_position)
            
            # Add MIDI clips with arrangement sequence
            if song.arrangement and song.arrangement.sequence:
                logger.info(f"Adding MIDI clips for '{song.title}' with {len(song.arrangement.sequence)} sections")
                self._add_midi_clips_for_song(liveset, song, current_beat_position)
            
            # Estimate beat duration for this song (simplified: assume 120 BPM, ~240 beats per song)
            # In reality, this should be based on the actual guide audio duration
            song_duration_beats = 240
            current_beat_position += song_duration_beats

    def _add_guide_stem_to_track(self, liveset: ET.Element, guide_stem: AudioStem, beat_position: float) -> None:
        """Add a guide stem audio clip to track 3 (Guide track)."""
        # Find the MasterTrack to get reference to other tracks
        master_track = liveset.find(".//MasterTrack")
        if master_track is None:
            logger.warning("Could not find MasterTrack to reference audio tracks")
            return
        
        # Find the Guide track (typically track 3, but search by name)
        tracks = liveset.find(".//Tracks")
        if tracks is None:
            logger.warning("Could not find Tracks element")
            return
        
        guide_track = None
        track_index = 0
        for track in tracks.findall(".//AudioTrack"):
            track_name_elem = track.find(".//Name/EffectiveName")
            if track_name_elem is not None and "Guide" in track_name_elem.get('Value', ''):
                guide_track = track
                logger.info(f"Found Guide track at index {track_index}")
                break
            track_index += 1
        
        if not guide_track:
            logger.warning("Guide track not found, skipping audio placement")
            return
        
        # Create clip for the guide
        # Note: This is a simplified implementation. Full implementation would need to:
        # 1. Create proper Ableton clip with file reference
        # 2. Set the clip length based on audio file duration
        # 3. Handle file path references correctly
        logger.info(f"Would place guide stem at beat {beat_position}: {guide_stem.file_path}")
        # Actual implementation would create XML elements for clips here

    def _add_midi_clips_for_song(self, liveset: ET.Element, song, beat_position: float) -> None:
        """Create MIDI clips with arrangement sequence markers for a song."""
        if not song.arrangement or not song.arrangement.sequence:
            return
        
        sequence = song.arrangement.sequence
        num_sections = len(sequence)
        
        # Estimate beats per section (simplified: 240 beats total for song)
        song_duration_beats = 240
        beats_per_section = song_duration_beats / num_sections if num_sections > 0 else song_duration_beats
        
        logger.info(f"Song '{song.title}': Adding MIDI clips for {num_sections} sections")
        
        for section_idx, section_name in enumerate(sequence):
            section_beat_position = beat_position + (section_idx * beats_per_section)
            logger.debug(f"  Section {section_idx}: {section_name} at beat {section_beat_position}")
            
            # In a full implementation, this would:
            # 1. Create a MIDI clip in a dedicated MIDI track
            # 2. Add a note with name=section_name
            # 3. Position it at section_beat_position
            # For now, we log the structure

    def _generate_output_path(self, service_title: str) -> Path:
        """Generate output path for the new project file."""
        # Sanitize service title for filename
        safe_title = "".join(c for c in service_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_title = safe_title.replace(' ', '_')

        filename = f"{safe_title}.als"
        return self.output_folder / filename

    def _save_project(self, tree: ET.ElementTree, output_path: Path) -> None:
        """Save the modified project as a proper .als file.
        
        For gzip format: Writes XML with proper declaration and compresses.
        For ZIP format: Extracts, modifies, and re-zips.
        """
        try:
            # Convert the modified XML tree to string WITH the XML declaration
            xml_string = ET.tostring(tree.getroot(), encoding='unicode')
            
            # Prepend the XML declaration if not present
            if not xml_string.startswith('<?xml'):
                xml_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_string
            
            # Convert back to bytes
            xml_content = xml_string.encode('utf-8')

            if self.template_format == 'gzip':
                # For gzip: Write XML with proper headers and compression
                with gzip.GzipFile(output_path, 'wb', compresslevel=9, mtime=0) as f:
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

                    # Create the output ZIP file
                    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as output_zip:
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
                with gzip.GzipFile(output_path, 'wb', compresslevel=9, mtime=0) as f:
                    f.write(xml_content)

            logger.info(f"Project saved to: {output_path}")

        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            raise