"""Tests for the stage gates (src/stage_gates.py, fix E2). Synthetic silver files live in a throwaway git repository
in a temporary folder (skipped without git); runs and evaluation tables are synthetic too."""

import hashlib
import json
import shutil
import subprocess
import sys

import pandas as pd
import pytest

from src.config import load_config
from src.run_folder import RunFolder
from src.stage_gates import evaluation_gate, statistics_gate

CONFIG = load_config()
CASES = ["01", "03"]
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def setup(tmp_path, silver_cases=None, commit=True, runs_complete=True, frozen_matches=True):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    frozen = {"cases": {c: {"passages": [{"rank": 1, "passage_id": "P1", "text": "x"},
                                         {"rank": 2, "passage_id": "P2", "text": "y"}]} for c in CASES}}
    frozen_path = tmp_path / "frozen.json"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    sha = hashlib.sha256(frozen_path.read_bytes()).hexdigest() if frozen_matches else "0" * 64
    silver_cases = silver_cases if silver_cases is not None else {
        c: {"passages": [{"passage_id": "P1", "label": "indeterminate"}, {"passage_id": "P2", "label": "irrelevant"}],
            "required_steps": []} for c in CASES}
    silver_path = repo / "silver.json"
    silver_path.write_text(json.dumps({"frozen_retrieval_sha256": sha, "cases": silver_cases}), encoding="utf-8")
    if commit:
        git(repo, "add", "silver.json")
        git(repo, "commit", "-q", "-m", "silver")
    config = dict(CONFIG, cases={"ids": CASES}, conditions=["C1", "C2"],
                  statistics=dict(CONFIG["statistics"], runs=["rep1"]),
                  paths=dict(CONFIG["paths"], silver_reference=str(silver_path), frozen_retrieval=str(frozen_path),
                             runs=str(tmp_path / "runs"), evaluation=str(tmp_path / "evaluation.csv")))
    folder = RunFolder(config, "rep1", 1)
    for condition in config["conditions"]:
        folder.start_part(condition, 1, tmp_path / "log")
        for case_id in CASES if runs_complete else CASES[:1]:
            case_dir = folder.condition_dir(condition) / case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / config["paths"]["validation_file"]).write_text("{}", encoding="utf-8")
    return config, silver_path


def test_evaluation_gate_open_when_everything_is_ready(tmp_path):
    config, _ = setup(tmp_path)
    assert evaluation_gate(config) == []


@pytest.mark.parametrize("silver_cases,expected", [
    ({"01": {"passages": [{"passage_id": "P1", "label": "indeterminate"}, {"passage_id": "P2", "label": "irrelevant"}],
             "required_steps": []}}, "case 03 has no labels"),
    ({c: {"passages": [{"passage_id": "P1", "label": "indeterminate"}], "required_steps": []} for c in CASES},
     "no label for passage(s) ['P2']"),
    ({c: {"passages": [{"passage_id": "P1", "label": "annotation_failed"}, {"passage_id": "P2", "label": "irrelevant"}],
          "required_steps": []} for c in CASES}, "unusable label(s) ['annotation_failed']"),
    ({c: {"passages": [{"passage_id": "P1", "label": "applicable"}, {"passage_id": "P2", "label": "irrelevant"}]}
      for c in CASES}, "no expected requirements"),
])
def test_incomplete_silver_closes_the_gate(tmp_path, silver_cases, expected):
    config, _ = setup(tmp_path, silver_cases=silver_cases)
    assert any(expected in p for p in evaluation_gate(config))


def test_uncommitted_or_untracked_silver_closes_the_gate(tmp_path):
    config, silver_path = setup(tmp_path)
    silver_path.write_text(silver_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert any("uncommitted changes" in p for p in evaluation_gate(config))
    config, _ = setup(tmp_path / "b", commit=False)
    assert any("not committed" in p for p in evaluation_gate(config))


def test_silver_built_on_another_frozen_retrieval_closes_the_gate(tmp_path):
    config, _ = setup(tmp_path, frozen_matches=False)
    assert any("frozen retrieval" in p for p in evaluation_gate(config))


def test_incomplete_or_missing_run_closes_the_gate(tmp_path):
    config, _ = setup(tmp_path, runs_complete=False)
    assert any("rep1: condition(s) ['C1', 'C2'] not complete" in p for p in evaluation_gate(config))
    config["statistics"] = dict(config["statistics"], runs=["rep1", "rep2"])
    assert any("run rep2 does not exist" in p for p in evaluation_gate(config))


def evaluation_rows(run_ids, conditions=("C1", "C2"), cases=CASES):
    return pd.DataFrame([{"run_id": r, "condition": c, "case_id": k} for r in run_ids for c in conditions for k in cases])


def test_statistics_gate(tmp_path):
    config, _ = setup(tmp_path)
    assert "no evaluation" in statistics_gate(config)[0]
    path = tmp_path / "evaluation.csv"
    evaluation_rows(["rep1"]).to_csv(path, index=False)
    assert statistics_gate(config) == []
    evaluation_rows(["rep1", "smoke"]).to_csv(path, index=False)
    assert any("holds runs ['rep1', 'smoke']" in p for p in statistics_gate(config))
    evaluation_rows(["rep1"], cases=["01"]).to_csv(path, index=False)
    assert any("has 2 of 4" in p for p in statistics_gate(config))


def test_commands_stop_when_the_gate_is_closed(tmp_path, monkeypatch):
    from src import evaluate, statistics
    config, _ = setup(tmp_path, runs_complete=False)
    monkeypatch.setattr(evaluate, "load_config", lambda: config)
    monkeypatch.setattr(statistics, "load_config", lambda: config)
    monkeypatch.setattr(sys, "argv", ["evaluate"])
    with pytest.raises(SystemExit, match="evaluation gate is closed"):
        evaluate.main()
    with pytest.raises(SystemExit, match="statistics gate is closed"):
        statistics.main()
    assert not (tmp_path / "evaluation.csv").exists()
