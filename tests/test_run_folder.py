"""Tests for RunFolder, RunLogger's refusal, and the run_experiment.py entry point (with MockLLM)."""

import json
import subprocess
import sys

import pytest

from src.config import PROJECT_ROOT, load_config
from src.logger import RunLogger
from src.run_folder import RunFolder, default_run_id

CONFIG = load_config()


def config_in(tmp_path, **llm):
    return dict(CONFIG, llm=dict(CONFIG["llm"], **llm), paths=dict(CONFIG["paths"], runs=str(tmp_path / "runs")))


# ---------- RunLogger ----------

def test_run_logger_part_files(tmp_path):
    assert RunLogger(tmp_path, "C1", "rep1").log_path.name == "C1_rep1.jsonl"
    assert RunLogger(tmp_path, "C1", "rep1", part=2).log_path.name == "C1_rep1_part2.jsonl"


def test_run_logger_refuses_an_existing_log_file(tmp_path):
    logger = RunLogger(tmp_path, "C1", "rep1")
    logger.log_call(case_id="01", component="X", model="m", temperature=0, prompt="p", raw_output="r",
                    parsed_output=None, valid_json=False, retries=0, duration_seconds=0.0)
    with pytest.raises(FileExistsError, match="Choose a new run id"):
        RunLogger(tmp_path, "C1", "rep1")
    RunLogger(tmp_path, "C2", "rep1")  # another condition of the same run is fine


# ---------- RunFolder ----------

def test_default_run_id_names_provider_and_repetition(tmp_path):
    assert default_run_id(config_in(tmp_path, provider="anthropic"), 2) == "anthropic_rep2"
    assert default_run_id(config_in(tmp_path, provider="mock"), 1) == "mock_rep1"


def test_repetition_must_be_within_configured_range(tmp_path):
    with pytest.raises(ValueError, match="between 1 and 3"):
        RunFolder(config_in(tmp_path), "x", 4)


def finish_cases(folder, condition, case_ids):
    """Pretend these cases were finished: write their validation.json."""
    for case_id in case_ids:
        case_dir = folder.condition_dir(condition) / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "validation.json").write_text(json.dumps({"generation_succeeded": True, "valid": True}))


def test_parts_are_recorded_in_run_info(tmp_path):
    folder = RunFolder(config_in(tmp_path), "mock_rep2", 2)
    to_run = folder.start_part("C1", 1, tmp_path / "C1.jsonl")
    assert to_run == CONFIG["cases"]["ids"]
    finish_cases(folder, "C1", ["01", "03"])
    folder.end_part("C1", [], interrupted="stopped at case 05: quota")

    assert folder.next_part("C1") == 2
    to_run = folder.start_part("C1", 2, tmp_path / "C1_part2.jsonl")
    assert to_run == CONFIG["cases"]["ids"][2:]          # finished cases 01 and 03 are not run again
    finish_cases(folder, "C1", to_run)
    folder.end_part("C1", [{"generation_succeeded": True, "valid": True}] * 13)

    info = folder.read_info()
    assert (info["run_id"], info["repetition"], info["provider"]) == ("mock_rep2", 2, "mock")
    c1 = info["conditions"]["C1"]
    assert [p["part"] for p in c1["parts"]] == [1, 2]
    assert c1["parts"][0]["interrupted"] == "stopped at case 05: quota" and c1["parts"][1]["interrupted"] is None
    assert c1["complete"] is True and c1["n_cases"] == 13 and c1["n_valid"] == 13


def test_a_complete_condition_is_never_started_again(tmp_path):
    folder = RunFolder(config_in(tmp_path), "mock_rep1", 1)
    folder.start_part("C1", 1, tmp_path / "log")
    finish_cases(folder, "C1", CONFIG["cases"]["ids"])
    with pytest.raises(FileExistsError, match="already complete"):
        folder.check_can_start("C1")
    folder.start_part("C2", 1, tmp_path / "log2")  # other conditions of the same repetition join the same folder
    assert set(folder.read_info()["conditions"]) == {"C1", "C2"}


