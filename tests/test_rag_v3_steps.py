"""Tests for RAG step routing (SR): src/rag_v3_steps.py and scripts/debug_rag_v3_steps.py.
Mock LLM answers and fake retrievers only: no Ollama, no embedding or reranker model."""

import json
import re

from scripts.debug_rag_v3_steps import check_rules, next_run_dir, run_once, summary_text
from src.config import load_config
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.rag_v3_steps import (RoutingAgent, StepRouter, StepsAgent, article_id_of, article_index, article_lines,
                              articles_text, first_sentence,
                              check_routes, check_steps, expand, merge_rankings, step_query)
from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult

CONFIG = load_config()
DESCRIPTION = "The sales staff write down the customer's email address. The shop sends the product to the customer."


def passage(pid, title="T"):
    return Passage(id=pid, directive="d", article=0, paragraph=0, title=title, text=f"text of {pid}", n_chars=10)


PASSAGES = [passage("GDPR-Art13-1", "Information to be provided"), passage("GDPR-Art13-2", "Information to be provided"),
            passage("GDPR-Art5-1-a", "Principles"), passage("CRD-Art8-3", "Distance contracts"),
            passage("CRD-Art9-1", "Withdrawal")]
STEP1 = {"step_id": "S1", "actor": "sales staff", "activity": "write down the email address",
         "data_or_object": "email address", "quote": "The sales staff write down the customer's email address"}
STEP2 = {"step_id": "S2", "actor": "shop", "activity": "send the product", "data_or_object": "product",
         "quote": "The shop sends the product to the customer"}


class FakeRetriever:
    """Returns every passage in a fixed order (like a search with k = whole corpus)."""

    def __init__(self, order):
        self.order = order

    def search(self, query, k):
        by_id = {p.id: p for p in PASSAGES}
        return [SearchResult(passage=by_id[pid], score=1.0, rank=i) for i, pid in enumerate(self.order[:k], 1)]


class FakeReranker:
    """Scores a passage by its position in a fixed preference list; records the queries it was given."""

    def __init__(self, prefer):
        self.prefer, self.queries = prefer, []

    def rerank(self, queries, candidates, top_k):
        self.queries.append(queries)
        scores = {c.passage.id: -self.prefer.index(c.passage.id) for c in candidates}
        order = sorted(scores, key=lambda pid: (-scores[pid], pid))[:top_k]
        by_id = {c.passage.id: c for c in candidates}
        return [SearchResult(passage=by_id[pid].passage, score=scores[pid], rank=i) for i, pid in enumerate(order, 1)]


def router(tmp_path, answers, reranker=None, name="a"):
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "SR", name)
    order = [p.id for p in PASSAGES]
    reranker = reranker or FakeReranker(order)
    return StepRouter(CONFIG, StepsAgent(llm, log), RoutingAgent(llm, log), PASSAGES, FakeRetriever(order),
                      FakeRetriever(order[::-1]), reranker), llm


# ---------- corpus helpers ----------

def test_article_ids_and_index_come_from_the_passages_only():
    assert article_id_of("GDPR-Art13-1") == "GDPR-Art13" and article_id_of("GDPR-Art5-1-a") == "GDPR-Art5"
    index = article_index(PASSAGES)
    assert list(index) == ["GDPR-Art13", "GDPR-Art5", "CRD-Art8", "CRD-Art9"]
    assert articles_text(index).splitlines()[0] == "GDPR-Art13: Information to be provided"


def test_real_corpus_article_list_has_every_article_once():
    from src.config import project_path
    from src.retrieval.passage import load_passages
    passages = load_passages(project_path(CONFIG["study2_corpus"]["passages"]))
    index = article_index(passages)
    assert "GDPR-Art13" in index and len(index) == len({article_id_of(p.id) for p in passages})
    assert list(article_lines(passages)) == list(index)


def law_passage(pid, text, title="Delivery"):
    return Passage(id=pid, directive="d", article=1, paragraph=1, title=title, text=text, n_chars=len(text))


