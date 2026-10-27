"""Tests for RAG v2 (src/rag_v2.py, src/retrieval/sibling_expander.py, src/evaluate_retrieval_v2.py).

The dense model (e5-small-v2) is the locally cached one used by the other retrieval tests, and the dense indexes are
the committed ones (only read). The cross-encoder is always a fake model, so nothing is downloaded and no LLM is
called. No frozen retrieval file is written; nothing is frozen.
"""

import json

import pytest

from src.config import load_config, project_path
from src.evaluate_retrieval_v2 import evaluate, expected_law_share, law_of
from src.freeze_retrieval_gdpr import GdprDevFreezer
from src.rag_v2 import RagV2Retriever, corpus_view
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.passage import Passage, load_passages
from src.retrieval.search_result import SearchResult
from src.retrieval.sibling_expander import SiblingExpander

CONFIG = load_config()
TOP_K = CONFIG["reranker"]["top_k"]
N_CANDIDATES = CONFIG["reranker"]["candidates"]


class ShortFirstModel:
    """Fake cross-encoder: the shorter the passage, the higher the score (same for every query)."""

    def predict(self, pairs, batch_size, show_progress_bar):
        return [-float(len(text)) for _, text in pairs]


class ReplayModel:
    """Fake cross-encoder that gives every (query, passage text) pair the score stored in a frozen file."""

    def __init__(self, scores: dict[tuple[str, str], float]):
        self.scores = scores

    def predict(self, pairs, batch_size, show_progress_bar):
        return [self.scores[pair] for pair in pairs]


def passage(pid: str, article, paragraph, directive="2011/83/EU") -> Passage:
    return Passage(id=pid, directive=directive, article=article, paragraph=paragraph, title="t", text=pid,
                   n_chars=len(pid))


def hit(p: Passage, rank: int) -> SearchResult:
    return SearchResult(passage=p, score=1.0 / rank, rank=rank)


# ---------- sibling expander ----------

MINI = [passage("CRD-Art6-1-a", 6, 1), passage("CRD-Art6a-1-a", "6a", 1), passage("CRD-Art6a-2", "6a", 2),
        passage("CRD-Art9-1", 9, 1), passage("CRD-Art9-1a", 9, "1a"), passage("CRD-Art9-2-a", 9, 2),
        passage("SGD-Art9-1", 9, 1, directive="(EU) 2019/771")]


def test_siblings_same_law_and_article_with_letter_ids():
    added = SiblingExpander(MINI).siblings([hit(MINI[3], 1), hit(MINI[2], 2)])   # CRD-Art9-1, CRD-Art6a-2
    assert [a.passage.id for a in added] == ["CRD-Art9-1a", "CRD-Art9-2-a", "CRD-Art6a-1-a"]
    # Article 6a is not Article 6, and Article 9 of another law is not a sibling
    assert "CRD-Art6-1-a" not in [a.passage.id for a in added] and "SGD-Art9-1" not in [a.passage.id for a in added]
    assert [a.rank for a in added] == [3, 4, 5] and all(a.score == 0.0 for a in added)


def test_siblings_never_repeat_a_candidate_or_each_other():
    added = SiblingExpander(MINI).siblings([hit(MINI[3], 1), hit(MINI[4], 2)])   # CRD-Art9-1 and CRD-Art9-1a
    assert [a.passage.id for a in added] == ["CRD-Art9-2-a"]


# ---------- RAG v2 on the Study 2 corpus ----------

SHOP = ("An online shop sells clothes to private customers through its website. The customer orders a jacket and pays "
        "by card. Within 14 days the customer withdraws from the contract. The shop refunds the payment.")


@pytest.fixture(scope="module")
def study2_view():
    return corpus_view(CONFIG)


