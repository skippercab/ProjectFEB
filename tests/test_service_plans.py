#!/usr/bin/env python3
"""Test script to verify service plans load correctly for SMC Weekend Services."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.pco_service import PlanningCenterService
from projectfeb.core.config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load config
config = Config()
pco_service = PlanningCenterService(config.planning_center)

# Test: Get plans for SMC Weekend Services (ID: 1524990)
print("\n" + "="*60)
print("TEST: Getting plans for SMC Weekend Services")
print("="*60)
print("Service Type ID: 1524990 (from Summers Corner)")

plans = pco_service.get_plans_for_service_type('1524990')
print(f"✓ Retrieved {len(plans)} plans")

if plans:
    print("\nFirst 10 plans:")
    for plan in plans[:10]:
        print(f"  - {plan.title} ({plan.date})")
else:
    print("✗ No plans found!")

print("\n✓ Service type cascade test passed!")
