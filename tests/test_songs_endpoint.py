#!/usr/bin/env python3
"""Test songs endpoint."""
import sys
sys.path.insert(0, 'src')

from projectfeb.services.pco_service import PlanningCenterService
from projectfeb.core.config import Config
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load config
config = Config()
pco_service = PlanningCenterService(config.planning_center)

# Get a plan from SMC Weekend Services
print("Getting plans for SMC Weekend Services (1524990)...")
plans = pco_service.get_plans_for_service_type('1524990')
print(f"Found {len(plans)} plans")

if plans:
    first_plan = plans[0]
    print(f"\nFirst plan: {first_plan.title} ({first_plan.date})")
    print(f"Plan ID: {first_plan.id}")
    print(f"Songs in plan: {len(first_plan.songs)}")
    
    if first_plan.songs:
        print("\nSongs found:")
        for song in first_plan.songs:
            print(f"  - {song.title}")
    else:
        print("\n✗ No songs found in plan!")
        print("\nTesting endpoint formats...")
        
        # Test both endpoint formats
        import requests
        from requests.auth import HTTPBasicAuth
        
        token = config.planning_center.secret
        app_id = config.planning_center.application_id
        base_url = config.planning_center.base_url
        
        # Format 1: /services/v2/service_types/plans/{id}/items (current)
        url1 = f"{base_url}/services/v2/service_types/plans/{first_plan.id}/items"
        print(f"\nTesting: {url1}")
        try:
            response = requests.get(url1, auth=HTTPBasicAuth(app_id, token), timeout=5)
            print(f"Status: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")
        
        # Format 2: /services/v2/plans/{id}/items (correct)
        url2 = f"{base_url}/services/v2/plans/{first_plan.id}/items"
        print(f"\nTesting: {url2}")
        try:
            response = requests.get(url2, auth=HTTPBasicAuth(app_id, token), timeout=5)
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                items = data.get('data', [])
                print(f"Items found: {len(items)}")
                if items:
                    print("✓ This is the correct endpoint!")
        except Exception as e:
            print(f"Error: {e}")
