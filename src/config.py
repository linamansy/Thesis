"""Load config.yaml so that every other file reads its settings from one place."""

from pathlib import Path

import yaml

# The project root is the folder that contains src/ and config.yaml.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Read the YAML configuration file and return it as a dictionary."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_path(relative_path: str) -> Path:
    """Turn a path from config.yaml (relative to the project root) into a full path."""
    return PROJECT_ROOT / relative_path