def test_article_line_is_law_name_title_and_first_sentence_from_the_corpus():
    first = law_passage("ABC-Art2-1", "Made-up Directive (1/2) - Article 2: Delivery\n1. The shop shall deliver the "
                                      "goods.\nIt shall do so on time. Second sentence.")
    second = law_passage("ABC-Art2-2", "Made-up Directive (1/2) - Article 2: Delivery\n2. Not the first paragraph.")
    assert article_lines([first, second]) == {
        "ABC-Art2": "Made-up Directive (1/2) – Delivery – The shop shall deliver the goods."}


def test_first_sentence_is_cut_at_40_words():
    long = law_passage("ABC-Art3-1", "Made-up Directive (1/2) - Article 3: Delivery\n" + " ".join(["word"] * 60) + ".")
    assert first_sentence(long) == " ".join(["word"] * 40) + " ..."
    assert first_sentence(law_passage("ABC-Art4-1", "Header\n(a) free of charge; (b) on time.")) == \
        "(a) free of charge; (b) on time."


# ---------- S1 / S2 checks ----------

def test_steps_with_a_missing_quote_are_dropped_and_logged():
    bad = dict(STEP2, quote="The shop dispatches the goods by courier")
    kept, dropped = check_steps([STEP1, bad], DESCRIPTION)
    assert [s["step_id"] for s in kept] == ["S1"]
    assert dropped[0]["step_id"] == "S2" and dropped[0]["dropped_because"] == "quote not found in the description"


def test_unknown_and_repeated_article_ids_are_dropped():
    index = article_index(PASSAGES)
    routes = [{"article_id": "GDPR-Art13", "reason": "r"}, {"article_id": "GDPR-Art99", "reason": "r"},
              {"article_id": "GDPR-Art13", "reason": "again"}]
    kept, dropped = check_routes(routes, index)
    assert [r["article_id"] for r in kept] == ["GDPR-Art13"] and kept[0]["title"] == "Information to be provided"
    assert [d["dropped_because"] for d in dropped] == ["article id not in the corpus", "repeated article id"]


def test_step_query_is_activity_plus_data_or_object():
    assert step_query(STEP1) == "write down the email address email address"
    assert step_query(dict(STEP1, data_or_object="")) == "write down the email address"


def test_routing_prompt_lists_all_articles_and_no_hint(tmp_path):
    r, llm = router(tmp_path, [{"steps": [STEP1]}, {"routes": []}])
    r.run("c", DESCRIPTION)
    prompt = llm.prompts_received[1]
    for article in ("GDPR-Art13", "GDPR-Art5", "CRD-Art8", "CRD-Art9"):
        assert article in prompt
    assert "GDPR-Art13: text of GDPR-Art13-1 – Information to be provided – text of GDPR-Art13-1" in prompt
    assert "data protection" not in prompt.lower() and "personal data" not in prompt.lower()


def test_more_than_three_routes_are_refused_and_retried(tmp_path):
    four = {"routes": [{"article_id": f"CRD-Art{i}", "reason": "r"} for i in range(4)]}
    r, llm = router(tmp_path, [{"steps": [STEP1]}, four, {"routes": [{"article_id": "GDPR-Art13", "reason": "r"}]}])
    s2 = r.run("c", DESCRIPTION)["S2"]
    assert [x["article_id"] for x in s2["per_step"]["S1"]["routes"]] == ["GDPR-Art13"]


# ---------- S3 / S4 ----------

def test_s3_keeps_only_routed_articles_and_reranks_with_the_step_text(tmp_path):
    reranker = FakeReranker(["GDPR-Art13-2", "GDPR-Art13-1", "CRD-Art8-3", "CRD-Art9-1", "GDPR-Art5-1-a"])
    r, _ = router(tmp_path, [{"steps": [STEP1]}, {"routes": [{"article_id": "GDPR-Art13", "reason": "r"}]}], reranker)
    out = r.run("c", DESCRIPTION)
    ranking = out["S3"]["per_step"]["S1"]["ranking"]
    assert [x["passage_id"] for x in ranking] == ["GDPR-Art13-2", "GDPR-Art13-1"]   # no other article
    assert reranker.queries == [["write down the email address email address"]]
    assert out["S3"]["per_step"]["S1"]["n_paragraphs_in_routed_articles"] == 2


