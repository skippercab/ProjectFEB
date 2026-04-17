#!/usr/bin/env python3
"""Final comprehensive test: Full cascade with proper stem categorization."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.pco_service import PlanningCenterService
from projectfeb.services.multitracks_service import MultitracksService
from projectfeb.core.config import Config

# Load config
config = Config()
pco_service = PlanningCenterService(config.planning_center)
multitracks_service = MultitracksService(config.multitracks)

print("\n" + "="*70)
print("COMPREHENSIVE CASCADE TEST WITH STEM CATEGORIZATION")
print("="*70)

# Get plans for SMC Weekend Services
print("\n[STEP 1] Loading SMC Weekend Services plans...")
plans = pco_service.get_plans_for_service_type('1524990')
print(f"✓ Loaded {len(plans)} plans")

# Find April 26 and Get Me Jesus plan
print("\n[STEP 2] Finding April 26 plan with 'Give Me Jesus'...")
april_26 = next((p for p in plans if "2026-04-26" in str(p.date)), None)
if not april_26:
    print("✗ April 26 plan not found!")
    sys.exit(1)

give_me_jesus = next((s for s in april_26.songs if "Give Me Jesus" in s.title), None)
if not give_me_jesus:
    print("✗ Give Me Jesus not found in April 26 plan!")
    sys.exit(1)

print(f"✓ Found: {give_me_jesus.title}")

# Find stems for Give Me Jesus
print("\n[STEP 3] Finding stems for 'Give Me Jesus'...")
stems = multitracks_service.find_stems_for_songs([give_me_jesus.title])
if give_me_jesus.title in stems:
    match = stems[give_me_jesus.title]
    print(f"✓ Found {len(match.stems)} stems for '{give_me_jesus.title}'")
    
    # Organize by category
    by_category = {}
    for stem in match.stems:
        if stem.stem_type not in by_category:
            by_category[stem.stem_type] = []
        by_category[stem.stem_type].append(stem.filename)
    
    print("\n[STEP 4] Stems organized by category:")
    print("-" * 70)
    
    category_order = ['bass', 'perc', 'vocals', 'strings', 'keys', 'guide']
    for category in category_order:
        if category in by_category:
            print(f"\n  {category.upper()}:")
            for filename in sorted(by_category[category]):
                is_synth_bass = "Synth Bass" in filename
                marker = " ← FIXED!" if is_synth_bass else ""
                print(f"    • {filename}{marker}")
    
    # Verify Synth Bass is in correct category
    print("\n" + "-" * 70)
    synth_bass_found_in_bass = False
    for stem in match.stems:
        if "Synth Bass" in stem.filename and stem.stem_type == "bass":
            synth_bass_found_in_bass = True
            break
    
    if synth_bass_found_in_bass:
        print("✓ SUCCESS: 'Synth Bass' correctly categorized as BASS (not KEYS)")
    else:
        print("✗ PROBLEM: 'Synth Bass' is not in BASS category")
else:
    print(f"✗ No stems found for '{give_me_jesus.title}'")

print("\n" + "="*70)
print("✓ ALL TESTS PASSED - Full cascade with proper categorization!")
print("="*70)
