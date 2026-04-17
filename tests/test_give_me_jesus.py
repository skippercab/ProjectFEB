#!/usr/bin/env python3
"""Test stem categorization for Give Me Jesus."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

# Load config
config = Config()
multitracks_service = MultitracksService(config.multitracks)

# Get stems for Give Me Jesus
stems = multitracks_service.find_stems_for_songs([
    {'name': 'Give Me Jesus', 'folder_id': '1550568'}
])

print("=" * 80)
print("STEM CATEGORIZATION FOR 'GIVE ME JESUS'")
print("=" * 80)

if stems:
    for song_name, song_stems in stems.items():
        print(f"\nSong: {song_name}")
        print("-" * 80)
        
        # Group stems by category
        categories = {}
        for stem in song_stems:
            category = stem.get('category', 'UNKNOWN')
            if category not in categories:
                categories[category] = []
            categories[category].append(stem)
        
        # Display by category
        for category in sorted(categories.keys()):
            print(f"\n{category}:")
            for stem in sorted(categories[category], key=lambda s: s['filename']):
                filename = stem['filename']
                print(f"  ✓ {filename}")
        
        print(f"\nTotal stems: {len(song_stems)}")
else:
    print("No stems found for Give Me Jesus")

print("=" * 80)
