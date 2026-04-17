#!/usr/bin/env python3
"""Test stem type detection for Synth Bass and other edge cases."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

# Load config
config = Config()
multitracks_service = MultitracksService(config.multitracks)

# Test cases
test_cases = [
    ("Give Me Jesus - Synth Bass.wav", "bass"),
    ("Song - Synth.wav", "keys"),
    ("Song - Electric Bass.wav", "bass"),
    ("Song - Sub Bass.wav", "bass"),
    ("Song - Piano.wav", "keys"),
    ("Song - Keys.wav", "keys"),
    ("Song - Bass.wav", "bass"),
    ("Song - Synth_Bass.wav", "bass"),
    ("The Blood (75) [G] sw - STRINGS.wav", "strings"),
    ("The Blood (75) [G] sw - GUIDE.wav", "guide"),
    ("The Blood (75) [G] sw - DRUMS.wav", "perc"),
    ("The Blood (75) [G] sw - KEYBASS.wav", "bass"),
]

print("Testing stem type detection for various filenames:\n")
print("="*70)
for filename, expected in test_cases:
    # Remove .wav extension for detection
    stem_name = filename.replace('.wav', '')
    detected = multitracks_service._detect_stem_type(stem_name)
    status = "✓" if detected == expected else "✗"
    print(f"{status} {filename:45} → {detected:10} (expected: {expected})")
print("="*70)
