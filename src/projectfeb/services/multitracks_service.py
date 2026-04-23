"""Multitracks audio stem discovery and matching service."""

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from fuzzywuzzy import fuzz, process
from loguru import logger

from ..core.config import MultitracksConfig

@dataclass
class AudioStem:
    """Represents an audio stem file."""
    path: Path
    filename: str
    stem_type: str  # vocals, drums, bass, guitar, keys, etc.
    song_title: str
    confidence: float = 0.0

@dataclass
class StemMatch:
    """Represents a match between a song and its stems."""
    song_title: str
    stems: List[AudioStem]
    match_confidence: float
    missing_stems: List[str] = None

    def __post_init__(self):
        if self.missing_stems is None:
            self.missing_stems = []

class MultitracksService:
    """Service for discovering and matching Multitracks audio stems."""

    FOLDER_TRAILING_MODIFIERS = {'sw'}

    # Common stem types and their variations - organized by Ableton template groups
    STEM_TYPES = {
        # Perc group - percussion based tracks
        'perc': ['drums', 'drum', 'kit', 'percussion', 'perc', 'alt_drums', 'toms', 'fx', 'loop', 'live'],
        
        # Bass group - low frequency instruments
        'bass': ['bass', 'electric_bass', 'upright_bass', 'moog', 'sub_bass', 'synth_bass', 'bbass', 'keybass'],
        
        # Leads group - typically empty, manual electric guitar selection
        'leads': [],  # Will be populated manually
        
        # Strings group - guitars and orchestral instruments
        'strings': ['eg', 'electric', 'ag', 'acoustic', 'guitar', 'electric_guitar', 'acoustic_guitar', 'gtr', 
                   'strings', 'violin', 'viola', 'cello', 'orchestral', 'ax', 'axe'],
        
        # Keys group - keyboard instruments (anything not in other categories)
        'keys': ['keys', 'keyboard', 'piano', 'organ', 'synth', 'rhodes', 'wurlitzer', 'clav', 'synth_fx', 
                'additional', 'additionals', 'accompaniment', 'strings_pad', 'pad'],
        
        # Vocals group - vocal tracks
        'vocals': ['vocals', 'vocal', 'vox', 'lead_vox', 'bgv', 'backing_vox', 'choir', 'tenor', 'alto', 'soprano', 'bgvs', 'vox_fx'],
        
        # Guide group - metronome/guide tracks (channel 3 in template)
        'guide': ['guide', 'metronome', 'click', 'click_track', 'cue', 'reference']
    }

    def __init__(self, config: MultitracksConfig):
        """Initialize the Multitracks service.

        Args:
            config: Multitracks configuration
        """
        self.config = config
        self.stems_folder = Path(config.stems_folder) if config.stems_folder else None
        self.extracted_archive_dirs: List[Path] = []

        # Build reverse mapping for stem type detection
        self.stem_keywords = {}
        for stem_type, keywords in self.STEM_TYPES.items():
            for keyword in keywords:
                self.stem_keywords[keyword.lower()] = stem_type

        logger.info(f"Multitracks service initialized with folder: {self.stems_folder}")

    def find_stems_for_songs(self, song_titles: List[str]) -> Dict[str, StemMatch]:
        """Find audio stems for a list of songs.

        Args:
            song_titles: List of song titles to find stems for

        Returns:
            Dictionary mapping song titles to StemMatch objects
        """
        if not self.stems_folder or not self.stems_folder.exists():
            logger.error(f"Stems folder not found: {self.stems_folder}")
            return {}

        # Get all available stems
        all_stems = self._discover_all_stems()

        matches = {}
        for song_title in song_titles:
            match = self._find_stems_for_song(song_title, all_stems)
            if match:
                matches[song_title] = match

        logger.info(f"Found stems for {len(matches)} out of {len(song_titles)} songs")
        return matches

    def _discover_all_stems(self) -> List[AudioStem]:
        """Discover all audio stems in the configured folder.
        
        Filters out .zip files and handles duplicate detection (folder vs .zip).
        """
        stems = []

        if not self.stems_folder:
            return stems

        # Supported file extensions
        extensions = [f".{ext}" for ext in self.config.supported_formats]

        try:
            # First pass: collect all items and detect duplicates
            all_items = list(self.stems_folder.iterdir())
            folders = [item for item in all_items if item.is_dir() and not item.name.startswith('.')]
            zip_files = [item for item in all_items if item.is_file() and item.suffix.lower() == '.zip']
            
            # Detect duplicates: same base name, one folder and one .zip
            zip_base_names = {item.stem for item in zip_files}
            folder_names = {folder.name for folder in folders}
            
            duplicates = {}
            for folder in folders:
                if folder.name in zip_base_names:
                    duplicates[folder.name] = {
                        'folder': folder,
                        'zip': next(z for z in zip_files if z.stem == folder.name)
                    }
            
            # Handle duplicates - ask user which to use
            folders_to_process = []
            for folder in folders:
                if folder.name in duplicates:
                    # This is a duplicate - let the user choose
                    chosen_path = self._resolve_duplicate(duplicates[folder.name])
                    if chosen_path and chosen_path.is_dir():
                        folders_to_process.append(chosen_path)
                    logger.warning(f"Duplicate found for '{folder.name}': Using {'folder' if chosen_path == folder else 'zip (not expanded)'}")
                else:
                    # No duplicate, add normally
                    folders_to_process.append(folder)
            
            # Process selected folders
            for song_folder in folders_to_process:
                # Extract clean song title from folder name
                clean_title = self._extract_song_title_from_folder(song_folder.name)

                # Find stems in this song folder
                song_stems = self._find_stems_in_song_folder(song_folder, clean_title, extensions)
                stems.extend(song_stems)

            # Process zip-only songs that do not already have an expanded folder
            for zip_file in zip_files:
                if zip_file.stem in folder_names:
                    continue

                extracted_song_folder = self._extract_zip_song_folder(zip_file)
                if extracted_song_folder is None:
                    continue

                clean_title = self._extract_song_title_from_folder(extracted_song_folder.name)
                song_stems = self._find_stems_in_song_folder(extracted_song_folder, clean_title, extensions)
                stems.extend(song_stems)

            logger.info(f"Discovered {len(stems)} audio stem files across {len(folders_to_process)} song folders")
            if duplicates:
                logger.warning(f"Skipped {len(duplicates)} .zip files that had matching folders")
            return stems

        except Exception as e:
            logger.error(f"Failed to discover stems: {e}")
            return []

    def _resolve_duplicate(self, duplicate_dict: Dict) -> Optional[Path]:
        """Resolve duplicate by preferring folder over .zip file.
        
        In the future, this could prompt the user via the UI.
        For now, we prefer the folder (expanded) over the .zip file.
        
        Args:
            duplicate_dict: Dict with 'folder' and 'zip' Path objects
            
        Returns:
            The chosen Path (folder in this case)
        """
        folder = duplicate_dict['folder']
        zip_file = duplicate_dict['zip']
        
        logger.warning(f"⚠️  Duplicate found: '{folder.name}' (folder) and '{zip_file.name}' (zip)")
        logger.warning(f"   → Using the folder: {folder}")
        logger.warning(f"   → Ignoring the zip file: {zip_file}")
        
        # Return the folder path
        # In the future, this method could be enhanced to prompt the user
        # via the UI (e.g., a dialog asking which to use)
        return folder

    def _extract_zip_song_folder(self, zip_file: Path) -> Optional[Path]:
        """Extract a zip-only song pack to a temp folder and return its song root."""
        try:
            extract_root = Path(tempfile.mkdtemp(prefix='projectfeb_stems_'))
            self.extracted_archive_dirs.append(extract_root)

            with zipfile.ZipFile(zip_file) as archive:
                for member in archive.infolist():
                    member_path = extract_root / member.filename
                    resolved_path = member_path.resolve()
                    if extract_root.resolve() not in resolved_path.parents and resolved_path != extract_root.resolve():
                        logger.warning(f"Skipping unsafe zip member '{member.filename}' from {zip_file.name}")
                        continue
                    archive.extract(member, extract_root)

            preferred_root = extract_root / zip_file.stem
            if preferred_root.exists() and preferred_root.is_dir():
                logger.info(f"Extracted zip-only song pack '{zip_file.name}' to {preferred_root}")
                return preferred_root

            child_dirs = [child for child in extract_root.iterdir() if child.is_dir() and child.name != '__MACOSX']
            if len(child_dirs) == 1:
                logger.info(f"Extracted zip-only song pack '{zip_file.name}' to {child_dirs[0]}")
                return child_dirs[0]

            logger.info(f"Extracted zip-only song pack '{zip_file.name}' to {extract_root}")
            return extract_root

        except Exception as exc:
            logger.error(f"Failed to extract zip-only song pack '{zip_file}': {exc}")
            return None

    def _parse_stem_file(self, file_path: Path) -> Optional[AudioStem]:
        """Parse a stem file to extract song title and stem type."""
        filename = file_path.stem.lower()

        # Look for stem type keywords at the end first (most common pattern: SongTitle_StemType)
        detected_stem_type = None
        song_title = None
        
        for keyword, stem_type_name in self.stem_keywords.items():
            if filename.endswith('_' + keyword) or filename.endswith('-' + keyword):
                detected_stem_type = stem_type_name
                song_title = filename[:-len(keyword)-1].strip()  # Remove keyword and separator
                break
            elif filename.startswith(keyword + '_') or filename.startswith(keyword + '-'):
                detected_stem_type = stem_type_name
                song_title = filename[len(keyword)+1:].strip()  # Remove keyword and separator
                break

        # If no direct match, try separator-based parsing
        if not detected_stem_type:
            # Common separators in Multitracks naming
            separators = [' - ', '_', '__', ' -', '- ', '–', '—']

            for sep in separators:
                if sep in filename:
                    parts = filename.split(sep, 1)
                    if len(parts) == 2:
                        # Assume first part is song title, second part is stem name
                        potential_song_title = parts[0].strip()
                        potential_stem_name = parts[1].strip()
                        
                        # Detect stem type from the stem name part
                        detected_stem_type = self._detect_stem_type(potential_stem_name)
                        if detected_stem_type:
                            song_title = potential_song_title
                            break

        # If still no stem type found, try to detect from whole filename
        if not detected_stem_type:
            detected_stem_type = self._detect_stem_type(filename)
            if detected_stem_type:
                # Remove the detected keyword to get song title
                for keyword in self.stem_keywords.keys():
                    if keyword in filename:
                        song_title = filename.replace(keyword, '').strip()
                        break

        if not song_title or not detected_stem_type:
            logger.debug(f"Could not parse stem file: {file_path}")
            return None

        # Clean up song title
        song_title = self._clean_song_title(song_title)

        stem = AudioStem(
            path=file_path,
            filename=file_path.name,
            stem_type=detected_stem_type,
            song_title=song_title
        )

        return stem

    def _detect_stem_type(self, text: str) -> Optional[str]:
        """Detect stem type from text using keyword matching.
        
        Prioritizes keywords at the end of the text (after separators) since
        that's where stem types are typically indicated in filenames.
        Handles compound keywords like "Synth Bass" by prioritizing "Bass".
        """
        text_lower = text.lower()
        
        # Special handling: if "bass" appears anywhere, check if it's in a compound keyword
        # Compounds like "synth bass", "electric bass" should map to bass category
        if ' bass' in text_lower or '_bass' in text_lower:
            # Check if this is a compound like "synth_bass" or "synth bass"
            for compound in ['synth_bass', 'synth bass', 'electric_bass', 'electric bass', 'upright_bass', 'upright bass', 'sub_bass', 'sub bass', 'key_bass', 'key bass']:
                if compound in text_lower:
                    return 'bass'
            # Even if not a known compound, "bass" at the end is likely the bass group
            if text_lower.endswith('bass') or ' bass' in text_lower[-10:]:
                return 'bass'
        
        # Strategy 1: Look for keywords after common separators (end of filename)
        # Common separators that indicate stem type comes after them
        separators = [' - ', '_', ' -', '- ', '--', '__']
        
        for separator in separators:
            if separator in text_lower:
                # Get the part after the LAST occurrence of the separator
                parts = text_lower.rsplit(separator, 1)
                if len(parts) == 2:
                    stem_part = parts[1].strip()
                    
                    # Try to match keywords in this part
                    best_match = None
                    best_length = 0
                    
                    for keyword in self.stem_keywords.keys():
                        if keyword in stem_part:
                            if len(keyword) > best_length:
                                best_match = self.stem_keywords[keyword]
                                best_length = len(keyword)
                    
                    if best_match:
                        return best_match
        
        # Strategy 2: Look for the longest matching keyword anywhere in text
        best_match = None
        best_length = 0
        
        for keyword, stem_type in self.stem_keywords.items():
            if keyword in text_lower:
                if len(keyword) > best_length:
                    best_match = stem_type
                    best_length = len(keyword)
        
        # If no match found, return 'unknown' for manual review
        return best_match if best_match else 'unknown'

    def _extract_song_title(self, filename: str) -> str:
        """Extract song title from filename when no clear separator exists."""
        # Remove common prefixes/suffixes
        filename = re.sub(r'^(track|stem|audio)\d*[-_\s]*', '', filename, flags=re.IGNORECASE)
        filename = re.sub(r'[-_\s]*(track|stem|audio)\d*$', '', filename, flags=re.IGNORECASE)

        # Remove file extension if present
        filename = re.sub(r'\.(wav|aif|flac|mp3)$', '', filename, flags=re.IGNORECASE)

        return filename.strip()

    def _clean_song_title(self, title: str) -> str:
        """Clean up song title by removing extra characters and normalizing."""
        # Apply the same cleaning as folder title extraction
        title = self._extract_song_title_from_folder(title)
        
        # Title case
        title = title.title()

        return title

    def _find_stems_for_song(self, song_title: str, all_stems: List[AudioStem]) -> Optional[StemMatch]:
        """Find all stems for a specific song."""
        requested_variants = self._song_title_match_variants(song_title)

        # Filter stems that might match this song
        candidate_stems = []
        for stem in all_stems:
            # Skip metronome/guide files (classic-*.aif, click.wav)
            if (stem.filename.lower().startswith('classic-') and stem.filename.lower().endswith('.aif')) or \
               stem.filename.lower().endswith('- click.wav') or stem.filename.lower() == 'click.wav':
                continue

            stem_variants = self._song_title_match_variants(stem.song_title)
            confidence = max(
                fuzz.ratio(requested_variant, stem_variant)
                for requested_variant in requested_variants
                for stem_variant in stem_variants
            )
            if confidence >= 85:  # Minimum confidence threshold - increased to avoid false matches
                stem.confidence = confidence / 100.0
                candidate_stems.append(stem)

        if not candidate_stems:
            logger.debug(f"No stems found for song: {song_title}")
            return None

        # Return ALL matching stems (not just one per type)
        matched_stems = candidate_stems

        # Calculate overall match confidence
        avg_confidence = sum(stem.confidence for stem in matched_stems) / len(matched_stems)

        # Check for missing common stems
        available_types = set(stem.stem_type for stem in matched_stems)
        missing_types = []
        essential_stems = ['vocals', 'perc', 'bass', 'strings', 'keys']  # Based on Ableton template groups

        for stem_type in essential_stems:
            if stem_type not in available_types:
                missing_types.append(stem_type)

        match = StemMatch(
            song_title=song_title,
            stems=matched_stems,
            match_confidence=avg_confidence,
            missing_stems=missing_types
        )

        logger.info(f"Found {len(matched_stems)} stems for '{song_title}' (confidence: {avg_confidence:.2f})")
        if 'unknown' in available_types:
            unknown_count = len([s for s in matched_stems if s.stem_type == 'unknown'])
            logger.warning(f"⚠️  {unknown_count} stems categorized as 'unknown' - may need manual review")
        return match

    def get_available_stems_summary(self) -> Dict[str, int]:
        """Get a summary of available stems by type."""
        if not self.stems_folder:
            return {}

        all_stems = self._discover_all_stems()
        summary = {}

        for stem in all_stems:
            summary[stem.stem_type] = summary.get(stem.stem_type, 0) + 1

        return summary

    def _extract_song_title_from_folder(self, folder_name: str) -> str:
        """Extract clean song title from folder name.

        Handles patterns like:
        - "Again & Again (Db) [115]"
        - "Give Me Jesus (UPPERROOM)"
        - "Mighty Name of Jesus"
        - "The Blood (75) [G] sw"
        - "Same God (Db) [72.5] sw"  (with decimal tempo)
        """
        title = folder_name

        # Remove parentheses content that looks like key signatures (Db, G, Ab, etc.) - keep these
        # Actually, we want to remove everything in parentheses except key signatures
        # But for now, let's remove all parentheses content
        title = re.sub(r'\s*\([^)]*\)', '', title)

        # Remove tempo information in parentheses (75)
        title = re.sub(r'\s*\(\d+\)', '', title)

        # Remove tempo information in brackets [115] or [72.5] (with decimals)
        title = re.sub(r'\s*\[[\d.]+\]', '', title)

        # Remove key information in brackets [A-G][b#]?[anything]
        title = re.sub(r'\s*\[[A-G][b#]?[\w]*\]', '', title)

        # Remove known trailing modifiers (like "sw" for switch) but keep short real title words like "Joy"
        parts = title.split()
        if parts and parts[-1].lower() in self.FOLDER_TRAILING_MODIFIERS:
            title = ' '.join(parts[:-1])

        # Clean up extra spaces
        title = re.sub(r'\s+', ' ', title).strip()

        # Convert ampersands to "and"
        title = title.replace('&', 'and')

        return title.title()

    def _song_title_match_variants(self, title: str) -> List[str]:
        """Generate normalized title variants for fuzzy song-to-folder matching."""
        variants: List[str] = []

        def add_variant(value: str) -> None:
            normalized = re.sub(r"[^a-z0-9]+", ' ', value.lower())
            normalized = re.sub(r'\s+', ' ', normalized).strip()
            if normalized and normalized not in variants:
                variants.append(normalized)

        cleaned = title.replace('&', 'and')
        add_variant(cleaned)

        no_parenthetical = re.sub(r'\s*\([^)]*\)', '', cleaned).strip()
        add_variant(no_parenthetical)

        no_leading_article = re.sub(r'^(the|a|an)\s+', '', no_parenthetical, flags=re.IGNORECASE).strip()
        add_variant(no_leading_article)

        return variants

    def _find_stems_in_song_folder(self, song_folder: Path, song_title: str, extensions: List[str]) -> List[AudioStem]:
        """Find all stems within a song folder, handling different architectures."""
        stems = []

        # Priority order for finding stems:
        # 1. MultiTracks subfolder (cleanest)
        # 2. Samples/Imported subfolder
        # 3. Samples folder
        # 4. Direct files in song folder

        # Check MultiTracks subfolder
        multitracks_folder = song_folder / "MultiTracks"
        if multitracks_folder.exists():
            stems.extend(self._parse_stems_in_folder(multitracks_folder, song_title, extensions, "multitracks"))
            if stems:  # If we found stems here, prefer this location
                return stems

        # Check Samples/Imported subfolder
        imported_folder = song_folder / "Samples" / "Imported"
        if imported_folder.exists():
            stems.extend(self._parse_stems_in_folder(imported_folder, song_title, extensions, "imported"))
            if stems:  # If we found stems here, prefer this location
                return stems

        # Check Samples folder (without Imported subfolder)
        samples_folder = song_folder / "Samples"
        if samples_folder.exists():
            stems.extend(self._parse_stems_in_folder(samples_folder, song_title, extensions, "samples"))
            if stems:  # If we found stems here, prefer this location
                return stems

        # Finally, check direct files in song folder
        stems.extend(self._parse_stems_in_folder(song_folder, song_title, extensions, "direct"))

        return stems

    def _parse_stems_in_folder(self, folder: Path, song_title: str, extensions: List[str], location_type: str) -> List[AudioStem]:
        """Parse stems in a specific folder with appropriate naming logic."""
        stems = []

        try:
            for file_path in folder.iterdir():
                if not file_path.is_file() or file_path.suffix.lower() not in extensions:
                    continue

                # Skip .asd files (Ableton analysis files)
                if file_path.suffix.lower() == '.asd':
                    continue

                stem = self._parse_stem_file_by_location(file_path, song_title, location_type)
                if stem:
                    stems.append(stem)

        except Exception as e:
            logger.debug(f"Failed to parse stems in {folder}: {e}")

        return stems

    def _parse_stem_file_by_location(self, file_path: Path, song_title: str, location_type: str) -> Optional[AudioStem]:
        """Parse a stem file based on its location and naming convention."""
        filename = file_path.stem.lower()

        # Different parsing logic based on location
        if location_type == "multitracks":
            # MultiTracks: "Drums.wav", "Alto.wav", etc.
            stem_type = self._detect_stem_type(filename)
            if not stem_type:
                return None

        elif location_type == "imported":
            # Samples/Imported: "AG.wav", "Drums.wav", etc.
            stem_type = self._detect_stem_type(filename)
            if not stem_type:
                return None

        elif location_type == "direct":
            # Direct files: "AG - Song Title.wav" or "Song Title - DRUMS.wav"
            stem_type = self._parse_direct_stem_filename(filename, song_title)
            if not stem_type:
                return None

        else:
            # Fallback to original logic
            stem_type = self._detect_stem_type(filename)
            if not stem_type:
                return None

        stem = AudioStem(
            path=file_path,
            filename=file_path.name,
            stem_type=stem_type,
            song_title=song_title
        )

        return stem

    def _parse_direct_stem_filename(self, filename: str, song_title: str) -> Optional[str]:
        """Parse stem type from direct file naming conventions."""
        # Handle patterns like:
        # "AG - Again & Again (Db) [115].wav"
        # "The Blood (75) [G] sw - DRUMS.wav"

        # Remove the full song title from filename to isolate stem type
        song_title_clean = song_title.lower().replace(' ', '').replace('&', 'and')

        # Try removing song title with various separators
        for separator in [' - ', '_', ' -', '- ']:
            if separator in filename:
                parts = filename.split(separator, 1)
                if len(parts) == 2:
                    # Check if first part contains song title
                    first_part = parts[0].strip()
                    second_part = parts[1].strip()

                    # If first part looks like a stem type, use it
                    stem_type = self._detect_stem_type(first_part)
                    if stem_type and stem_type != 'unknown':
                        logger.debug(f"Found stem type '{stem_type}' from first part: '{first_part}'")
                        return stem_type

                    # If second part looks like a stem type, use it
                    stem_type = self._detect_stem_type(second_part)
                    if stem_type and stem_type != 'unknown':
                        logger.debug(f"Found stem type '{stem_type}' from second part: '{second_part}'")
                        return stem_type

        # Fallback: try to detect stem type from entire filename
        stem_type = self._detect_stem_type(filename)
        if stem_type != 'unknown':
            logger.debug(f"Found stem type '{stem_type}' from full filename: '{filename}'")
        return stem_type