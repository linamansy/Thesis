"""The real results/ folder is byte-identical before and after the tests (fix B2).

The file name starts with "zz" so pytest runs it after the other test files; the session end repeats the check
(tests/conftest.py), so tests that run after this one are covered too.
"""

from conftest import RESULTS_BEFORE, TEST_RESULTS_DIR
from results_guard import REAL_RESULTS, differences, fingerprint
from src.config import load_config


def test_config_paths_point_into_the_temporary_folder():
    paths = load_config()["paths"]
    for key in ("runs", "logs", "evaluation", "statistics_dir", "evaluation_summary"):
        assert str(TEST_RESULTS_DIR) in paths[key], key
        assert not paths[key].startswith("results/")


def test_real_results_folder_is_byte_identical():
    assert differences(RESULTS_BEFORE, fingerprint()) == []


def test_fingerprint_notices_added_changed_and_removed_files(tmp_path):
    (tmp_path / "a.csv").write_text("1", encoding="utf-8")
    (tmp_path / "b.csv").write_text("2", encoding="utf-8")
    before = fingerprint(tmp_path)
    (tmp_path / "a.csv").write_text("changed", encoding="utf-8")
    (tmp_path / "b.csv").unlink()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.csv").write_text("3", encoding="utf-8")
    assert differences(before, fingerprint(tmp_path)) == ["added: sub/c.csv", "removed: b.csv", "changed: a.csv"]
    assert REAL_RESULTS.name == "results"
