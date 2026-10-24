"""Tests for CrossEncoderReranker with a fake model (no model is loaded or downloaded)."""

import pytest

from src.config import load_config
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult

CONFIG = load_config()


class FakeCrossEncoder:
    """Scores a (query, passage text) pair from a table; remembers every pair it was asked about."""

    def __init__(self, table: dict[tuple[str, str], float]):
        self.table = table
        self.calls = []

    def predict(self, pairs, batch_size, show_progress_bar):
        self.calls.append(list(pairs))
        return [self.table[pair] for pair in pairs]


def candidate(pid: str, rank: int) -> SearchResult:
    return SearchResult(passage=Passage(id=pid, directive="2016/679", article=1, paragraph=1, title="t",
                                        text=f"text {pid}", n_chars=7), score=1.0 / rank, rank=rank)


def reranker(table, aggregation="mean", queries="sentences") -> CrossEncoderReranker:
    return CrossEncoderReranker("fake-model", "rev1", 512, 32, aggregation, queries, model=FakeCrossEncoder(table))


QUERIES = ["FULL", "s1", "s2"]   # QueryBuilder order: full description, then each sentence
CANDIDATES = [candidate("A", 1), candidate("B", 2), candidate("C", 3)]
TABLE = {
    ("FULL", "text A"): 9.0, ("s1", "text A"): 0.0, ("s2", "text A"): 0.0,   # high only for the full description
    ("FULL", "text B"): 1.0, ("s1", "text B"): 2.0, ("s2", "text B"): 4.0,   # mean 3
    ("FULL", "text C"): 1.0, ("s1", "text C"): 5.0, ("s2", "text C"): 0.0,   # mean 2.5, max 5
}


def test_sentence_queries_leave_out_the_full_description():
    r = reranker(TABLE)
    assert r.select_queries(QUERIES) == ["s1", "s2"]
    r.score(QUERIES, CANDIDATES)
    assert all(query != "FULL" for query, _ in r.model.calls[0])


def test_one_line_description_uses_its_only_query():
    assert reranker(TABLE).select_queries(["only sentence"]) == ["only sentence"]
    assert reranker(TABLE, queries="all").select_queries(QUERIES) == QUERIES


def test_mean_over_sentences_orders_candidates():
    result = reranker(TABLE).rerank(QUERIES, CANDIDATES, top_k=3)
    assert [(r.passage.id, r.rank, r.score) for r in result] == [("B", 1, 3.0), ("C", 2, 2.5), ("A", 3, 0.0)]


def test_max_and_all_queries_is_dominated_by_full_description():
    result = reranker(TABLE, aggregation="max", queries="all").rerank(QUERIES, CANDIDATES, top_k=1)
    assert [r.passage.id for r in result] == ["A"]   # the problem that led to "sentences" + "mean"


def test_top_k_ties_and_empty_input():
    tied = {(q, f"text {p}"): 1.0 for q in QUERIES for p in "ABC"}
    assert [r.passage.id for r in reranker(tied).rerank(QUERIES, list(reversed(CANDIDATES)), top_k=2)] == ["A", "B"]
    assert reranker(TABLE).rerank([], CANDIDATES, top_k=5) == []
    assert reranker(TABLE).rerank(QUERIES, [], top_k=5) == []


def test_unknown_settings_are_refused():
    with pytest.raises(ValueError, match="aggregation"):
        reranker(TABLE, aggregation="median")
    with pytest.raises(ValueError, match="query set"):
        reranker(TABLE, queries="full")


def test_from_config_uses_config_settings_and_is_off_by_default():
    r = CrossEncoderReranker.from_config(CONFIG, model=FakeCrossEncoder({}))
    settings = CONFIG["reranker"]
    assert (r.model_name, r.revision, r.aggregation, r.queries) == (
        "cross-encoder/ms-marco-MiniLM-L-6-v2", settings["revision"], "mean", "sentences")
    assert settings["enabled"] is False
    assert (settings["candidates"], settings["top_k"]) == (20, CONFIG["retrieval"]["final_top_k"])
