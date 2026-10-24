"""Tests for the GDPR development retrieval (src/freeze_retrieval_gdpr.py).

The dense model (e5-small-v2) is the locally cached one also used by tests/test_freeze_retrieval.py, and the GDPR
dense index is the committed one (only read). The cross-encoder is replaced by a fake model, so nothing is
downloaded. Nothing is written into data/.
"""

import json
import sys

import pytest

from src.config import load_config, project_path
from src.freeze_retrieval_gdpr import GdprDevFreezer, gdpr_view, main, side_by_side
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]


class ShortFirstModel:
    """Fake cross-encoder: the shorter the passage, the higher the score (same for every query)."""

    def predict(self, pairs, batch_size, show_progress_bar):
        return [-float(len(text)) for _, text in pairs]


def committed(key: str) -> dict:
    return json.loads(project_path(GDPR[key]).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen():
    fake = CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())
    return GdprDevFreezer(CONFIG, reranker=fake).freeze_both()


def test_view_points_to_gdpr_without_changing_the_config():
    view = gdpr_view(CONFIG)
    assert view["paths"]["passages"] == GDPR["passages_restricted"]
    assert view["paths"]["dense_index_dir"] == GDPR["dense_index_dir_restricted"]
    assert view["cases"]["ids"] == GDPR["development_ids"] == ["01", "06", "11", "13", "17", "19", "45"]
    assert CONFIG["paths"]["passages"] == "data/knowledge/passages.jsonl"   # Study 1 untouched
    assert CONFIG["cases"]["ids"] != view["cases"]["ids"]


def test_hybrid_version_reproduces_committed_file(frozen):
    hybrid, _ = frozen
    saved = committed("frozen_dev_hybrid_restricted")
    assert hybrid["cases"] == saved["cases"]
    assert hybrid["reproducibility"] == saved["reproducibility"]
    assert hybrid["reproducibility"]["passages_file"] == GDPR["passages_restricted"]
    assert all(len(case["passages"]) == 5 for case in hybrid["cases"].values())


def test_rerank_version_reorders_the_hybrid_top_20(frozen):
    hybrid, rerank = frozen
    assert list(rerank["cases"]) == GDPR["development_ids"]
    for case_id, case in rerank["cases"].items():
        assert len(case["candidates"]) == CONFIG["reranker"]["candidates"]
        assert case["reranker_queries"] == case["queries"][1:]
        by_hybrid = sorted(case["candidates"], key=lambda c: c["hybrid_rank"])
        assert [c["passage_id"] for c in by_hybrid[:5]] == [p["passage_id"] for p in hybrid["cases"][case_id]["passages"]]
        scores = [c["rerank_score"] for c in case["candidates"]]
        assert scores == sorted(scores, reverse=True)                 # candidates in reranker order
        assert [p["passage_id"] for p in case["passages"]] == [c["passage_id"] for c in case["candidates"][:5]]
        assert all(-p["rerank_score"] == len(p["text"]) for p in case["passages"])   # the fake model's score


def test_both_versions_share_the_header(frozen):
    hybrid, rerank = frozen
    assert hybrid["reproducibility"] == rerank["reproducibility"]
    assert (hybrid["study2"]["version"], rerank["study2"]["version"]) == ("hybrid", "rerank")
    assert hybrid["study2"]["included_chapters"] == ["I", "II", "III", "IV", "V"]
    assert rerank["reranker"]["revision"] == CONFIG["reranker"]["revision"]
    assert "reranker" not in hybrid


def test_committed_rerank_file_is_consistent():
    hybrid, rerank = committed("frozen_dev_hybrid_restricted"), committed("frozen_dev_rerank_restricted")
    assert rerank["reranker"]["model"] == CONFIG["reranker"]["model"]
    assert rerank["reranker"]["revision"] == CONFIG["reranker"]["revision"]
    assert (rerank["reranker"]["settings"]["queries"], rerank["reranker"]["settings"]["aggregation"]) == (
        "sentences", "mean")
    for case_id, case in rerank["cases"].items():
        assert case["reranker_queries"] == case["queries"][1:]
        by_hybrid = sorted(case["candidates"], key=lambda c: c["hybrid_rank"])
        assert [c["passage_id"] for c in by_hybrid[:5]] == [p["passage_id"] for p in hybrid["cases"][case_id]["passages"]]


def test_side_by_side_marks_new_passages():
    hybrid = {"cases": {"01": {"passages": [{"rank": 1, "passage_id": "A"}, {"rank": 2, "passage_id": "B"}]}}}
    rerank = {"cases": {"01": {"passages": [{"rank": 1, "passage_id": "B", "hybrid_rank": 2},
                                            {"rank": 2, "passage_id": "C", "hybrid_rank": 9}]}}}
    lines = side_by_side(hybrid, rerank).splitlines()
    assert lines[1].split() == ["01", "1", "A", "B", "2"]
    assert lines[2].split() == ["01", "2", "B", "C", "9", "*new"]


def test_main_refuses_to_overwrite_existing_files(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["freeze_retrieval_gdpr"])
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        main()
