"""Tests for scripts/debug_mediation_on_passages.py: corpus lookup, folders, stage files. MockLLM only, no Ollama."""

import json

import pytest

from scripts.debug_mediation_on_passages import (given_case, load_corpus_passages, next_med_dir, reason,
                                                 summary_text)
from scripts.debug_single_case import debug_run
from src.config import load_config
from src.llm.mock_llm import MockLLM
from tests.test_debug_single_case import CONFIRMED, DESCRIPTION, PASSAGE, RELEVANT, REQUIREMENT, SPLIT

CONFIG = load_config()


def test_passages_come_from_the_corpus_in_the_given_order():
    passages, sha = load_corpus_passages(CONFIG, ["GDPR-Art13-3", "GDPR-Art13-1"])
    assert [p["passage_id"] for p in passages] == ["GDPR-Art13-3", "GDPR-Art13-1"]
    assert [p["rank"] for p in passages] == [1, 2] and len(sha) == 64 and passages[0]["text"]


def test_unknown_passage_id_is_refused():
    with pytest.raises(KeyError):
        load_corpus_passages(CONFIG, ["NOPE-Art1-1"])


def test_next_med_dir_counts_per_label(tmp_path):
    (tmp_path / "med_oracle_run_1").mkdir()
    (tmp_path / "med_oracle_run_2").mkdir()
    (tmp_path / "med_other_run_7").mkdir()
    assert next_med_dir(tmp_path, "oracle").name == "med_oracle_run_3"
    assert next_med_dir(tmp_path, "new").name == "med_new_run_1"


def test_mock_run_writes_stage_files_and_summary(tmp_path):
    passages = [{"rank": 1, "passage_id": "P-1", "text": PASSAGE, "rerank_score": None, "hybrid_rank": None}]
    llm = MockLLM([json.dumps(a) for a in (RELEVANT, SPLIT, CONFIRMED, REQUIREMENT)])
    key = {"target_passage_id": "P-1", "accepted_target_ids": ["P-1"], "expected_step": "x"}
    out = debug_run(CONFIG, given_case(passages, DESCRIPTION), DESCRIPTION, key, llm, tmp_path / "med_t_run_1",
                    {"model": "mock"})
    assert out["records"][0]["label"] == "Applicable"
    assert (tmp_path / "med_t_run_1" / "08_final_requirement.json").exists()
    text = summary_text("t", [out])
    assert "P-1" in text and "Applicable" in text and "requirement:" in text
    assert reason(out["records"][0]) == ""


# ---------- fix B (28 Oct 2026): the printed cause is the code's, never the model's reason ----------

def test_printed_cause_is_the_code_cause_not_the_model_reason():
    model_reason = "The rule is about transparent information, which the process does."
    record = {"passage_id": "P-1", "label": "Irrelevant", "failed_step": None, "requirement": None,
              "label_cause": "law_quote not found", "relevance": {"reason": model_reason}, "resolution": None}
    assert reason(record) == "law_quote not found"
    assert model_reason not in summary_text("t", [{"run": "r", "records": [record]}])


def test_applicable_without_a_valid_requirement_shows_the_failed_check():
    record = {"passage_id": "P-1", "label": "Applicable", "failed_step": None, "relevance": None, "resolution": None,
              "label_cause": 'requirement invalid: the trigger "where applicable" is not copied word for word',
              "requirement": {"requirement": None, "requirement_invalid": True}}
    assert reason(record).startswith("requirement invalid: ")
    text = summary_text("t", [{"run": "r", "records": [record]}])
    assert "Applicable  (requirement invalid: " in text and "requirement: None" not in text