def test_step_without_a_valid_route_is_skipped(tmp_path):
    r, _ = router(tmp_path, [{"steps": [STEP1]}, {"routes": [{"article_id": "XYZ-Art1", "reason": "r"}]}])
    out = r.run("c", DESCRIPTION)
    assert out["S3"]["steps_without_route"] == ["S1"] and out["S4"]["passages"] == []


def test_merge_is_rrf_with_k_60_over_the_step_lists():
    top = merge_rankings({"S1": ["A", "B", "C"], "S2": ["B", "C", "D"]}, 60, 3)
    assert [t["passage_id"] for t in top] == ["B", "C", "A"]
    assert abs(top[0]["rrf_score"] - (1 / 62 + 1 / 61)) < 1e-12
    assert top[0]["rank_in_steps"] == {"S1": 2, "S2": 1}
    assert CONFIG["retrieval"]["rrf_k"] == 60


# ---------- pass rules and the debug run ----------

def two_step_answers(route2):
    return [{"steps": [STEP1, STEP2]}, {"routes": [{"article_id": "GDPR-Art13", "reason": "contact data"}]},
            {"routes": [{"article_id": route2, "reason": "delivery"}]}]


def test_rules_pass_when_art13_is_routed_and_art13_1_is_in_the_top_5(tmp_path):
    r, _ = router(tmp_path, two_step_answers("CRD-Art9"))
    rules = check_rules(r.run("c", DESCRIPTION), 60)
    assert rules["rule_a_pass"] and rules["rule_a_steps"] == ["S1"] and rules["rule_b_pass"] and rules["pass"]
    assert rules["rank_in_s3_per_step"]["S1"] == 1 and rules["rank_in_s3_per_step"]["S2"] is None
    assert rules["rank_in_s4_full_merge"] == 2   # ties with CRD-Art9-1 (rank 1 in S2's list); tie broken by passage id


def test_rules_fail_when_art13_is_not_routed(tmp_path):
    answers = [{"steps": [STEP1]}, {"routes": [{"article_id": "CRD-Art8", "reason": "r"}]}]
    r, _ = router(tmp_path, answers)
    rules = check_rules(r.run("c", DESCRIPTION), 60)
    assert not rules["rule_a_pass"] and not rules["rule_b_pass"] and not rules["pass"]
    assert rules["rank_in_s4_full_merge"] is None


def test_run_once_writes_every_file_and_the_model_is_recorded(tmp_path):
    key = {"target_passage_id": "GDPR-Art13-1"}
    info = {"model": "qwen3:8b", "model_digest": "abc"}
    counter = iter("abc")

    def factory(logger):
        r, _ = router(tmp_path / "unused", two_step_answers("CRD-Art9"), name=next(counter))
        r.steps_agent.logger = r.routing_agent.logger = logger
        return r

    run = run_once(CONFIG, factory, DESCRIPTION, key, tmp_path / "rag_sr_run_1", info)
    names = sorted(p.name for p in (tmp_path / "rag_sr_run_1").glob("*.json"))
    assert names == ["00_run_info.json", "01_steps.json", "02_routes.json", "03_step_rankings.json",
                     "04_merged_top5.json", "05_pass_rules.json"]
    written = json.loads((tmp_path / "rag_sr_run_1" / "00_run_info.json").read_text(encoding="utf-8"))
    assert written["model"] == "qwen3:8b" and written["model_digest"] == "abc" and "pass_rules" in written
    text = summary_text([run], {"target_passage_id": "GDPR-Art13-1"})
    assert "Rule (a) PASS" in text and "Rule (b) PASS" in text and "S2 routes per step" in text
    assert re.search(r"GDPR-Art13-1 per step list: S1=1, S2=-", text)


