"""Tests for the RAG v2 extra round (docs/RAG_V2_CRITERIA.md section 7): configs A-D, QueryRewriter, variant hits.

No real model is called: the rewriter gets a MockLLM, the reranker a fake cross-encoder. The embedding model is
local. Nothing is frozen; the prefixed dense index of config A is built in a temporary folder.
"""

import json
import re

import pytest

from src.config import load_config, project_path
from src.evaluate_retrieval_v2 import evaluate, variant_hits
from src.freeze_rag_v2_extra import freeze_extra
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.rag_v2_extra import ExtraRoundRetriever, index_text, law_names, make_rewriter
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.passage import load_passages
from src.retrieval.query_rewriter import QueryRewriter, parse_queries

CONFIG = load_config()
EXTRA = CONFIG["rag_v2"]["extra_round"]
SHOP = ("A customer orders goods in the online shop. The shop sends an order confirmation by email. "
        "The customer pays the invoice within 30 days.")
ANSWER = "- distance contract consumer order\n2. order confirmation trader\n\n* late payment interest\n"


class ShortFirstModel:
    """Fake cross-encoder: the shorter the passage, the higher the score (same for every query)."""

    def predict(self, pairs, batch_size, show_progress_bar):
        return [-float(len(text)) for _, text in pairs]


def fake_reranker():
    return CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())


def rewriter(tmp_path, answer=ANSWER):
    template = project_path(EXTRA["rewrite_prompt"]).read_text(encoding="utf-8")
    return QueryRewriter(MockLLM([answer]), template, tmp_path / "rewrites",
                         lambda: RunLogger(tmp_path / "logs", EXTRA["rewrite_log_condition"], "test"))


# ---------- the fixed settings equal the criteria doc ----------

def test_rewrite_prompt_is_the_doc_block_byte_for_byte():
    doc = project_path("docs/RAG_V2_CRITERIA.md").read_text(encoding="utf-8")
    section = doc[doc.index("### 7.3"):doc.index("### 7.4")]
    block = re.search(r"```text\n(.*?)```", section, re.S).group(1)
    assert project_path(EXTRA["rewrite_prompt"]).read_text(encoding="utf-8") == block
    assert block.startswith("/no_think\n") and block.count("{description}") == 1


def test_configs_equal_section_7_2_and_baseline():
    assert EXTRA["configs"] == {"A": {"index_prefix": True, "rewrite": False, "pool": 20},
                                "B": {"index_prefix": False, "rewrite": True, "pool": 20},
                                "C": {"index_prefix": False, "rewrite": False, "pool": 50},
                                "D": {"index_prefix": True, "rewrite": True, "pool": 50}}
    assert EXTRA["simplicity_order"] == ["A", "C", "B", "D"] and EXTRA["baseline_m1"] == 2
    assert CONFIG["reranker"]["candidates"] == 20 and CONFIG["rag_v2"]["sibling_expansion"] is False
    assert EXTRA["frozen_retrieval"] != CONFIG["rag_v2"]["frozen_retrieval"]   # never the current freeze


def test_agent_settings_are_the_ones_section_7_2_fixes():
    assert CONFIG["llm"]["temperature"] == 0 and CONFIG["llm"]["seed"] == 42
    assert CONFIG["model"]["think"] is False and CONFIG["model"]["num_ctx"] == 16384
    assert str(CONFIG["study2_gdpr"]["ollama_version"]) == "0.40.11"


def test_make_rewriter_refuses_the_mock_provider():
    with pytest.raises(ValueError, match="ollama"):
        make_rewriter(CONFIG)   # tests run with THESIS_FORCE_MOCK


# ---------- QueryRewriter ----------

def test_parse_queries_strips_marks_and_numbering_and_skips_empty_lines():
    assert parse_queries(ANSWER) == ["distance contract consumer order", "order confirmation trader",
                                     "late payment interest"]
    assert parse_queries("") == [] and parse_queries("\n  \n") == []
    assert parse_queries("30 days payment term") == ["30 days payment term"]   # a number without "." stays


def test_rewriter_puts_the_description_verbatim_saves_and_reuses(tmp_path):
    r = rewriter(tmp_path)
    assert r.rewrite("01", SHOP) == parse_queries(ANSWER)
    sent = r.llm.prompts_received[0]
    assert sent == project_path(EXTRA["rewrite_prompt"]).read_text(encoding="utf-8").replace("{description}", SHOP)
    saved = json.loads((tmp_path / "rewrites" / "01.json").read_text(encoding="utf-8"))
    assert saved["raw_output"] == ANSWER and saved["prompt"] == sent and saved["queries"] == parse_queries(ANSWER)
    log = [json.loads(line) for line in r.logger.log_path.read_text(encoding="utf-8").splitlines()]
    assert len(log) == 1 and log[0]["component"] == "QueryRewriter" and log[0]["raw_output"] == ANSWER

    again = rewriter(tmp_path, answer="other answer")         # a new run: reuses the saved file, no LLM call
    assert again.rewrite("01", SHOP) == parse_queries(ANSWER) and again.llm.prompts_received == []
    with pytest.raises(RuntimeError, match="changed"):
        again.rewrite("01", SHOP + " Changed.")


