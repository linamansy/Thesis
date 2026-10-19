"""Load config.yaml so that every other file reads its settings from one place."""

import os
from pathlib import Path

import yaml

# The project root is the folder that contains src/ and config.yaml.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Safety switch: when this environment variable is "1", the LLM provider is always "mock",
# whatever config.yaml says, and the generator is the legacy JSON generator. The test suite sets it
# (tests/conftest.py), so tests can never call a real API, Ollama or BPMNGen.
FORCE_MOCK_VARIABLE = "THESIS_FORCE_MOCK"

# Second safety switch: when this environment variable names a folder, every path in config.yaml that starts with
# "results/" is moved into that folder. The test suite sets it to a temporary folder (tests/conftest.py), so tests
# (and the run_experiment.py processes they start) never write into the real results/.
RESULTS_DIR_VARIABLE = "THESIS_RESULTS_DIR"
RESULTS_PREFIX = "results/"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Read the YAML configuration file and return it as a dictionary."""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if os.environ.get(FORCE_MOCK_VARIABLE) == "1":
        config["llm"]["provider"] = "mock"
        # Tests never start BPMNGen/Ollama: they use the legacy JSON generator with mock answers.
        # (BPMNGenGenerator has its own tests with a fake harness, see tests/test_bpmngen_generator.py.)
        config["generator"]["type"] = "json_builder"
    results_dir = os.environ.get(RESULTS_DIR_VARIABLE)
    if results_dir:
        config["paths"] = {key: str(Path(results_dir) / value[len(RESULTS_PREFIX):])
                           if isinstance(value, str) and value.startswith(RESULTS_PREFIX) else value
                           for key, value in config["paths"].items()}
    return config


def project_path(relative_path: str) -> Path:
    """Turn a path from config.yaml (relative to the project root) into a full path."""
    return PROJECT_ROOT / relative_path