def test_expansion_off_by_default_and_view_points_to_the_study2_corpus(study2_view):
    assert CONFIG["rag_v2"]["sibling_expansion"] is False
    assert study2_view["study2_gdpr"]["passages_restricted"] == CONFIG["study2_corpus"]["passages"]
    assert study2_view["study2_gdpr"]["dense_index_dir_restricted"] == CONFIG["rag_v2"]["dense_index_dir"]
    assert CONFIG["study2_gdpr"]["passages_restricted"] == "data/knowledge_gdpr/passages_ch1-5.jsonl"   # unchanged


def test_committed_study2_index_matches_the_corpus(study2_view):
    meta = json.loads((project_path(CONFIG["rag_v2"]["dense_index_dir"]) / "index_meta.json").read_text(encoding="utf-8"))
    corpus = load_passages(project_path(CONFIG["study2_corpus"]["passages"]))
    assert meta["passage_ids"] == [p.id for p in corpus] and meta["n_passages"] == 289
    assert meta["model"] == CONFIG["retrieval"]["dense_model"]


@pytest.fixture(scope="module")
def expanded(study2_view):
    fake = CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())
    retriever = RagV2Retriever(study2_view, reranker=fake, sibling_expansion=True)
    return retriever, retriever.retrieve(SHOP)


def test_expansion_adds_siblings_reranks_all_and_keeps_exactly_5(expanded):
    retriever, case = expanded
    record = case["sibling_expansion"]
    assert len(record["first_stage"]) == N_CANDIDATES and record["added"]
    assert len(case["candidates"]) == N_CANDIDATES + len(record["added"])            # all reranked
    assert len(case["passages"]) == TOP_K == 5
    by_id = {p.id: p for p in retriever.dense.passages}
    first_articles = {(by_id[i].directive, str(by_id[i].article)) for i in record["first_stage"]}
    for pid in record["added"]:
        assert (by_id[pid].directive, str(by_id[pid].article)) in first_articles and pid not in record["first_stage"]
    for row in case["candidates"]:                                                  # which entered via expansion
        assert row["via_expansion"] == (row["passage_id"] in record["added"])
        assert (row["hybrid_rank"] is None) == row["via_expansion"]
    assert record["top_k_via_expansion"] == [p["passage_id"] for p in case["passages"] if p["via_expansion"]]


def test_expansion_off_same_first_stage_no_siblings(study2_view, expanded):
    _, on = expanded
    fake = CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())
    off = RagV2Retriever(study2_view, reranker=fake).retrieve(SHOP)
    assert "sibling_expansion" not in off and all("via_expansion" not in r for r in off["candidates"])
    assert sorted(r["passage_id"] for r in off["candidates"]) == sorted(on["sibling_expansion"]["first_stage"])
    assert len(off["passages"]) == 5


# ---------- flag OFF reproduces the frozen GDPR development retrieval ----------

def test_expansion_off_reproduces_frozen_gdpr_dev_rerank_file_byte_for_byte():
    """Old GDPR corpus (Chapters I-V) and index; the cross-encoder replays the scores stored in the frozen file, so the
    first stage, the reranking code and the output format are all checked against the committed file."""
    path = project_path(CONFIG["study2_gdpr"]["frozen_dev_rerank_restricted"])
    frozen = json.loads(path.read_text(encoding="utf-8"))
    texts = {p.id: p.text for p in load_passages(project_path(CONFIG["study2_gdpr"]["passages_restricted"]))}
    scores = {(query, texts[c["passage_id"]]): c["rerank_score"] for frozen_case in frozen["cases"].values()
              for query in frozen_case["reranker_queries"] for c in frozen_case["candidates"]}
    fake = CrossEncoderReranker.from_config(CONFIG, model=ReplayModel(scores))
    retriever = RagV2Retriever(CONFIG, reranker=fake)                 # default config: expansion OFF
    assert retriever.sibling_expansion is False
    cases = {case_id: retriever.retrieve_case_reranked(case_id) for case_id in retriever.case_ids}
    assert json.dumps(cases, indent=2, ensure_ascii=False) == json.dumps(frozen["cases"], indent=2, ensure_ascii=False)
    # and it is the same as the unchanged GdprDevFreezer
    parent = GdprDevFreezer(CONFIG, reranker=fake)
    assert cases["01"] == parent.retrieve_case_reranked("01")


