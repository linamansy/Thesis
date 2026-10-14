"""Tests for QueryBuilder, HybridRetriever.search_case and the frozen retrieval."""

import json

import pytest

from src.config import load_config, project_path
from src.freeze_retrieval import RetrievalFreezer, save
from src.retrieval.hybrid_retriever import reciprocal_rank_fusion
from src.retrieval.passage import load_passages
from src.retrieval.query_builder import QueryBuilder

CONFIG = load_config()
FINAL_TOP_K = CONFIG["retrieval"]["final_top_k"]


# ---------- QueryBuilder ----------

def test_queries_are_full_description_then_each_sentence():
    description = "First the order arrives.\r\nThen it is checked.  \r\n"
    assert QueryBuilder().build(description) == [
        "First the order arrives. Then it is checked.", "First the order arrives.", "Then it is checked."]


def test_title_label_removed_but_title_kept_and_empty_lines_skipped():
    description = "Title: Ordering in an Online Shop  \r\n\r\nThe customer   orders.\r\n   \r\n"
    assert QueryBuilder().build(description) == [
        "Ordering in an Online Shop The customer orders.", "Ordering in an Online Shop", "The customer orders."]


def test_duplicate_sentences_become_one_query_and_empty_text_gives_none():
    assert QueryBuilder().build("A happens.\nB happens.\nA happens.") == [
        "A happens. B happens.", "A happens.", "B happens."]
    assert QueryBuilder().build("\n  \n") == []


def test_real_case_with_title():
    description = (project_path(CONFIG["paths"]["cases"]) / "37" / "description.txt").read_text(encoding="utf-8")
    queries = QueryBuilder().build(description)
    assert queries[1] == "Contract"
    assert not any(q.lower().startswith("title") for q in queries)


# ---------- the frozen retrieval ----------

@pytest.fixture(scope="module")
def freezer():
    return RetrievalFreezer(CONFIG)


@pytest.fixture(scope="module")
def frozen(freezer):
    return freezer.freeze()


def test_running_twice_gives_identical_results(frozen):
    again = RetrievalFreezer(CONFIG).freeze()  # a completely new freezer: models and indexes reloaded
    assert again["cases"] == frozen["cases"]
    assert again["reproducibility"] == frozen["reproducibility"]


def test_every_case_has_exactly_five_passages(frozen):
    assert list(frozen["cases"]) == CONFIG["cases"]["ids"]
    for case_id, case in frozen["cases"].items():
        assert len(case["passages"]) == FINAL_TOP_K == 5, case_id
        assert [p["rank"] for p in case["passages"]] == [1, 2, 3, 4, 5]
        ids = [p["passage_id"] for p in case["passages"]]
        assert len(set(ids)) == len(ids), f"duplicate passage in case {case_id}"
        scores = [p["fused_score"] for p in case["passages"]]
        assert scores == sorted(scores, reverse=True)


def test_every_passage_id_exists_in_passages_file(frozen):
    passages = {p.id: p for p in load_passages(project_path(CONFIG["paths"]["passages"]))}
    for case in frozen["cases"].values():
        for p in case["passages"]:
            assert p["passage_id"] in passages
            assert p["text"] == passages[p["passage_id"]].text  # the full, unchanged text is stored


def test_frozen_file_records_config_and_checksum(frozen):
    assert frozen["retrieval_config"]["retrieval"] == CONFIG["retrieval"]
    assert len(frozen["reproducibility"]["passages_sha256"]) == 64
    assert frozen["created_at"].endswith("+00:00")


def test_case_score_is_rrf_summed_over_all_queries(freezer, frozen):
    """Recompute case 01 by hand: two lists per query, all summed."""
    case = frozen["cases"]["01"]
    k, top = CONFIG["retrieval"]["rrf_k"], CONFIG["retrieval"]["top_k_per_retriever"]
    rankings = []
    for query in case["queries"]:
        rankings.append([r.passage.id for r in freezer.dense.search(query, top)])
        rankings.append([r.passage.id for r in freezer.sparse.search(query, top)])
    fused = reciprocal_rank_fusion(rankings, k)
    for p in case["passages"]:
        assert p["fused_score"] == pytest.approx(fused[p["passage_id"]])


def test_existing_file_is_not_overwritten_without_force(tmp_path):
    path = tmp_path / "frozen.json"
    save({"version": 1}, path, force=False)
    with pytest.raises(FileExistsError):
        save({"version": 2}, path, force=False)
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}
    save({"version": 2}, path, force=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 2}
