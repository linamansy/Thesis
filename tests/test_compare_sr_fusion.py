"""Tests for scripts/compare_sr_fusion.py: the four fusion rules on small hand-made step lists. No LLM."""

from scripts.compare_sr_fusion import (cap_per_article, combmax_order, evaluate, fusion_orders, rrf_order)


def row(pid, score):
    return {"passage_id": pid, "rerank_score": score}


LISTS = {"S1": [row("A-Art1-1", 3.0), row("A-Art1-2", 2.0), row("A-Art1-3", 1.0), row("B-Art2-1", 0.5)],
         "S2": [row("A-Art1-1", 2.5), row("A-Art1-2", 1.5), row("A-Art1-3", 1.2)],
         "S3": [row("C-Art3-1", 9.0)]}


def ids(order):
    return [r["passage_id"] for r in order]


def test_rrf_rewards_paragraphs_in_several_lists():
    assert ids(rrf_order(LISTS, 60))[:3] == ["A-Art1-1", "A-Art1-2", "A-Art1-3"]


def test_combmax_uses_the_highest_score_and_breaks_ties_by_rrf():
    assert ids(combmax_order(LISTS, 60))[:2] == ["C-Art3-1", "A-Art1-1"]   # 9.0, then 3.0
    tie = {"S1": [row("X-Art1-1", 1.0), row("X-Art1-2", 0.0)], "S2": [row("Y-Art2-1", 1.0)],
           "S3": [row("X-Art1-1", -5.0), row("Y-Art2-1", 0.0)]}
    # X-Art1-1 and Y-Art2-1 both have max 1.0; X is rank 1 and 1 in S1/S3, Y is rank 1 and 2 in S2/S3: X's RRF is higher
    assert ids(combmax_order(tie, 60))[:2] == ["X-Art1-1", "Y-Art2-1"]


def test_cap_skips_the_third_paragraph_of_an_article_and_keeps_the_order():
    orders = fusion_orders(LISTS, 60)
    assert ids(orders["rrf_cap2"]) == ["A-Art1-1", "A-Art1-2", "C-Art3-1", "B-Art2-1"]
    assert ids(cap_per_article(orders["rrf"], limit=1))[:2] == ["A-Art1-1", "C-Art3-1"]


def test_evaluate_gives_top5_rank_and_pass(monkeypatch):
    order = [{"passage_id": f"A-Art{i}-1"} for i in range(1, 8)]
    monkeypatch.setattr("scripts.compare_sr_fusion.TARGET", "A-Art6-1")
    assert evaluate(order, 5) == {"top5": ids(order)[:5], "rank": 6, "pass": False}
    monkeypatch.setattr("scripts.compare_sr_fusion.TARGET", "A-Art2-1")
    assert evaluate(order, 5)["pass"] and evaluate(order, 5)["rank"] == 2
    monkeypatch.setattr("scripts.compare_sr_fusion.TARGET", "Z-Art9-1")
    assert evaluate(order, 5) == {"top5": ids(order)[:5], "rank": None, "pass": False}
