#!/usr/bin/env python3
"""Test what's actually happening with the stems folder."""
import sys
sys.path.insert(0, 'src')

from projectfeb.core.config import Config
from pathlib import Path

config = Config()
stems_folder = Path(config.multitracks.stems_folder)

print(f"\nStems folder: {stems_folder}")
print(f"Exists: {stems_folder.exists()}")

if stems_folder.exists():
    print(f"\nContents:")
    for item in stems_folder.iterdir():
        print(f"  - {item.name} ({'dir' if item.is_dir() else 'file'})")
    
    # Check The Blood folder structure
    blood_folder = stems_folder / "The Blood"
    if blood_folder.exists():
        print(f"\nThe Blood folder structure:")
        for item in blood_folder.iterdir():
            if item.is_dir():
                print(f"  📁 {item.name}/")
                for subitem in item.iterdir():
                    print(f"     - {subitem.name}")
            else:
                print(f"  📄 {item.name}")
