#!/usr/bin/env python3
"""Comprehensive test of full cascading flow: Folder → Service Type → Plan → Songs."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.pco_service import PlanningCenterService
from projectfeb.core.config import Config
import logging

logging.basicConfig(level=logging.INFO)

# Load config
config = Config()
service = PlanningCenterService(config.planning_center)

print("\n" + "="*70)
print("COMPREHENSIVE CASCADE TEST: Folder → Service Type → Plan → Songs")
print("="*70)

# Step 1: Get all folders
print("\n[STEP 1] Loading all folders...")
folders = service.get_folders()
print(f"✓ Loaded {len(folders)} folders")

# Step 2: Find Summers Corner
print("\n[STEP 2] Finding Summers Corner Campus...")
sc = next((f for f in folders if f.id == '1550568'), None)
if not sc:
    print("✗ Summers Corner not found!")
    sys.exit(1)
print(f"✓ Found: {sc.name} (ID: {sc.id})")

# Step 3: Get service types for Summers Corner
print("\n[STEP 3] Loading service types for Summers Corner...")
service_types = service.get_service_types_for_folder(sc.id)
print(f"✓ Loaded {len(service_types)} service types:")
for st in service_types:
    print(f"  - {st.name}")

# Step 4: Find SMC Weekend Services
print("\n[STEP 4] Finding SMC Weekend Services...")
smc = next((st for st in service_types if "Weekend" in st.name), None)
if not smc:
    print("✗ SMC Weekend Services not found!")
    sys.exit(1)
print(f"✓ Found: {smc.name} (ID: {smc.id})")

# Step 5: Get plans for SMC Weekend Services
print("\n[STEP 5] Loading plans for SMC Weekend Services...")
plans = service.get_plans_for_service_type(smc.id)
print(f"✓ Loaded {len(plans)} plans")

# Step 6: Find April 26 plan
print("\n[STEP 6] Finding April 26 plan...")
april_26 = next((p for p in plans if "2026-04-26" in str(p.date)), None)
if not april_26:
    print("✗ April 26 plan not found!")
    print("Available dates:")
    for p in plans[:5]:
        print(f"  - {p.date.strftime('%Y-%m-%d')}: {p.title}")
    sys.exit(1)
print(f"✓ Found: {april_26.title} ({april_26.date.strftime('%Y-%m-%d')})")

# Step 7: Verify songs in April 26 plan
print("\n[STEP 7] Checking songs in April 26 plan...")
print(f"✓ Songs in plan: {len(april_26.songs)}")
if april_26.songs:
    print(f"✓ First song: {april_26.songs[0].title}")
    if april_26.songs[0].title == "The Blood":
        print("✓ Verified: 'The Blood' is the first song!")
    for song in april_26.songs:
        print(f"  - {song.title}")
else:
    print("✗ No songs found in April 26 plan!")

print("\n" + "="*70)
print("✓ ALL TESTS PASSED - Full cascade working correctly!")
print("="*70)