def test_next_repetition_needs_the_previous_one_complete(tmp_path):
    config = config_in(tmp_path)
    rep1 = RunFolder(config, "mock_rep1", 1)
    for condition in ("C1", "C2", "C3"):
        rep1.start_part(condition, 1, tmp_path / condition)
    finish_cases(rep1, "C1", CONFIG["cases"]["ids"])
    finish_cases(rep1, "C2", CONFIG["cases"]["ids"])
    finish_cases(rep1, "C3", CONFIG["cases"]["ids"][:5])           # C3 of repetition 1 is unfinished

    with pytest.raises(ValueError, match="Repetition 1 is not complete yet .unfinished: C3."):
        RunFolder(config, "mock_rep2", 2).check_previous_repetition_complete(["C1", "C2", "C3"])
    finish_cases(rep1, "C3", CONFIG["cases"]["ids"])
    RunFolder(config, "mock_rep2", 2).check_previous_repetition_complete(["C1", "C2", "C3"])  # now allowed


def test_a_run_folder_cannot_mix_settings(tmp_path):
    RunFolder(config_in(tmp_path), "shared", 1).start_part("C1", 1, tmp_path / "log")
    with pytest.raises(ValueError, match="other settings"):
        RunFolder(config_in(tmp_path), "shared", 2).check_can_start("C2")          # other repetition
    with pytest.raises(ValueError, match="other settings"):
        RunFolder(config_in(tmp_path, provider="gemini"), "shared", 1).check_can_start("C2")  # other provider
    RunFolder(config_in(tmp_path, provider="gemini", model="gemini-a"), "real", 1).start_part("C1", 1, tmp_path / "x")
    with pytest.raises(ValueError, match="other settings"):
        RunFolder(config_in(tmp_path, provider="gemini", model="gemini-b"), "real", 1).check_can_start("C2")


def test_mock_run_records_the_mock_model_name(tmp_path):
    folder = RunFolder(config_in(tmp_path, provider="mock"), "mock_rep1", 1)
    assert folder.settings["model"] == "mock-llm"


def test_find_runs(tmp_path):
    config = config_in(tmp_path)
    RunFolder(config, "mock_rep2", 2).start_part("C1", 1, tmp_path / "a")
    RunFolder(config, "mock_rep1", 1).start_part("C3", 1, tmp_path / "b")
    runs = RunFolder.find_runs(config)
    assert [(r["run_id"], list(r["conditions"])) for r in runs] == [("mock_rep1", ["C3"]), ("mock_rep2", ["C1"])]
    assert runs[0]["path"] == tmp_path / "runs" / "mock_rep1"


# ---------- run_experiment.py from the command line (MockLLM) ----------

def run_cli(*args):
    return subprocess.run([sys.executable, "run_experiment.py", *args], cwd=PROJECT_ROOT,
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_refuses_to_overwrite_and_needs_a_valid_repetition(tmp_path):
    run_id = f"pytest_{tmp_path.name}"  # unique id, cleaned up below
    runs_dir = PROJECT_ROOT / CONFIG["paths"]["runs"] / run_id
    log = PROJECT_ROOT / CONFIG["paths"]["logs"] / f"C1_{run_id}.jsonl"
    try:
        first = run_cli("--condition", "C1", "--repetition", "1", "--run-id", run_id)
        assert first.returncode == 0, first.stderr
        assert (runs_dir / "C1" / "19" / "validation.json").exists()
        assert json.loads((runs_dir / "run_info.json").read_text())["conditions"]["C1"]["n_cases"] == 13

        second = run_cli("--condition", "C1", "--repetition", "1", "--run-id", run_id)
        assert second.returncode != 0 and "Not started" in second.stderr and "already complete" in second.stderr

        wrong = run_cli("--condition", "C1", "--repetition", "7", "--run-id", run_id + "_x")
        assert wrong.returncode != 0 and "between 1 and 3" in wrong.stderr
    finally:
        import shutil
        shutil.rmtree(runs_dir, ignore_errors=True)
        log.unlink(missing_ok=True)
