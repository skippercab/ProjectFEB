"""Basic tests for Project FEB."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from projectfeb.core.config import Config
from projectfeb.services.multitracks_service import MultitracksService, AudioStem

def test_config_loading():
    """Test configuration loading."""
    config = Config()
    assert hasattr(config, 'planning_center')
    assert hasattr(config, 'multitracks')
    assert hasattr(config, 'ableton')

def test_stem_parsing():
    """Test audio stem file parsing."""
    # Create a mock config
    mock_config = Mock()
    mock_config.stems_folder = "/fake/path"
    mock_config.supported_formats = ['wav']
    
    service = MultitracksService(mock_config)

    # Mock file path
    mock_path = Mock()
    mock_path.stem = "Amazing_Grace_Vocals"
    mock_path.name = "Amazing_Grace_Vocals.wav"
    mock_path.suffix = ".wav"

    stem = service._parse_stem_file(mock_path)

    assert stem is not None
    assert stem.song_title == "Amazing Grace"
    assert stem.stem_type == "vocals"
    assert stem.filename == "Amazing_Grace_Vocals.wav"

def test_fuzzy_matching():
    """Test fuzzy song title matching."""
    # Create a mock config
    mock_config = Mock()
    mock_config.stems_folder = "/fake/path"
    mock_config.supported_formats = ['wav']
    
    service = MultitracksService(mock_config)

    # Create test stems
    stems = [
        AudioStem(
            path=Path("/test/Amazing_Grace_Vocals.wav"),
            filename="Amazing_Grace_Vocals.wav",
            stem_type="vocals",
            song_title="Amazing Grace"
        ),
        AudioStem(
            path=Path("/test/Amazing_Grace_Drums.wav"),
            filename="Amazing_Grace_Drums.wav",
            stem_type="drums",
            song_title="Amazing Grace"
        )
    ]

    # Test matching
    match = service._find_stems_for_song("Amazing Grace", stems)

    assert match is not None
    assert len(match.stems) == 2
    assert match.match_confidence > 0.8

def test_folder_title_extraction():
    """Test song title extraction from folder names."""
    # Create a mock config
    mock_config = Mock()
    mock_config.stems_folder = "/fake/path"
    mock_config.supported_formats = ['wav']
    
    service = MultitracksService(mock_config)

    test_cases = [
        ("Again & Again (Db) [115]", "Again And Again"),
        ("Give Me Jesus (UPPERROOM)", "Give Me Jesus"),
        ("Mighty Name of Jesus", "Mighty Name Of Jesus"),
        ("The Blood (75) [G] sw", "The Blood"),
        ("Amazing Grace (Traditional)", "Amazing Grace"),
    ]

    for folder_name, expected in test_cases:
        result = service._extract_song_title_from_folder(folder_name)
        assert result == expected, f"Failed for '{folder_name}': got '{result}', expected '{expected}'"

def test_direct_stem_parsing():
    """Test parsing of direct stem files with complex naming."""
    # Create a mock config
    mock_config = Mock()
    mock_config.stems_folder = "/fake/path"
    mock_config.supported_formats = ['wav']
    
    service = MultitracksService(mock_config)

    # Test cases for direct file parsing
    test_cases = [
        ("AG - Again & Again (Db) [115]", "Again And Again", "strings"),  # AG = Acoustic Guitar
        ("Drums - The Blood (75) [G] sw", "The Blood", "perc"),  # Drums go to Perc group
        ("Bass - Mighty Name of Jesus", "Mighty Name Of Jesus", "bass"),
    ]

    for filename, song_title, expected_stem_type in test_cases:
        result = service._parse_direct_stem_filename(filename.lower(), song_title)
        assert result == expected_stem_type, f"Failed for '{filename}': got '{result}', expected '{expected_stem_type}'"

if __name__ == "__main__":
    pytest.main([__file__])