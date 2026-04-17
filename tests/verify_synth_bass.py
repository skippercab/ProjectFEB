#!/usr/bin/env python3
"""Verify Give Me Jesus stems are categorized correctly."""
import sys
sys.path.insert(0, 'src')

from pathlib import Path
from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

# Load config
config = Config()
service = MultitracksService(config.multitracks)

# Test the Give Me Jesus folder
give_me_jesus_folder = Path("/Users/skippercab/Music/Tracks/Stems/Give Me Jesus (UPPERROOM)")

if give_me_jesus_folder.exists():
    print("\nAnalyzing stems in Give Me Jesus folder:")
    print("="*70)
    
    stems_by_category = {
        'bass': [],
        'keys': [],
        'perc': [],
        'vocals': [],
        'strings': [],
        'guide': [],
        'unknown': []
    }
    
    for wav_file in sorted(give_me_jesus_folder.glob("*.wav")):
        stem_type = service._detect_stem_type(wav_file.stem)
        if not stem_type:
            stem_type = 'unknown'
        
        if stem_type not in stems_by_category:
            stems_by_category[stem_type] = []
        
        stems_by_category[stem_type].append(wav_file.name)
    
    # Display results by category
    for category in ['bass', 'keys', 'perc', 'vocals', 'strings', 'guide', 'unknown']:
        stems = stems_by_category.get(category, [])
        if stems:
            print(f"\n{category.upper()}:")
            for stem in stems:
                is_synth_bass = "Synth Bass" in stem
                marker = " ← SYNTH BASS" if is_synth_bass else ""
                print(f"  • {stem}{marker}")
    
    print("\n" + "="*70)
    
    # Check if Synth Bass is in correct category
    synth_bass_found = False
    for stem in stems_by_category.get('bass', []):
        if "Synth Bass" in stem:
            synth_bass_found = True
            break
    
    if synth_bass_found:
        print("✓ SUCCESS: 'Synth Bass' is correctly categorized under BASS")
    else:
        print("✗ PROBLEM: 'Synth Bass' is NOT in the BASS category")
        # Check where it ended up
        for category, stems in stems_by_category.items():
            for stem in stems:
                if "Synth Bass" in stem:
                    print(f"  Found in: {category.upper()} instead!")
else:
    print(f"Folder not found: {give_me_jesus_folder}")
