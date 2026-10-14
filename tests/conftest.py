"""Settings for the whole test suite.

Tests must NEVER call a real LLM API. Setting THESIS_FORCE_MOCK makes load_config() always use
the mock provider, whatever config.yaml says; child processes started by tests inherit it.
This runs before any test module is imported.
"""

import os

os.environ["THESIS_FORCE_MOCK"] = "1"