# ---------- configs A, B, C ----------

def test_index_text_example_of_the_doc():
    corpus = {p.id: p for p in load_passages(project_path(CONFIG["study2_corpus"]["passages"]))}
    text = index_text(corpus["LPD-Art3-1"], law_names(CONFIG))
    assert text.startswith("Late Payment Directive 2011/7/EU, Article 3: Transactions between undertakings.\n")
    assert text.endswith(corpus["LPD-Art3-1"].text)


@pytest.fixture(scope="module")
def config_c():
    return ExtraRoundRetriever(CONFIG, "C", reranker=fake_reranker())


def test_config_c_reranks_a_pool_of_50_and_keeps_5(config_c):
    case = config_c.retrieve(SHOP)
    assert len(case["candidates"]) == 50 and len(case["passages"]) == 5
    assert case["rewritten_queries"] is None and case["config"] == "C"


def test_config_a_indexes_prefixed_text_but_returns_the_corpus_text(tmp_path):
    a = ExtraRoundRetriever(CONFIG, "A", reranker=fake_reranker(), dense_index_dir=tmp_path / "index")
    corpus = {p.id: p for p in load_passages(project_path(CONFIG["study2_corpus"]["passages"]))}
    assert all(p.text == index_text(corpus[p.id], law_names(CONFIG)) for p in a.dense.passages)
    assert all(p.text == index_text(corpus[p.id], law_names(CONFIG)) for p in a.sparse.passages)
    case = a.retrieve(SHOP)
    assert len(case["candidates"]) == 20 and len(case["passages"]) == 5
    assert all(p["text"] == corpus[p["passage_id"]].text for p in case["passages"])


def test_config_b_adds_rewritten_queries_after_the_originals(tmp_path, config_c):
    b = ExtraRoundRetriever(CONFIG, "B", reranker=fake_reranker(), rewriter=rewriter(tmp_path))
    case = b.retrieve(SHOP, "01")
    originals = b.query_builder.build(SHOP)
    assert case["queries"] == originals + parse_queries(ANSWER)
    assert case["reranker_queries"] == case["queries"][1:] and len(case["candidates"]) == 20
    with pytest.raises(ValueError, match="QueryRewriter"):
        ExtraRoundRetriever(CONFIG, "B", reranker=fake_reranker())


def test_freeze_extra_names_section_7_4_and_keeps_the_case_list(config_c):
    frozen = freeze_extra(CONFIG, config_c, ["report.json"])
    variants = [i["case_id"] for i in
                json.loads(project_path(CONFIG["rag_v2"]["test_set"]).read_text(encoding="utf-8"))["items"]]
    assert list(frozen["cases"]) == CONFIG["study2_cases"]["ids"] + variants
    assert frozen["rag_v2"]["decided_by"] == "docs/RAG_V2_CRITERIA.md section 7.4"
    assert frozen["rag_v2"]["extra_round_config"]["config"] == "C" and frozen["rag_v2"]["sibling_expansion"] is False


# ---------- variant hits (held-out: any accepted target) ----------

def test_variant_hit_if_any_accepted_target_is_in_the_top_5():
    top = ["A-1", "A-2", "A-3", "A-4", "A-5"]
    retrievals = {"05.1": {"passages": [{"passage_id": p} for p in top],
                           "candidates": [{"rank": i, "passage_id": p} for i, p in enumerate(top + ["B-1"], 1)]},
                  "03.1": {"passages": [{"passage_id": p} for p in top],
                           "candidates": [{"rank": i, "passage_id": p} for i, p in enumerate(top + ["B-1"], 1)]}}
    items = [{"case_id": "05.1", "targets": ["B-1", "A-4"]}, {"case_id": "03.1", "targets": ["B-1"]}]
    hits = variant_hits(evaluate(retrievals, items, top_k=5))
    assert hits["n_hit"] == 1 and hits["n_variants"] == 2
    assert hits["per_variant"]["05.1"] == {"hit": True, "best_rank": 4, "targets": {"B-1": 6, "A-4": 4}}
    assert hits["per_variant"]["03.1"]["hit"] is False and hits["per_variant"]["03.1"]["best_rank"] == 6