def test_run_folders_are_numbered_and_never_reused(tmp_path):
    assert next_run_dir(tmp_path).name == "rag_sr_run_1"
    (tmp_path / "rag_sr_run_1").mkdir()
    (tmp_path / "rag_sr_run_4").mkdir()
    (tmp_path / "run_9").mkdir()   # the other debug runner's folders do not count
    assert next_run_dir(tmp_path).name == "rag_sr_run_5"


# ---------- options: two_view, fusion="combmax", parent_expansion (defaults = the original SR) ----------

def test_defaults_keep_the_original_sr(tmp_path):
    r, llm = router(tmp_path, two_step_answers("CRD-Art9"))
    assert (r.two_view, r.fusion, r.parent_expansion) == (False, "rrf", False)
    out = r.run("c", DESCRIPTION)
    assert len(llm.prompts_received) == 3   # S1 + one routing call per step
    assert set(out["S4"]) == {"stage", "rrf_k", "top_k", "passages"} and out["S4"]["top_k"] == 5
    assert set(out["S2"]["per_step"]["S1"]) == {"failed", "raw_routes", "routes", "dropped"}


def test_unknown_fusion_is_refused():
    import pytest
    with pytest.raises(ValueError):
        StepRouter(CONFIG, None, None, PASSAGES, None, None, None, fusion="combsum")


def test_two_view_routes_with_both_lists_and_takes_the_union(tmp_path):
    answers = [{"steps": [STEP1]},
               {"routes": [{"article_id": "GDPR-Art13", "reason": "title view"}]},
               {"routes": [{"article_id": "CRD-Art8", "reason": "f1"}, {"article_id": "GDPR-Art13", "reason": "f1"},
                           {"article_id": "XYZ-Art1", "reason": "f1"}]}]
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "SR", "tv")
    order = [p.id for p in PASSAGES]
    r = StepRouter(CONFIG, StepsAgent(llm, log), RoutingAgent(llm, log), PASSAGES, FakeRetriever(order),
                   FakeRetriever(order[::-1]), FakeReranker(order), two_view=True)
    out = r.run("c", DESCRIPTION)
    title_prompt, f1_prompt = llm.prompts_received[1], llm.prompts_received[2]
    assert "GDPR-Art13: Information to be provided\n" in title_prompt and "text of GDPR-Art13-1" not in title_prompt
    assert "GDPR-Art13: text of GDPR-Art13-1 – Information to be provided" in f1_prompt
    s1 = out["S2"]["per_step"]["S1"]
    assert [(x["article_id"], x["views"]) for x in s1["routes"]] == [
        ("GDPR-Art13", ["title", "law_title_sentence"]), ("CRD-Art8", ["law_title_sentence"])]
    assert s1["routes"][0]["reason"] == "title view"   # a repeated id keeps its first route
    assert s1["dropped"] == [{"article_id": "XYZ-Art1", "reason": "f1", "dropped_because": "article id not in the corpus",
                              "view": "law_title_sentence"}]
    assert set(s1["views"]) == {"title", "law_title_sentence"} and not s1["failed"]
    assert out["S3"]["per_step"]["S1"]["routed_articles"] == ["GDPR-Art13", "CRD-Art8"]   # S3 searches the union


def numbered_passages(n_articles, per_article):
    return [passage(f"L-Art{a}-{p}") for a in range(1, n_articles + 1) for p in range(1, per_article + 1)]


def s3_of(lists):
    return {"per_step": {s: {"ranking": [{"passage_id": pid, "rerank_score": score} for pid, score in rows]}
                         for s, rows in lists.items()}}


