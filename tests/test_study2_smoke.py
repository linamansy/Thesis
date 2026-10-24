"""Tests for the Study 2 config view, the GDPR development smoke run, its evaluation and the Study 2 manifest.

No Ollama, no BPMNGen: the run folder of the smoke run is faked in pytest's tmp_path (a reference model copied as the
"generated" model). The task matcher is the locally cached embedding model, as in tests/test_evaluate.py.
"""

import copy
import json
import shutil

import pandas as pd
import pytest

from src.config import load_config, project_path
from src.evaluate import Evaluator
from src.evaluate_gdpr_dev_smoke import (SmokeEvaluator, check_silver_matches_retrieval, input_string_length,
                                         markdown_table, silver_for_version)
from src.results_manifest_study2 import build_manifest, study2_files
from src.run_gdpr_dev_smoke import check_development_only, smoke_run_id
from src.study2_config import study2_view
from src.task_matcher import TaskMatcher

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]


# ---------- config view (decision 1, 24 Oct 2026) ----------

def test_view_uses_the_reranked_gdpr_retrieval_and_leaves_study1_unchanged():
    view = study2_view(CONFIG)
    assert view["paths"]["frozen_retrieval"] == GDPR["frozen_retrieval"] == GDPR["frozen_dev_rerank_restricted"]
    assert GDPR["retrieval_version"] == "rerank"
    assert view["reranker"]["enabled"] is True
    assert view["paths"]["passages"] == GDPR["passages_restricted"]
    assert view["cases"]["ids"] == GDPR["development_ids"]
    assert CONFIG["reranker"]["enabled"] is False                                         # Study 1 default
    assert CONFIG["paths"]["frozen_retrieval"] == "data/retrieval/frozen_retrieval.json"  # Study 1 default
    assert view["generator"] == CONFIG["generator"] and view["model"] == CONFIG["model"]  # same generator


def test_smoke_run_id_must_be_a_smoke_run():
    assert smoke_run_id(CONFIG) == "smoke_gdpr_dev"
    for bad in ("gdpr_dev", "ollama_rep1"):
        config = copy.deepcopy(CONFIG)
        config["study2_gdpr"]["smoke_run_id"] = bad
        with pytest.raises(ValueError, match="must start with"):
            smoke_run_id(config)


def test_smoke_run_refuses_non_development_cases():
    view = study2_view(CONFIG)
    check_development_only(view)
    view["cases"]["ids"] = view["cases"]["ids"] + ["03"]   # a Study 1 case outside the GDPR development set
    with pytest.raises(ValueError, match="development cases only"):
        check_development_only(view)


# ---------- silver restricted to the chosen version ----------

def test_silver_for_version_keeps_only_that_versions_passages():
    silver = {"case_versions": {"01": {"hybrid": ["A"], "rerank": ["B"]}},
              "cases": {"01": {"required_steps": [{"passage_id": "A", "label": "a"},
                                                  {"passage_id": "B", "label": "b"}]}}}
    assert silver_for_version(silver, "rerank") == {"01": {"required_steps": [{"passage_id": "B", "label": "b"}]}}


def test_committed_silver_for_rerank():
    silver = json.loads(project_path(GDPR["silver_reference_dev"]).read_text(encoding="utf-8"))
    check_silver_matches_retrieval(silver, project_path(GDPR["frozen_retrieval"]), "rerank")
    cases = silver_for_version(silver, "rerank")
    steps = {c: [s["passage_id"] for s in case["required_steps"]] for c, case in cases.items()}
    assert steps["11"] == ["GDPR-Art32-2", "GDPR-Art32-2"] and steps["19"] == ["GDPR-Art16-1", "GDPR-Art16-1"]
    assert steps["45"] == []   # GDPR-Art13-2-a is in the hybrid top 5 only


def test_silver_check_refuses_another_frozen_file(tmp_path):
    silver = json.loads(project_path(GDPR["silver_reference_dev"]).read_text(encoding="utf-8"))
    other = tmp_path / "frozen.json"
    other.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="another rerank frozen file"):
        check_silver_matches_retrieval(silver, other, "rerank")


# ---------- inputString length ----------

def test_input_string_length_uses_the_server_layout():
    label = CONFIG["generator"]["knowledge_label"]
    assert input_string_length(" Desc. \n", label, "\nK\n") == len(f"Desc.\n\n{label}\nK")
    assert CONFIG["bpmngen_server"]["input_string_max_chars"] == 30000


# ---------- the smoke evaluation on a faked run folder ----------

