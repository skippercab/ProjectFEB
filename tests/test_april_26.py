#!/usr/bin/env python3
"""Test April 26 plan songs."""
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

# Get plans for SMC Weekend Services
plans = pco_service.get_plans_for_service_type('1524990')
print(f"Total plans: {len(plans)}\n")

# Find April 26 plan
april_26 = None
for plan in plans:
    date_str = plan.date.strftime("%Y-%m-%d")
    print(f"Plan: {date_str} - {plan.title}")
    if date_str == "2026-04-26":
        april_26 = plan
        print(f"  → Songs: {len(plan.songs)}")
        for song in plan.songs:
            print(f"     • {song.title}")

print("\n" + "="*60)
if april_26:
    print(f"April 26 Plan - Total songs: {len(april_26.songs)}")
    if april_26.songs:
        first_song = april_26.songs[0]
        print(f"First song: {first_song.title}")
        if first_song.title == "The Blood":
            print("✓ Found 'The Blood' as expected!")
        else:
            print(f"✗ Expected 'The Blood', got '{first_song.title}'")
else:
    print("✗ April 26 plan not found!")
