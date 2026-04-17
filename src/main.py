#!/usr/bin/env python3
"""Main entry point for Project FEB application."""

import sys
import os
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from projectfeb.ui.main_window import ProjectFEBApp
from projectfeb.core.config import Config
from projectfeb.utils.logging import setup_logging

def main():
    """Main application entry point."""
    # Set up logging
    setup_logging()

    # Load configuration
    config = Config()

    # Create and run the application
    app = ProjectFEBApp(config)
    app.run()

if __name__ == "__main__":
    main()