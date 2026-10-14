"""Load config.yaml so that every other file reads its settings from one place."""

import os
from pathlib import Path

import yaml

# The project root is the folder that contains src/ and config.yaml.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Safety switch: when this environment variable is "1", the LLM provider is always "mock",
# whatever config.yaml says. The test suite sets it (tests/conftest.py), so tests can never
# call a real API or use up the free-tier quota.
FORCE_MOCK_VARIABLE = "THESIS_FORCE_MOCK"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Read the YAML configuration file and return it as a dictionary."""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if os.environ.get(FORCE_MOCK_VARIABLE) == "1":
        config["llm"]["provider"] = "mock"
    return config


def project_path(relative_path: str) -> Path:
    """Turn a path from config.yaml (relative to the project root) into a full path."""
    return PROJECT_ROOT / relative_path