# ---------- evaluation counts ----------

def case(top: list[str], candidates: list[str], expanded_ids=()) -> dict:
    rows = [{"rank": i, "passage_id": pid, "via_expansion": pid in expanded_ids} for i, pid in enumerate(candidates, 1)]
    return {"passages": [{"passage_id": pid} for pid in top], "candidates": rows}


def test_evaluation_counts_top5_rank_and_candidates():
    candidates = ["A-1", "A-2", "B-1", "C-1", "D-1", "E-1", "F-1"]
    retrievals = {"01": case(candidates[:5], candidates, expanded_ids={"F-1"}),
                  "01.1": case(["X-1", "X-2", "X-3", "X-4", "X-5"], ["X-1", "X-2", "X-3", "X-4", "X-5"])}
    items = [{"case_id": "01", "targets": ["B-1", "F-1", "Z-9"]}, {"case_id": "01.1", "targets": ["X-5"]}]
    report = evaluate(retrievals, items, top_k=5)
    rows = {(r["case_id"], r["target"]): r for r in report["items"]}
    assert rows[("01", "B-1")] == {"case_id": "01", "target": "B-1", "in_top_k": True, "rank": 3,
                                   "in_candidates": True, "via_expansion": False}
    assert rows[("01", "F-1")] == {"case_id": "01", "target": "F-1", "in_top_k": False, "rank": 7,
                                   "in_candidates": True, "via_expansion": True}
    assert rows[("01", "Z-9")] == {"case_id": "01", "target": "Z-9", "in_top_k": False, "rank": None,
                                   "in_candidates": False, "via_expansion": None}
    assert rows[("01.1", "X-5")]["in_top_k"] is True and rows[("01.1", "X-5")]["rank"] == 5
    assert report["summary"] == {"n_items": 4, "n_in_top_k": 2, "n_in_candidates": 3, "hit_rate_at_5": 0.5}


def test_evaluation_with_expansion_off_has_no_via_expansion():
    retrievals = {"01": {"passages": [{"passage_id": "A-1"}], "candidates": [{"rank": 1, "passage_id": "A-1"}]}}
    report = evaluate(retrievals, [{"case_id": "01", "targets": ["A-1"]}], top_k=5)
    assert report["items"][0]["via_expansion"] is None and report["summary"]["hit_rate_at_5"] == 1.0


# ---------- M2, expected-law share ----------

def test_expected_law_share_per_case_and_mean():
    retrievals = {"01": case(["CRD-Art9-1", "GDPR-Art13-1", "LPD-Art3-1", "ECD-Art10-1", "SGD-Art14-1"], []),
                  "10": case(["GDPR-Art32-1"] * 5, [])}
    m2 = expected_law_share(retrievals, {"01": ["CRD", "ECD", "GDPR"], "10": ["GDPR"]}, ["01", "10"], top_k=5)
    assert m2["per_case"]["01"]["laws"] == ["CRD", "GDPR", "LPD", "ECD", "SGD"]
    assert m2["per_case"]["01"]["share"] == 0.6 and m2["per_case"]["10"]["share"] == 1.0 and m2["mean"] == 0.8
    assert law_of("CRD-Art6a-1-a") == "CRD"


def test_expected_laws_in_config_equal_the_criteria_doc_table():
    doc = project_path("docs/RAG_V2_CRITERIA.md").read_text(encoding="utf-8")
    table = {}
    for line in doc.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].isdigit():
            table[cells[0]] = [law.strip() for law in cells[2].split(",")]
    assert table == CONFIG["rag_v2"]["expected_laws"] and len(table) == 13
