"""Fingerprint of the real results/ folder, so the test suite can prove it never changes it (fix B2).

The fingerprint is {relative path: SHA-256} of every file under results/. tests/conftest.py takes it once,
before any test runs; tests/test_zz_results_untouched.py and the end of the session compare it again.
"""

import hashlib
from pathlib import Path

from src.config import PROJECT_ROOT

REAL_RESULTS = PROJECT_ROOT / "results"


def fingerprint(folder: Path = REAL_RESULTS) -> dict[str, str]:
    """{path relative to folder: sha256} of every file under folder (empty if the folder does not exist)."""
    if not folder.exists():
        return {}
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def differences(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Human-readable list of added, removed and changed files."""
    return ([f"added: {p}" for p in sorted(set(after) - set(before))]
            + [f"removed: {p}" for p in sorted(set(before) - set(after))]
            + [f"changed: {p}" for p in sorted(set(before) & set(after)) if before[p] != after[p]])
