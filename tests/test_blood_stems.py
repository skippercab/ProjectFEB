#!/usr/bin/env python3
"""Test The Blood stems with the actual discovery mechanism."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

config = Config()
service = MultitracksService(config.multitracks)

print("\n" + "="*70)
print("DISCOVERING STEMS FOR THE BLOOD")
print("="*70)

# Get all discovered stems
all_stems = service._discover_all_stems()

# Filter for The Blood
blood_stems = [s for s in all_stems if 'blood' in s.song_title.lower()]

print(f"\nTotal stems discovered: {len(all_stems)}")
print(f"The Blood stems found: {len(blood_stems)}")

if blood_stems:
    print("\nThe Blood stems breakdown:")
    
    # Group by stem type
    by_type = {}
    for stem in blood_stems:
        if stem.stem_type not in by_type:
            by_type[stem.stem_type] = []
        by_type[stem.stem_type].append(stem.filename)
    
    for stem_type in sorted(by_type.keys()):
        files = by_type[stem_type]
        print(f"\n  {stem_type.upper()} ({len(files)} files):")
        for filename in sorted(files):
            print(f"    - {filename}")
    
    # Check for unknowns
    unknowns = [s for s in blood_stems if s.stem_type == 'unknown']
    if unknowns:
        print(f"\n  ⚠️  UNKNOWN ({len(unknowns)} files):")
        for stem in unknowns:
            print(f"    - {stem.filename}")
else:
    print("✗ No Blood stems found!")
