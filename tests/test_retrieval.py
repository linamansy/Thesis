"""Tests for text processing, DenseRetriever, BM25Retriever and HybridRetriever."""

import faiss
import numpy as np
import pytest

from src.config import load_config, project_path
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.hybrid_retriever import HybridRetriever, reciprocal_rank_fusion
from src.retrieval.passage import load_passages
from src.retrieval.sparse_retriever import BM25Retriever
from src.retrieval.text_processing import load_stopwords, normalise, tokenize

CONFIG = load_config()
SETTINGS = CONFIG["retrieval"]
WITHDRAWAL_QUERY = "right of withdrawal within 14 days"
LATE_PAYMENT_QUERY = "interest for late payment between businesses"


@pytest.fixture(scope="module")
def passages():
    return load_passages(project_path(CONFIG["paths"]["passages"]))


@pytest.fixture(scope="module")
def dense(passages):
    return DenseRetriever.from_config(CONFIG, passages)


@pytest.fixture(scope="module")
def sparse(passages):
    return BM25Retriever.from_config(CONFIG, passages)


@pytest.fixture(scope="module")
def hybrid(dense, sparse):
    return HybridRetriever.from_config(CONFIG, dense, sparse)


def ids(results):
    return [r.passage.id for r in results]


# ---------- text processing ----------

def test_normalise_lowercases_and_removes_punctuation():
    assert normalise("The Trader's ‘Goods’, Directive 2011/83/EU!").split() == \
        ["the", "trader", "s", "goods", "directive", "2011", "83", "eu"]


def test_tokenize_removes_stopwords_and_stems():
    stopwords = load_stopwords(SETTINGS["stopwords_language"], project_path(CONFIG["paths"]["nltk_data"]))
    assert {"the", "of", "for", "between"} <= stopwords
    assert tokenize("The right of withdrawal for consumers", stopwords) == ["right", "withdraw", "consum"]


# ---------- the same query always gives the same result ----------

@pytest.mark.parametrize("query", [WITHDRAWAL_QUERY, LATE_PAYMENT_QUERY])
def test_same_query_same_result(hybrid, query):
    first, second = hybrid.search(query), hybrid.search(query)
    assert [(r.passage.id, r.score) for r in first] == [(r.passage.id, r.score) for r in second]


def test_rebuilt_index_gives_same_result(passages, dense, sparse, tmp_path):
    """Building the dense index from scratch gives the same results as the saved index."""
    rebuilt = DenseRetriever(passages, SETTINGS["dense_model"], SETTINGS["passage_prefix"],
                             SETTINGS["query_prefix"], tmp_path / "index")
    assert (tmp_path / "index" / "index.faiss").exists()
    assert ids(rebuilt.search(WITHDRAWAL_QUERY, 20)) == ids(dense.search(WITHDRAWAL_QUERY, 20))
    again = HybridRetriever.from_config(CONFIG, rebuilt, BM25Retriever.from_config(CONFIG, passages))
    assert ids(again.search(LATE_PAYMENT_QUERY)) == ids(HybridRetriever.from_config(CONFIG, dense, sparse)
                                                       .search(LATE_PAYMENT_QUERY))


# ---------- the expected passages are found ----------

def test_withdrawal_query_finds_crd_article_9(hybrid):
    top3 = ids(hybrid.search(WITHDRAWAL_QUERY, top_n=3))
    assert any(pid.startswith("CRD-Art9-") for pid in top3), top3


def test_late_payment_query_finds_lpd(hybrid):
    top3 = ids(hybrid.search(LATE_PAYMENT_QUERY, top_n=3))
    assert top3[0].startswith("LPD-"), top3


# ---------- dense retriever ----------

def test_dense_index_is_flat_inner_product_with_normalised_vectors(dense, passages):
    assert isinstance(dense.index, faiss.IndexFlatIP)
    assert dense.index.ntotal == len(passages)
    vectors = dense.index.reconstruct_n(0, dense.index.ntotal)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_dense_scores_are_sorted_cosine_similarities(dense):
    results = dense.search(WITHDRAWAL_QUERY, 20)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0 <= s <= 1.0 for s in scores)
    assert [r.rank for r in results] == list(range(1, 21))


def test_dense_uses_query_prefix(dense):
    """The search score equals the cosine of the PREFIXED query with the passage vector."""
    top = dense.search(WITHDRAWAL_QUERY, 1)[0]
    query_vector = dense.embed([SETTINGS["query_prefix"] + WITHDRAWAL_QUERY])[0]
    passage_vector = dense.index.reconstruct(dense.passages.index(top.passage))
    assert float(query_vector @ passage_vector) == pytest.approx(top.score, abs=1e-5)


# ---------- BM25 retriever ----------

def test_bm25_uses_configured_parameters(sparse):
    assert (sparse.bm25.k1, sparse.bm25.b) == (SETTINGS["bm25_k1"], SETTINGS["bm25_b"])


def test_bm25_returns_only_matching_passages(sparse):
    assert sparse.search("the of and", 20) == []          # only stopwords: nothing matches
    results = sparse.search(LATE_PAYMENT_QUERY, 20)
    assert len(results) == 20 and all(r.score > 0 for r in results)


# ---------- fusion ----------

def test_reciprocal_rank_fusion_formula():
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_hybrid_scores_match_ranks(hybrid):
    k = SETTINGS["rrf_k"]
    results = hybrid.search(WITHDRAWAL_QUERY)
    assert len(results) <= 2 * SETTINGS["top_k_per_retriever"]
    for r in results:
        expected = sum(1 / (k + rank) for rank in (r.dense_rank, r.sparse_rank) if rank is not None)
        assert r.score == pytest.approx(expected)
    assert [r.score for r in results] == sorted((r.score for r in results), reverse=True)