@pytest.fixture(scope="module")
def matcher():
    settings = CONFIG["evaluation"]
    return TaskMatcher(settings["embedding_model"], settings["similarity_threshold"])


def fake_smoke_run(tmp_path) -> dict:
    """A config whose runs and output folders are in tmp_path, with a smoke run of C1 and C2 for cases 01 and 11."""
    config = copy.deepcopy(CONFIG)
    config["paths"]["runs"] = str(tmp_path / "runs")
    config["paths"]["gdpr_dev_smoke_dir"] = str(tmp_path / "out")
    run_dir = tmp_path / "runs" / "smoke_gdpr_dev"
    info = {"run_id": "smoke_gdpr_dev", "repetition": 1, "provider": "ollama", "model": "qwen3:8b",
            "conditions": {"C1": {}, "C2": {}}}
    run_dir.mkdir(parents=True)
    (run_dir / "run_info.json").write_text(json.dumps(info), encoding="utf-8")
    for condition in ("C1", "C2"):
        for case_id in ("01", "11"):
            case_dir = run_dir / condition / case_id
            case_dir.mkdir(parents=True)
            shutil.copy(project_path(CONFIG["paths"]["cases"]) / case_id / "reference.bpmn", case_dir / "generated.bpmn")
            (case_dir / "knowledge_block.txt").write_text("x" * (40000 if case_id == "11" else 10), encoding="utf-8")
            validation = {"generation_succeeded": True, "valid": True, "errors": [],
                          "bpmngen": {"prompt_tokens": 20000 if case_id == "11" else 5000, "auto_repairs": {}}}
            (case_dir / "validation.json").write_text(json.dumps(validation), encoding="utf-8")
    return config


def test_smoke_evaluation_writes_only_into_its_folder(tmp_path, matcher):
    config = fake_smoke_run(tmp_path)
    smoke = SmokeEvaluator(config, Evaluator(study2_view(config), matcher))
    result = smoke.write()
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        ["evaluation.csv", "summary.csv", "input_string_check.csv", "report.md"])
    assert not list((tmp_path / "runs").rglob("evaluation.json"))          # nothing written into the run folder
    table = result["evaluation"]
    assert len(table) == 4 and (table["f1"] == 1.0).all()                  # the reference against itself
    assert set(table["case_id"]) == {"01", "11"}
    assert table["n_required_steps"].tolist() == [0, 2, 0, 2]              # GDPR silver (rerank), not Study 1's
    lengths = result["lengths"].set_index(["condition", "case_id"])
    assert lengths.loc[("C1", "01"), "chars_ok"] and not lengths.loc[("C1", "11"), "chars_ok"]
    assert lengths.loc[("C1", "01"), "tokens_ok"] and not lengths.loc[("C1", "11"), "tokens_ok"]
    assert result["summary"]["n_valid"].tolist() == [2, 2]
    with pytest.raises(FileExistsError):
        smoke.write()


def test_markdown_table():
    assert markdown_table(pd.DataFrame({"a": [1, None], "b": ["x", "y"]})).splitlines() == [
        "| a | b |", "|---|---|", "| 1.0 | x |", "|  | y |"]


# ---------- Study 2 manifest ----------

def test_study2_manifest_lists_only_study2_files(tmp_path):
    results = tmp_path / "results"
    for name in ("logs/SILVER_gdpr_dev_silver_1.jsonl", "logs/C1_smoke_gdpr_dev.jsonl", "logs/C1_ollama_rep1.jsonl",
                 "runs/smoke_gdpr_dev/C1/01/generated.bpmn", "runs/ollama_rep1/C1/01/generated.bpmn",
                 "diagnostics/gdpr_dev_smoke/report.md", "diagnostics/precision_recall.md", "MANIFEST.csv"):
        (results / name).parent.mkdir(parents=True, exist_ok=True)
        (results / name).write_text("x", encoding="utf-8")
    config = copy.deepcopy(CONFIG)
    config["paths"]["results_manifest_study2"] = str(results / "MANIFEST_study2.csv")
    table = build_manifest(config)
    assert table["path"].tolist() == ["diagnostics/gdpr_dev_smoke/report.md", "logs/C1_smoke_gdpr_dev.jsonl",
                                      "logs/SILVER_gdpr_dev_silver_1.jsonl", "runs/smoke_gdpr_dev/C1/01/generated.bpmn"]
    assert table.set_index("path").loc["logs/C1_smoke_gdpr_dev.jsonl", "status"] == "smoke"
    assert study2_files(results, ["*.csv"], {"MANIFEST.csv"}) == []
