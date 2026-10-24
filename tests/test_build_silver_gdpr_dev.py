"""Tests for the GDPR development silver labels (src/build_silver_gdpr_dev.py).

The annotator is a MockLLM; every builder writes into pytest's tmp_path, never into data/silver_gdpr/ or data/silver/.
"""

import copy
import hashlib
import json

import pytest

from src.agents.silver_annotator import SilverAnnotator
from src.build_silver_gdpr_dev import (GdprDevSilverBuilder, choose_version, label_counts, totals, union_passages,
                                       version_passages)
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]


def answer(label: str) -> str:
    steps = [{"label": "Inform customer", "actor": "Shop", "when": None, "already_in_description": False}]
    return json.dumps({"label": label, "facts": [], "reason": "r", "evidence": [],
                       "required_steps": steps if label == "applicable" else [], "possible_steps": []})


def make_builder(tmp_path, answers, run_id="t1") -> GdprDevSilverBuilder:
    config = copy.deepcopy(CONFIG)
    config["study2_gdpr"]["silver_reference_dev"] = str(tmp_path / "silver_dev.json")
    annotator = SilverAnnotator(MockLLM(answers), RunLogger(tmp_path / "logs", GDPR["silver_log_condition"], run_id))
    return GdprDevSilverBuilder(config, annotator)


# ---------- union of the two versions ----------

def test_union_lists_each_passage_once_hybrid_first():
    per_version = {"hybrid": {"01": [{"rank": 1, "passage_id": "A", "text": "a"}, {"rank": 2, "passage_id": "B", "text": "b"}]},
                   "rerank": {"01": [{"rank": 1, "passage_id": "C", "text": "c"}, {"rank": 2, "passage_id": "A", "text": "a"}]}}
    assert union_passages(per_version, "01") == [{"rank": 1, "passage_id": "A", "text": "a"},
                                                 {"rank": 2, "passage_id": "B", "text": "b"},
                                                 {"rank": 3, "passage_id": "C", "text": "c"}]


def test_union_of_the_committed_files_has_63_pairs():
    paths = {"hybrid": project_path(GDPR["frozen_dev_hybrid_restricted"]),
             "rerank": project_path(GDPR["frozen_dev_rerank_restricted"])}
    per_version = version_passages(paths)
    assert sum(len(union_passages(per_version, c)) for c in GDPR["development_ids"]) == 63


# ---------- the selection rule (docs/C3_V2_DEVELOPMENT.md section 4) ----------

def labelled(hybrid: list[str], rerank: list[str]) -> dict:
    """One case; hybrid passages h0.., rerank passages r0.. with the given labels."""
    passages = [{"passage_id": f"h{i}", "label": l} for i, l in enumerate(hybrid)] + \
               [{"passage_id": f"r{i}", "label": l} for i, l in enumerate(rerank)]
    return {"case_versions": {"01": {"hybrid": [f"h{i}" for i in range(len(hybrid))],
                                     "rerank": [f"r{i}" for i in range(len(rerank))]}},
            "cases": {"01": {"passages": passages}}}


def test_rule_step_1_more_applicable_wins():
    data = labelled(["applicable", "irrelevant"], ["applicable", "applicable"])
    assert choose_version(data)[0] == "rerank" and "step 1" in choose_version(data)[1]


def test_rule_step_2_fewer_irrelevant_wins():
    data = labelled(["applicable", "irrelevant"], ["applicable", "indeterminate"])
    assert choose_version(data)[0] == "rerank" and "step 2" in choose_version(data)[1]


def test_rule_step_3_tie_goes_to_hybrid():
    data = labelled(["indeterminate", "irrelevant"], ["irrelevant", "not_applicable"])
    assert choose_version(data)[0] == "hybrid" and "step 3" in choose_version(data)[1]


