#!/usr/bin/env python3
"""Test script to verify Summers Corner service types load correctly."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.pco_service import PlanningCenterService as PCOService
from projectfeb.core.config import Config
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load config
config = Config()
pco_service = PCOService(config.planning_center)

# Test 1: Get all folders
print("\n" + "="*60)
print("TEST 1: Getting all folders")
print("="*60)
folders = pco_service.get_folders()
print(f"✓ Retrieved {len(folders)} folders total")

# Find Summers Corner
sc_folders = [f for f in folders if f.id == '1550568']
if sc_folders:
    sc_folder = sc_folders[0]
    print(f"✓ Found Summers Corner: {sc_folder.name} (ID: {sc_folder.id})")
else:
    print("✗ Summers Corner NOT found!")
    sys.exit(1)

# Test 2: Get service types for Summers Corner
print("\n" + "="*60)
print("TEST 2: Getting service types for Summers Corner (1550568)")
print("="*60)
service_types = pco_service.get_service_types_for_folder('1550568')
print(f"✓ Retrieved {len(service_types)} service types")

if service_types:
    for st in service_types:
        print(f"  - {st.name} (ID: {st.id})")
else:
    print("✗ No service types found for Summers Corner!")

# Test 3: Verify expected service types
print("\n" + "="*60)
print("TEST 3: Verify expected service types are present")
print("="*60)

expected_ids = ['1723163', '1679556', '1524990', '1550579']
expected_names = ['SMC Weekend Services', 'SMC Guest Services Team', 'SMC Sisterhood']

for st in service_types:
    if st.id in expected_ids:
        print(f"✓ Found expected service type: {st.name} (ID: {st.id})")
    if any(expected in st.name for expected in expected_names):
        print(f"✓ Found expected service type: {st.name} (ID: {st.id})")

print("\n✓ All tests passed!")
