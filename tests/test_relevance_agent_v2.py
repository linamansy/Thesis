"""Tests for RelevanceAgent v2, its code check and the development test runner (MockLLM answers only, no Ollama).

v1 (prompts/relevance_prompt.txt, src/agents/relevance_agent.py) must stay unchanged: tests/test_c3_frozen.py checks
its hashes; here we check that v2 is a separate file and class.
"""

import copy
import itertools
import json

import pytest

from src.agents.relevance_agent import RelevanceAgent
from src.agents.relevance_agent_v2 import RelevanceAgentV2, RelevanceOutputV2
from src.c3_version import changed_items
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.relevance_v2_checker import RelevanceV2Checker
from src.relevance_v2_dev import (RelevanceV2Dev, criteria_result, law_metrics, law_setup, quote_metrics)

CONFIG = load_config()
DESCRIPTION = "The customer chooses a product. The customer pays by card. The shop sends the product."
PASSAGE = "If a customer pays by card, the shop must give a receipt."

REAL = {"law_focus": "card payments by customers", "law_quote": "If a customer pays by card", "relevant": True,
        "process_step": "the customer pays by card", "description_quote": "The customer pays by card",
        "reason": "The process has a card payment step."}
FAKE_DESCRIPTION_QUOTE = dict(REAL, description_quote="The customer pays in cash")
FAKE_LAW_QUOTE = dict(REAL, law_quote="the shop must refund the customer")
EMPTY_STEP = dict(REAL, relevant=False, process_step="", description_quote="", reason="No step does this.")


RUN_IDS = itertools.count()   # every agent gets its own log file (RunLogger never writes into an existing one)


def agent(tmp_path, answers) -> RelevanceAgentV2:
    return RelevanceAgentV2(MockLLM([json.dumps(a) if isinstance(a, dict) else a for a in answers]),
                            RunLogger(tmp_path, "RELEVANCE_V2", f"t{next(RUN_IDS)}"))


def run_and_check(tmp_path, answer) -> dict:
    output = agent(tmp_path, [answer]).run("x", description=DESCRIPTION, passage_id="P-1", passage_text=PASSAGE)
    return RelevanceV2Checker().check(output, PASSAGE, DESCRIPTION)


# ---------- agent and code check ----------

def test_real_quotes_give_relevant(tmp_path):
    result = run_and_check(tmp_path, REAL)
    assert (result["law_quote_found"], result["description_quote_found"], result["final_relevant"]) == (True, True, True)


def test_fake_description_quote_gives_irrelevant(tmp_path):
    result = run_and_check(tmp_path, FAKE_DESCRIPTION_QUOTE)
    assert result["relevant"] is True                     # the model's answer is kept
    assert (result["law_quote_found"], result["description_quote_found"], result["final_relevant"]) == (True, False, False)


def test_fake_law_quote_gives_irrelevant(tmp_path):
    result = run_and_check(tmp_path, FAKE_LAW_QUOTE)
    assert (result["law_quote_found"], result["final_relevant"]) == (False, False)


def test_empty_step_gives_irrelevant(tmp_path):
    result = run_and_check(tmp_path, EMPTY_STEP)
    assert (result["description_quote_found"], result["final_relevant"]) == (None, False)
    assert run_and_check(tmp_path, dict(EMPTY_STEP, relevant=True))["final_relevant"] is False   # true but no step


def test_quote_matching_is_quotechecker_matching(tmp_path):
    loose = dict(REAL, description_quote="the CUSTOMER pays, by card")   # case and punctuation are ignored
    assert run_and_check(tmp_path, loose)["description_quote_found"] is True
    partial_word = dict(REAL, description_quote="customer pay")          # whole words only
    assert run_and_check(tmp_path, partial_word)["description_quote_found"] is False


