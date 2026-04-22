"""Configuration management for Project FEB."""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from loguru import logger


def default_output_buses() -> list[dict[str, Any]]:
    """Return the default logical bus layout for generated Ableton returns."""
    return [
        {
            'slot': 1,
            'role': 'content',
            'mode': 'mono',
            'name': 'Perc',
            'tags': ['drums', 'percussion', 'loops', 'perc'],
        },
        {
            'slot': 2,
            'role': 'content',
            'mode': 'mono',
            'name': 'Bass',
            'tags': ['bass'],
        },
        {
            'slot': 3,
            'role': 'content',
            'mode': 'mono',
            'name': 'Lead',
            'tags': ['lead_line'],
        },
        {
            'slot': 4,
            'role': 'content',
            'mode': 'mono',
            'name': 'Strings',
            'tags': ['electric_guitar', 'acoustic_guitar', 'orchestra', 'guitars', 'strings'],
        },
        {
            'slot': 5,
            'role': 'content',
            'mode': 'mono',
            'name': 'Keys',
            'tags': ['piano', 'synth', 'keys'],
        },
        {
            'slot': 6,
            'role': 'content',
            'mode': 'mono',
            'name': 'Vocals',
            'tags': ['lead_vocal', 'bgvs', 'vocals'],
        },
        {
            'slot': 7,
            'role': 'click',
            'mode': 'mono',
            'name': 'Click',
            'tags': [],
        },
        {
            'slot': 8,
            'role': 'guide',
            'mode': 'mono',
            'name': 'Guide',
            'tags': [],
        },
    ]

@dataclass
class PlanningCenterConfig:
    """Planning Center Online configuration."""
    application_id: str = ""
    secret: str = ""
    base_url: str = "https://api.planningcenteronline.com"

@dataclass
class MultitracksConfig:
    """Multitracks configuration."""
    stems_folder: str = ""
    supported_formats: list = None

    def __post_init__(self):
        if self.supported_formats is None:
            self.supported_formats = ['wav', 'aif', 'aiff', 'flac']

@dataclass
class AbletonConfig:
    """Ableton Live configuration."""
    template_path: str = ""
    output_folder: str = ""
    version: str = "11.0_11300"  # Ableton 11.3.x
    output_buses: list[dict[str, Any]] = None
    enable_sub_master: bool = True
    sub_master_bus_name: str = "Sub Master"

    def __post_init__(self):
        if self.output_buses is None:
            self.output_buses = default_output_buses()

@dataclass
class Config:
    """Main configuration class."""
    planning_center: PlanningCenterConfig
    multitracks: MultitracksConfig
    ableton: AbletonConfig

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize configuration from file or defaults."""
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "settings.json"

        self.planning_center = PlanningCenterConfig()
        self.multitracks = MultitracksConfig()
        self.ableton = AbletonConfig()

        if config_path.exists():
            self._load_from_file(config_path)
        else:
            logger.warning(f"Config file not found at {config_path}, using defaults")
            self._load_from_env()

    def _load_from_file(self, config_path: Path) -> None:
        """Load configuration from JSON file."""
        try:
            with open(config_path, 'r') as f:
                data = json.load(f)

            # Update planning center config
            pc_data = data.get('planning_center', {})
            for key, value in pc_data.items():
                if hasattr(self.planning_center, key):
                    setattr(self.planning_center, key, value)

            # Update multitracks config
            mt_data = data.get('multitracks', {})
            for key, value in mt_data.items():
                if hasattr(self.multitracks, key):
                    setattr(self.multitracks, key, value)

            # Update ableton config
            al_data = data.get('ableton', {})
            for key, value in al_data.items():
                if hasattr(self.ableton, key):
                    setattr(self.ableton, key, value)

            logger.info(f"Configuration loaded from {config_path}")

        except Exception as e:
            logger.error(f"Failed to load config from {config_path}: {e}")
            self._load_from_env()

    def _load_from_env(self) -> None:
        """Load configuration from environment variables."""
        # Planning Center
        self.planning_center.application_id = os.getenv('PCO_APP_ID', '')
        self.planning_center.secret = os.getenv('PCO_SECRET', '')

        # Multitracks
        self.multitracks.stems_folder = os.getenv('MULTITRACKS_FOLDER', '')

        # Ableton
        self.ableton.template_path = os.getenv('ABLETON_TEMPLATE', '')
        self.ableton.output_folder = os.getenv('ABLETON_OUTPUT', '')

    def save(self, config_path: Optional[Path] = None) -> None:
        """Save current configuration to file."""
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "settings.json"

        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'planning_center': asdict(self.planning_center),
            'multitracks': asdict(self.multitracks),
            'ableton': asdict(self.ableton)
        }

        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Configuration saved to {config_path}")

    def is_valid(self) -> bool:
        """Check if configuration has required values."""
        required_checks = [
            bool(self.planning_center.application_id),
            bool(self.planning_center.secret),
            bool(self.multitracks.stems_folder),
            bool(self.ableton.template_path),
            Path(self.ableton.template_path).exists() if self.ableton.template_path else False,
            Path(self.multitracks.stems_folder).exists() if self.multitracks.stems_folder else False,
        ]
        return all(required_checks)