def test_combmax_keeps_the_top_10_by_highest_reranker_score():
    passages = numbered_passages(12, 1)
    r = StepRouter(CONFIG, None, None, passages, None, None, None, fusion="combmax")
    s3 = s3_of({"S1": [(f"L-Art{i}-1", float(i)) for i in range(1, 13)],
                "S2": [("L-Art1-1", 50.0)]})
    s4 = r.merge_with_options(s3, {p.id: p.text for p in passages})
    ids = [row["passage_id"] for row in s4["passages"]]
    assert len(ids) == 10 and ids[0] == "L-Art1-1"   # its max (50) over S1 and S2 wins
    assert ids[1:] == [f"L-Art{i}-1" for i in range(12, 3, -1)]
    assert s4["fusion"] == "combmax" and s4["top_k"] == 10 and s4["passages"][0]["text"] == "text of L-Art1-1"
    assert [row["rank"] for row in s4["passages"]] == list(range(1, 11))


def test_expand_orders_articles_by_their_best_paragraph_and_cuts_at_20():
    corpus = [p.id for p in numbered_passages(3, 9)]
    out = expand(["L-Art3-5", "L-Art1-2", "L-Art3-1"], corpus)
    assert out["articles"] == ["L-Art3", "L-Art1"]
    assert out["passages"] == [f"L-Art3-{i}" for i in range(1, 10)] + [f"L-Art1-{i}" for i in range(1, 10)]
    out = expand(["L-Art2-1", "L-Art3-1", "L-Art1-1"], corpus)
    assert len(out["passages"]) == 20 and out["cut"] == [f"L-Art1-{i}" for i in range(3, 10)]


def test_parent_expansion_replaces_the_fused_list_by_all_paragraphs_of_its_articles():
    passages = numbered_passages(3, 3)
    r = StepRouter(CONFIG, None, None, passages, None, None, None, fusion="combmax", parent_expansion=True)
    s4 = r.merge_with_options(s3_of({"S1": [("L-Art2-3", 5.0), ("L-Art1-1", 4.0)]}), {p.id: p.text for p in passages})
    assert [row["passage_id"] for row in s4["fused"]] == ["L-Art2-3", "L-Art1-1"]
    assert s4["articles"] == ["L-Art2", "L-Art1"] and s4["cut"] == []
    assert [(row["passage_id"], row["fused_rank"]) for row in s4["passages"]] == [
        ("L-Art2-1", None), ("L-Art2-2", None), ("L-Art2-3", 1), ("L-Art1-1", 2), ("L-Art1-2", None), ("L-Art1-3", None)]
    assert s4["passages"][0]["text"] == "text of L-Art2-1"


def test_all_options_together_in_a_run_and_rule_b_checks_the_final_set(tmp_path):
    answers = [{"steps": [STEP1]}, {"routes": [{"article_id": "GDPR-Art5", "reason": "r"}]},
               {"routes": [{"article_id": "GDPR-Art13", "reason": "r"}]}]
    counter = iter("xyz")

    def factory(logger):
        llm = MockLLM([json.dumps(a) for a in answers])
        order = [p.id for p in PASSAGES]
        reranker = FakeReranker(["GDPR-Art13-2", "GDPR-Art5-1-a", "GDPR-Art13-1"])
        return StepRouter(CONFIG, StepsAgent(llm, logger), RoutingAgent(llm, logger), PASSAGES, FakeRetriever(order),
                          FakeRetriever(order[::-1]), reranker, two_view=True, fusion="combmax", parent_expansion=True)

    run = run_once(CONFIG, factory, DESCRIPTION, {"target_passage_id": "GDPR-Art13-1"}, tmp_path / "rag_sr_run_1", {})
    s4 = run["stages"]["S4"]
    assert [row["passage_id"] for row in s4["passages"]] == ["GDPR-Art13-1", "GDPR-Art13-2", "GDPR-Art5-1-a"]
    assert run["rules"]["rule_b_pass"] and run["rules"]["s4_top5"] == [row["passage_id"] for row in s4["passages"]]
    info = json.loads((tmp_path / "rag_sr_run_1" / "00_run_info.json").read_text(encoding="utf-8"))
    assert info["pass_rules"]["(b)"] == "GDPR-Art13-1 in the final S4 set"