def test_one_retry_after_invalid_json(tmp_path):
    a = agent(tmp_path, ["not json", REAL])
    assert a.run("x", description=DESCRIPTION, passage_id="P-1", passage_text=PASSAGE) == RelevanceOutputV2(**REAL)
    assert agent(tmp_path, ["not json", "still not"]).run("x", description=DESCRIPTION, passage_id="P-1",
                                                          passage_text=PASSAGE) is None


def test_prompt_is_general_and_v1_is_unchanged(tmp_path):
    prompt = agent(tmp_path, [REAL]).build_prompt(description=DESCRIPTION, passage_id="P-1", passage_text=PASSAGE)
    assert "[P-1] If a customer pays by card" in prompt and DESCRIPTION in prompt
    lowered = project_path(CONFIG["paths"]["relevance_prompt_v2"]).read_text(encoding="utf-8").lower()
    for word in ("gdpr", "personal data", "consumer", "directive", "regulation", "data protection", "delivery"):
        assert word not in lowered, word
    assert CONFIG["paths"]["relevance_prompt"] == "prompts/relevance_prompt.txt"
    assert RelevanceAgent.prompt_key == "relevance_prompt" and RelevanceAgentV2.prompt_key == "relevance_prompt_v2"
    assert changed_items(CONFIG) == []                    # C3 v1 still identical to the frozen hashes


# ---------- metrics and criteria ----------

def record(silver, v2, v1=False, law_found=True, desc_found=True, valid=True) -> dict:
    v2_answer = {"law_quote_found": law_found, "description_quote_found": desc_found} if valid else None
    return {"silver_label": silver, "v2_relevant": v2, "v1_relevant": v1, "valid_json": valid, "v2": v2_answer}


def test_law_metrics_counts_recall_and_specificity():
    records = [record("indeterminate", True), record("applicable", False), record("not_applicable", True),
               record("irrelevant", True), record("irrelevant", False)]
    m = law_metrics(records, "v2_relevant")
    assert (m["silver_relevant_found"], m["n_silver_relevant"], m["recall"]) == (2, 3, 0.6667)
    assert (m["silver_irrelevant_called_relevant"], m["n_silver_irrelevant"], m["specificity"]) == (1, 2, 0.5)
    assert m["table"]["applicable"] == {"relevant": 0, "irrelevant": 1}


def test_quote_metrics_skip_empty_quotes_and_count_invalid_json():
    records = [record("irrelevant", False, desc_found=None), record("indeterminate", False, law_found=False),
               record("indeterminate", False, valid=False)]
    q = quote_metrics(records)
    assert (q["quotes_checked"], q["quotes_failed"], q["law_quotes_failed"]) == (3, 1, 1)
    assert (q["valid_json"], q["answers"], q["stability"]) == (2, 3, 0.6667)


def test_criteria_need_both_laws():
    good = {"v2": {"recall": 0.8, "specificity": 0.6}}
    bad = {"v2": {"recall": 0.9, "specificity": 0.4}}
    overall = {"evidence": 0.95, "stability": 1.0}
    criteria = CONFIG["c3_v2_dev"]["criteria"]
    result = criteria_result({"consumer_law": good, "gdpr": bad}, overall, criteria)
    assert result["1_recall_gdpr"] and not result["2_specificity_gdpr"] and not result["3_generality"]
    assert criteria_result({"consumer_law": good, "gdpr": good}, overall, criteria)["3_generality"]
    assert criteria == {"recall": 0.70, "specificity": 0.50, "evidence": 0.90, "stability": 0.95}


# ---------- development setup and mock run ----------

def test_law_setup_uses_development_cases_and_the_right_silver():
    consumer, gdpr = law_setup(CONFIG, "consumer_law"), law_setup(CONFIG, "gdpr")
    assert consumer["case_ids"] == CONFIG["cases"]["development_ids"] and len(consumer["silver"]) == 65
    assert gdpr["case_ids"] == CONFIG["study2_gdpr"]["development_ids"] and len(gdpr["silver"]) == 35
    assert sorted(set(gdpr["silver"].values())) == ["applicable", "indeterminate", "irrelevant", "not_applicable"]
    config = copy.deepcopy(CONFIG)
    config["cases"]["test_ids"] = ["06"]
    with pytest.raises(ValueError, match="test cases"):
        law_setup(config, "gdpr")