def test_shared_passage_counts_for_both_versions_and_failures_are_other():
    data = labelled(["applicable", "annotation_failed"], [])
    data["case_versions"]["01"]["rerank"] = ["h0"]   # the same passage in both versions, labelled once
    assert label_counts(data, "rerank")["01"]["applicable"] == 1
    assert totals(label_counts(data, "hybrid")) == {"applicable": 1, "indeterminate": 0, "not_applicable": 0,
                                                    "irrelevant": 0, "other": 1}


# ---------- the builder (mock annotator) ----------

def test_builder_labels_every_pair_once_and_records_both_versions(tmp_path):
    builder = make_builder(tmp_path, [answer("indeterminate")])
    assert builder.output_path == tmp_path / "silver_dev.json"
    data = builder.build()
    assert list(data["cases"]) == GDPR["development_ids"]
    assert sum(len(c["passages"]) for c in data["cases"].values()) == 63
    for case_id, case in data["cases"].items():
        ids = [p["passage_id"] for p in case["passages"]]
        assert len(ids) == len(set(ids))
        assert set(ids) == set(data["case_versions"][case_id]["hybrid"]) | set(data["case_versions"][case_id]["rerank"])
    sha = lambda key: hashlib.sha256(project_path(GDPR[key]).read_bytes()).hexdigest()
    assert data["frozen_retrieval_sha256"] == sha("frozen_dev_hybrid_restricted")
    assert data["frozen_retrieval_rerank_sha256"] == sha("frozen_dev_rerank_restricted")
    assert data["prompt_sha256"] == hashlib.sha256(project_path(CONFIG["paths"]["silver_prompt"]).read_bytes()).hexdigest()
    assert any((tmp_path / "logs").glob("SILVER_gdpr_dev_*.jsonl"))


def test_builder_refuses_changed_rerank_file(tmp_path):
    make_builder(tmp_path, [answer("irrelevant")]).build()
    saved = json.loads((tmp_path / "silver_dev.json").read_text(encoding="utf-8"))
    saved["frozen_retrieval_rerank_sha256"] = "0" * 64
    (tmp_path / "silver_dev.json").write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match="rerank frozen retrieval changed"):
        make_builder(tmp_path, [answer("irrelevant")], run_id="t2").build()


def test_builder_resumes_without_relabelling(tmp_path):
    make_builder(tmp_path, [answer("applicable")]).build()
    data = make_builder(tmp_path, ["not json"], run_id="t2").build()   # would give annotation_failed if called
    assert {p["label"] for c in data["cases"].values() for p in c["passages"]} == {"applicable"}


def test_output_and_logs_are_separate_from_study1():
    assert GDPR["silver_reference_dev"] == "data/silver_gdpr/silver_reference_dev.json"
    assert GDPR["silver_log_condition"].startswith("SILVER_gdpr_dev")
    assert CONFIG["paths"]["silver_reference"] == "data/silver/silver_reference.json"


# ---------- the committed silver file ----------

def test_committed_silver_file_matches_its_inputs():
    data = json.loads(project_path(GDPR["silver_reference_dev"]).read_text(encoding="utf-8"))
    assert data["annotator_model"] == CONFIG["silver"]["model"] == "openai/gpt-oss-120b"
    assert data["prompt_sha256"] == hashlib.sha256(project_path(CONFIG["paths"]["silver_prompt"]).read_bytes()).hexdigest()
    study1 = json.loads(project_path(CONFIG["paths"]["silver_reference"]).read_text(encoding="utf-8"))
    assert data["prompt_sha256"] == study1["prompt_sha256"]   # the same prompt as Study 1
    assert data["frozen_retrieval_sha256"] == hashlib.sha256(
        project_path(GDPR["frozen_dev_hybrid_restricted"]).read_bytes()).hexdigest()
    assert sum(len(c["passages"]) for c in data["cases"].values()) == 63
    assert all(p["label"] != "annotation_failed" for c in data["cases"].values() for p in c["passages"])
