#!/usr/bin/env python3
"""Setup script for Project FEB."""

import sys
import json
from pathlib import Path
from typing import Dict, Any

def main():
    """Run the setup process."""
    print("🎵 Project FEB Setup")
    print("=" * 50)

    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)

    print(f"✅ Python {sys.version.split()[0]} detected")

    # Create config directory if it doesn't exist
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    config_file = config_dir / "settings.json"

    if config_file.exists():
        print(f"📁 Configuration file already exists: {config_file}")
        if input("Do you want to reconfigure? (y/N): ").lower() != 'y':
            print("Setup cancelled.")
            return

    # Load existing config or create default
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
    else:
        config = get_default_config()

    # Interactive setup
    config = interactive_setup(config)

    # Save configuration
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"✅ Configuration saved to {config_file}")

    # Check if dependencies are installed
    print("\n📦 Checking dependencies...")
    try:
        import customtkinter
        import requests
        import fuzzywuzzy
        print("✅ Core dependencies are installed")
    except ImportError as e:
        print(f"⚠️  Missing dependencies. Run: pip install -r requirements.txt")
        print(f"Error: {e}")

    print("\n🎉 Setup complete!")
    print("Run 'python -m projectfeb' to start the application.")

def get_default_config() -> Dict[str, Any]:
    """Get default configuration."""
    return {
        "planning_center": {
            "application_id": "",
            "secret": "",
            "base_url": "https://api.planningcenteronline.com"
        },
        "multitracks": {
            "stems_folder": "",
            "supported_formats": ["wav", "aif", "aiff", "flac"]
        },
        "ableton": {
            "template_path": "/Users/skippercab/Music/Ableton/User Library/Templates/Default Set SMC.als",
            "output_folder": "~/Desktop",
            "version": "11.0_11300"
        }
    }

def interactive_setup(config: Dict[str, Any]) -> Dict[str, Any]:
    """Interactive configuration setup."""
    print("\n🔧 Configuration Setup")
    print("-" * 30)

    # Planning Center Online setup
    print("\n📅 Planning Center Online Setup")
    print("Get your Application ID and Secret from: https://api.planningcenteronline.com/oauth/applications")

    pco = config["planning_center"]
    pco["application_id"] = input(f"Application ID [{pco['application_id']}]: ").strip() or pco["application_id"]
    pco["secret"] = input(f"Secret [{pco['secret']}]: ").strip() or pco["secret"]

    # Multitracks setup
    print("\n🎵 Multitracks Setup")
    mt = config["multitracks"]
    mt["stems_folder"] = input(f"Stems folder path [{mt['stems_folder']}]: ").strip() or mt["stems_folder"]

    # Ableton setup
    print("\n🎹 Ableton Live Setup")
    al = config["ableton"]
    al["template_path"] = input(f"Template file path [{al['template_path']}]: ").strip() or al["template_path"]
    al["output_folder"] = input(f"Output folder [{al['output_folder']}]: ").strip() or al["output_folder"]

    # Validate paths
    template_path = Path(al["template_path"]).expanduser()
    if not template_path.exists():
        print(f"⚠️  Template file not found: {template_path}")
        if input("Continue anyway? (y/N): ").lower() != 'y':
            print("Setup cancelled.")
            sys.exit(1)

    stems_path = Path(mt["stems_folder"]).expanduser()
    if not stems_path.exists():
        print(f"⚠️  Stems folder not found: {stems_path}")
        print("You can set this later in the application.")

    return config

if __name__ == "__main__":
    main()