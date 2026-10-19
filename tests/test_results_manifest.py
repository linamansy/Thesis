"""Tests for the results manifest (src/results_manifest.py, fix E3) on a synthetic results folder."""

import hashlib
import json

import pytest

from src.config import load_config
from src.results_manifest import ResultsManifest

CONFIG = load_config()


def results_folder(tmp_path):
    root = tmp_path / "results"
    files = {
        "runs/ollama_rep2/run_info.json": json.dumps({"run_id": "ollama_rep2", "repetition": 2}),
        "runs/ollama_rep2/C2/05/generated.bpmn": "<bpmn/>",
        "runs/ollama_rep2/C2/05/bpmngen/meta.json": "{}",
        "runs/ollama_rep2/C3/mediation/05.json": "{}",
        "runs/ollama_rep2/C3/mediation/run_summary.json": "{}",
        "runs/smoke_x/run_info.json": json.dumps({"run_id": "smoke_x", "repetition": 1}),
        "logs/C3_ollama_rep2_part2.jsonl": "",
        "logs/SILVER_silver_1.jsonl": "",
        "_discarded/old_run/README.txt": "why",
        "evaluation.csv": "a,b",
        "MANIFEST.csv": "old",
        "README.md": "readme",
    }
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    return root


def config_for():
    return dict(CONFIG, statistics=dict(CONFIG["statistics"], runs=["ollama_rep1", "ollama_rep2", "ollama_rep3"]))


def test_every_file_is_described_with_its_hash(tmp_path):
    root = results_folder(tmp_path)
    rows = {r["path"]: r for r in ResultsManifest(config_for(), root).rows()}
    assert "MANIFEST.csv" not in rows and "README.md" not in rows          # the manifest does not list itself
    case = rows["runs/ollama_rep2/C2/05/bpmngen/meta.json"]
    assert (case["status"], case["run_id"], case["repetition"], case["condition"], case["case_id"], case["role"]) == \
        ("study", "ollama_rep2", 2, "C2", "05", "bpmngen/meta.json")
    assert case["sha256"] == hashlib.sha256(b"{}").hexdigest() and case["bytes"] == 2
    assert rows["runs/ollama_rep2/C3/mediation/05.json"]["role"] == "mediation_case"
    assert rows["runs/ollama_rep2/C3/mediation/05.json"]["case_id"] == "05"
    assert rows["runs/ollama_rep2/C3/mediation/run_summary.json"]["role"] == "mediation_summary"
    log = rows["logs/C3_ollama_rep2_part2.jsonl"]
    assert (log["run_id"], log["condition"], log["role"], log["repetition"]) == ("ollama_rep2", "C3", "llm_log_part2", 2)
    assert rows["logs/SILVER_silver_1.jsonl"]["role"] == "silver_log"
    assert rows["runs/smoke_x/run_info.json"]["status"] == "smoke"
    assert rows["_discarded/old_run/README.txt"]["status"] == "discarded"
    assert rows["evaluation.csv"]["role"] == "evaluation.csv"


def test_building_the_manifest_changes_no_file(tmp_path):
    root = results_folder(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    ResultsManifest(config_for(), root).rows()
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_command_never_overwrites(tmp_path, monkeypatch):
    from src import results_manifest
    root = results_folder(tmp_path)
    monkeypatch.setattr(results_manifest, "load_config",
                        lambda: dict(CONFIG, paths=dict(CONFIG["paths"], results_manifest=str(root / "MANIFEST.csv"))))
    with pytest.raises(SystemExit, match="never overwritten"):
        results_manifest.main()
    assert (root / "MANIFEST.csv").read_text(encoding="utf-8") == "old"
