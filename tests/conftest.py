"""Settings for the whole test suite.

Tests must NEVER call a real LLM API. Setting THESIS_FORCE_MOCK makes load_config() always use
the mock provider, whatever config.yaml says; child processes started by tests inherit it.

Tests must NEVER write into the real results/ (fix B2). THESIS_RESULTS_DIR moves every "results/..." path
of config.yaml into a temporary folder that is deleted after the session; child processes inherit it too.
A fingerprint of the real results/ is taken before any test runs; it is checked by
tests/test_zz_results_untouched.py and again at the end of the session (the run fails if anything changed).
This runs before any test module is imported.
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

os.environ["THESIS_FORCE_MOCK"] = "1"
TEST_RESULTS_DIR = Path(tempfile.mkdtemp(prefix="thesis_test_results_"))
os.environ["THESIS_RESULTS_DIR"] = str(TEST_RESULTS_DIR)

sys.path.insert(0, str(Path(__file__).parent))
from results_guard import differences, fingerprint  # noqa: E402

RESULTS_BEFORE = fingerprint()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_RESULTS_DIR, ignore_errors=True)
    changed = differences(RESULTS_BEFORE, fingerprint())
    if changed:
        print("\nTHE TEST SUITE CHANGED THE REAL results/ FOLDER:\n  " + "\n  ".join(changed[:20]))
        session.exitstatus = 1


@pytest.fixture
def verifier_yes(monkeypatch):
    """Tests written before the verifier (fix verifier, 30 Oct 2026): every VerifierCallV2 answers "yes" from its own
    MockLLM, so their fixed answer lists stay as they were. The verifier itself is tested in tests/test_verifier_v2.py."""
    from src.agents.applicability_agent_v2 import VerifierCallV2
    from src.llm.mock_llm import MockLLM
    yes = MockLLM([json.dumps({"answer": "yes", "reason": "mock"})])
    original = VerifierCallV2.__init__
    monkeypatch.setattr(VerifierCallV2, "__init__",
                        lambda self, llm, logger, max_retries=None: original(self, yes, logger, max_retries))
