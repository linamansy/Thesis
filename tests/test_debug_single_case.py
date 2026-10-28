"""Tests for scripts/debug_single_case.py: stage files, target ranks, run folders. MockLLM only, no Ollama."""

import json

from scripts.debug_single_case import (CASE_ID, debug_run, load_answer_key, load_frozen_case, next_run_dir,
                                        retrieval_stages, summary_text, target_ranks)
from src.config import load_config
from src.llm.mock_llm import MockLLM

CONFIG = load_config()
DESCRIPTION = "The customer chooses a product. The customer pays by card. The shop sends the product."
PASSAGE = "If a customer pays by card, the shop must give a receipt, unless the customer declines it."
RELEVANT = {"law_focus": "card payments", "law_quote": "a customer pays by card", "relevant": True,
            "process_step": "the customer pays by card", "description_quote": "The customer pays by card",
            "reason": "The process has a card payment step."}
SPLIT = {"roles": ["controller"], "if": ["a customer pays by card"], "then": "the shop must give a receipt",
         "exceptions": []}
CONFIRMED = {"results": [{"id": "C1", "status": "confirmed", "quote": "The customer pays by card"}]}
REQUIREMENT = {"requirement": "After the customer pays by card, a receipt is handed to the customer.",
               "step_quote": "The customer pays by card",
               "triggers": [{"trigger": "a customer pays by card", "kept_as": "After the customer pays by card"}],
               "duty": {"from_then": "give a receipt", "kept_as": "a receipt is handed"}}


def toy_case():
    cand = [{"rank": i, "passage_id": f"P-{i}", "rerank_score": -i, "hybrid_rank": 21 - i, "fused_score": 0.1 * i}
            for i in range(1, 21)]
    return {"queries": [DESCRIPTION], "reranker_queries": [DESCRIPTION], "candidates": cand,
            "passages": [dict(c, text=PASSAGE) for c in cand[:5]]}


def test_frozen_01_1_is_read_and_checksummed():
    case, sha = load_frozen_case(CONFIG)
    key = load_answer_key(CONFIG)
    assert len(sha) == 64 and len(case["candidates"]) == 20 and len(case["passages"]) == 5
    assert key["target_passage_id"] == "GDPR-Art13-1"
    ranks = target_ranks(case, key)
    assert ranks["top5"] is None or ranks["hybrid_top20"] is not None   # top 5 is a subset of the 20


def test_retrieval_stages_are_in_hybrid_order_and_mark_the_target():
    key = {"target_passage_id": "P-3", "accepted_target_ids": ["P-3"], "expected_step": "x"}
    files = retrieval_stages(toy_case(), DESCRIPTION, key)
    top20 = files["02_top20_before_rerank.json"]["candidates"]
    assert [c["hybrid_rank"] for c in top20] == list(range(1, 21))
    assert [c["passage_id"] for c in top20 if c["is_target"]] == ["P-3"]
    assert len(files["03_top5_after_rerank.json"]["passages"]) == 5
    assert target_ranks(toy_case(), key) == {"hybrid_top20": 18, "after_rerank_among_20": 3, "top5": 3,
                                             "passage_id": "P-3"}


def test_next_run_dir_never_reuses_a_folder(tmp_path):
    assert next_run_dir(tmp_path).name == "run_1"
    (tmp_path / "run_1").mkdir()
    (tmp_path / "run_3").mkdir()
    assert next_run_dir(tmp_path).name == "run_4"


def test_debug_run_writes_every_stage(tmp_path):
    case = toy_case()
    case["passages"] = case["passages"][:1]
    llm = MockLLM([json.dumps(a) for a in (RELEVANT, SPLIT, CONFIRMED, REQUIREMENT)])
    key = {"target_passage_id": "P-1", "accepted_target_ids": ["P-1"], "expected_step": "x"}
    out = debug_run(CONFIG, case, DESCRIPTION, key, llm, tmp_path / "run_1", {"case_id": CASE_ID})
    names = sorted(p.name for p in (tmp_path / "run_1").glob("*.json"))
    assert names == ["00_run_info.json", "01_query.json", "02_top20_before_rerank.json", "03_top5_after_rerank.json",
                     "04_relevance.json", "05_applicability.json", "06_resolver.json", "07_second_look.json",
                     "08_final_requirement.json", "09_audit_trail_full.json"]
    resolver = json.loads((tmp_path / "run_1" / "06_resolver.json").read_text(encoding="utf-8"))[0]
    assert resolver["final_label"] == "Applicable" and resolver["resolution"]["reason"]
    conditions = json.loads((tmp_path / "run_1" / "05_applicability.json").read_text(encoding="utf-8"))[0][
        "applicability"]["conditions"]
    assert any(c["id"] == "C1" and c["quote"] == "The customer pays by card" for c in conditions)
    final = json.loads((tmp_path / "run_1" / "08_final_requirement.json").read_text(encoding="utf-8"))
    assert "receipt" in final["knowledge_block"]
    text = summary_text(key, target_ranks(case, key), [out], case)
    assert "P-1" in text and "Applicable" in text