def test_mock_run_writes_only_its_round_folder(tmp_path):
    config = copy.deepcopy(CONFIG)
    config["paths"]["relevance_v2_dev_dir"] = str(tmp_path / "dev")
    metrics = RelevanceV2Dev(config, 1, MockLLM([json.dumps(EMPTY_STEP)])).run()
    out = tmp_path / "dev" / "round1"
    assert sorted(p.name for p in out.iterdir()) == ["answers_consumer_law.json", "answers_gdpr.json", "logs",
                                                      "metrics.json", "report.md"]
    assert metrics["per_law"]["gdpr"]["v2"]["silver_relevant_found"] == 0          # the mock says "not relevant"
    assert metrics["per_law"]["gdpr"]["v2"]["n_silver_relevant"] == 26
    assert metrics["per_law"]["consumer_law"]["v2"]["n_silver_relevant"] == 34
    answers = json.loads((out / "answers_consumer_law.json").read_text(encoding="utf-8"))
    assert len(answers) == 65 and all(a["valid_json"] for a in answers)
    with pytest.raises(ValueError, match="round must be"):
        RelevanceV2Dev(config, 4, MockLLM(["{}"]))


# ---------- fix B (28 Oct 2026): a law quote with an ellipsis is checked fragment by fragment ----------

LONG_PASSAGE = ("The controller shall take appropriate measures to provide any information referred to in Articles 13 "
                "and 14 to the data subject in a concise, transparent, intelligible and easily accessible form, using "
                "clear and plain language.")
CHECKER = RelevanceV2Checker()


def law_found(quote: str) -> bool | None:
    return CHECKER.law_quote_found(quote, LONG_PASSAGE)


def test_ellipsis_quote_with_verbatim_fragments_in_order_is_found():
    assert law_found("The controller shall take appropriate measures ... using clear and plain language") is True
    assert law_found("The controller shall take appropriate measures … using clear and plain language") is True
    assert law_found("The controller shall take appropriate measures ... to the data subject in a concise "
                     "... using clear and plain language") is True


def test_ellipsis_fragments_in_the_wrong_order_are_not_found():
    assert law_found("using clear and plain language ... The controller shall take appropriate measures") is False


def test_an_ellipsis_fragment_shorter_than_four_words_is_not_found():
    assert law_found("The controller shall take appropriate measures ... plain language") is False


def test_an_invented_ellipsis_fragment_is_not_found():
    assert law_found("The controller shall take appropriate measures ... within fourteen calendar days") is False


def test_a_quote_without_an_ellipsis_is_checked_exactly_as_before():
    assert law_found("take appropriate measures to provide any information") is True
    assert law_found("the shop must refund the customer") is False
    assert law_found("") is None and law_found("...") is None


def test_description_quote_is_not_ellipsis_aware(tmp_path):
    # the fix is for the law quote only: an ellipsis in the description quote still fails
    answer = dict(REAL, description_quote="The customer chooses a product ... The shop sends the product")
    result = run_and_check(tmp_path, answer)
    assert (result["description_quote_found"], result["final_relevant"]) == (False, False)


# ---------- fix B: the label cause is code-decided, never the model's own reason ----------

def test_cause_names_the_check_that_failed(tmp_path):
    assert run_and_check(tmp_path, REAL)["cause"] == "relevant"
    assert run_and_check(tmp_path, FAKE_LAW_QUOTE)["cause"] == "law_quote not found"
    assert run_and_check(tmp_path, FAKE_DESCRIPTION_QUOTE)["cause"] == "description_quote not found"
    assert run_and_check(tmp_path, EMPTY_STEP)["cause"] == "the model said not relevant, description_quote empty"
