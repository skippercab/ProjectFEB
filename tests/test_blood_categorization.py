#!/usr/bin/env python3
"""Show detailed stem categorization for The Blood."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

config = Config()
service = MultitracksService(config.multitracks)

print("\n" + "="*70)
print("THE BLOOD - STEM CATEGORIZATION BREAKDOWN")
print("="*70)

# Find stems for "The Blood"
match = service._find_stems_for_song("The Blood", service._discover_all_stems())

if match:
    print(f"\nSong: {match.song_title}")
    print(f"Total stems: {len(match.stems)}")
    print(f"Match confidence: {match.match_confidence:.2f}")
    print(f"Missing stems: {match.missing_stems}")
    
    # Group by type
    by_type = {}
    for stem in match.stems:
        if stem.stem_type not in by_type:
            by_type[stem.stem_type] = []
        by_type[stem.stem_type].append(stem.filename)
    
    print(f"\nStem categorization:")
    for stem_type in sorted(by_type.keys()):
        files = by_type[stem_type]
        prefix = "✓" if stem_type != "unknown" else "✗"
        print(f"\n  {prefix} {stem_type.upper()} ({len(files)} stems):")
        for filename in sorted(files):
            # Extract just the stem name
            name = filename.split(' - ')[-1].replace('.wav', '')
            print(f"      • {name}")
else:
    print("✗ No match found for The Blood!")
