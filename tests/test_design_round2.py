"""Tests for C3 v2 design round 2 (31 Oct 2026), one section per fix (MockLLM answers only, no Ollama):
  F1 the split also gives duty_type ("duty" / "right" / "none"); "none" -> label "No duty", no requirement
  F2 narrowed case events (a: only an actor's action in a single case); (b) the verifier checks that each If/When part
     of an Applicable (conditional) requirement describes the same event as its case event ("no" -> invalid)
Passages and descriptions below are made up.
"""

import json

import pytest

from src.agents.applicability_agent_v2 import NO_DUTY, ApplicabilityAgentV2
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from tests.test_design_round1 import (BUY_CONFIRMED_RETURN_OPEN, NO_KNOWLEDGE, RETURN_PASSAGE, RETURN_RELEVANT,
                                      RETURN_REQUIREMENT, RETURN_SPLIT, RUN_IDS, SHOP, return_orchestrator)

pytestmark = pytest.mark.usefixtures("verifier_yes")   # the verifier says "yes"; it is tested in test_verifier_v2.py


def agent(tmp_path, answers, **switches):
    llm = MockLLM([json.dumps(a) for a in answers])
    return ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND2", f"r{next(RUN_IDS)}"), **switches), llm


# ---------- F1: passages with no duty of their own ----------

LIMIT_PASSAGE = "Paragraphs 1 to 3 shall not apply where the product is sold at an auction."
NONE_SPLIT = {"duty_type": "none", "roles": ["other"], "if": [], "then": "", "exceptions": [], "special_cases": []}
LIMIT_RELEVANT = {**RETURN_RELEVANT, "law_quote": "shall not apply where the product is sold at an auction"}


def test_f1_duty_type_none_gives_no_duty_and_nothing_else_runs(tmp_path):
    a, llm = agent(tmp_path, [NONE_SPLIT])
    record = a.first_look("x", SHOP, "P-1", LIMIT_PASSAGE)
    assert record["label"] == NO_DUTY == "No duty" and record["duty_type"] == "none"
    assert record["conditions"] == [] and record["check"] is None and record["failed_step"] is None
    assert len(llm.prompts_received) == 1                                   # the split only


def test_f1_no_duty_comes_before_the_obligation_word_check(tmp_path):
    a, _ = agent(tmp_path, [{**NONE_SPLIT, "if": ["paragraphs 1 to 3 shall not apply"]}])
    assert a.first_look("x", SHOP, "P-1", LIMIT_PASSAGE)["label"] == "No duty"


def test_f1_orchestrator_keeps_no_duty_out_of_the_block(tmp_path):
    orch, llm = return_orchestrator(tmp_path, [LIMIT_RELEVANT, NONE_SPLIT], passage=LIMIT_PASSAGE)
    result = orch.mediate_case("c", SHOP)
    record = result["passages"][0]
    assert record["label"] == "No duty" and record["requirement"] is None and record["resolution"] is None
    assert record["label_cause"].startswith("duty_type none: the passage places no duty and gives no right")
    assert result["knowledge_block"] == NO_KNOWLEDGE and len(llm.prompts_received) == 2


@pytest.mark.parametrize("duty_type", ["duty", "right"])
def test_f1_duty_and_right_go_on_as_before(tmp_path, duty_type):
    a, _ = agent(tmp_path, [{**RETURN_SPLIT, "duty_type": duty_type}, BUY_CONFIRMED_RETURN_OPEN], case_events=True)
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert record["duty_type"] == duty_type and record["label"] == "Applicable (conditional)"


def test_f1_an_answer_without_duty_type_is_read_as_a_duty(tmp_path):
    a, _ = agent(tmp_path, [RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN])
    assert "duty_type" not in RETURN_SPLIT
    assert a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)["duty_type"] == "duty"


def test_f1_schema_requires_duty_type_and_prompt_explains_it_with_made_up_examples(tmp_path):
    a, _ = agent(tmp_path, ["{}"])
    prompt = a.split_call.build_prompt(passage_id="P-1", passage_text=LIMIT_PASSAGE)
    schema = a.split_call.model_schema()
    assert "duty_type" in schema["required"] and schema["properties"]["duty_type"]["enum"] == ["duty", "right", "none"]
    assert list(schema["properties"])[0] == "duty_type"
    assert '"none": it places no duty and gives no right of its own; it only limits, excludes or refers to other ' \
           'rules (for example "paragraphs 1 to 3 shall not apply where ..." or "without prejudice to ...")' in prompt
    assert prompt.count('"duty_type": "duty"') == 5
    assert ('EXAMPLE WITH A RIGHT (made up, for the format only)\nRule: "A sender may ask the carrier for a receipt'
            in prompt)
    assert ('EXAMPLE WITH NO DUTY OF ITS OWN (made up, for the format only)\nRule: "Parcels under 1 kg are exempt '
            'from paragraphs 1 and 2; this leaves the separate rules on dangerous goods untouched."\nAnswer: {"duty_type": '
            '"none", "roles": ["other"], "if": [], "then": "", "exceptions": [], "special_cases": []}') in prompt


# ---------- F2: narrowed case events (a) and the verifier's case-event check (b) ----------

YES, NO = {"answer": "yes", "reason": "the same return"}, {"answer": "no", "reason": "buying is not returning"}


def test_f2a_split_prompt_and_schema_narrow_case_events(tmp_path):
    a, _ = agent(tmp_path, ["{}"])
    prompt = a.split_call.build_prompt(passage_id="P-1", passage_text=RETURN_PASSAGE)
    assert ('What is sold, the type of contract, of content or of service, and who the parties are are ALWAYS process '
            'facts.') in prompt
    assert ('"case_event": ONLY something an actor does during a single case of the process: requests, withdraws, '
            'pays, delivers, returns, complains or cancels. Nothing else is a case event.') in prompt
    assert '{"text": "the parcel is fragile", "kind": "process_fact"}' in prompt                    # what is handled
    assert '{"text": "a list of approved carriers changes", "kind": "process_fact"}' in prompt
    assert '{"text": "the recipient asks for a later delivery", "kind": "case_event"}' in prompt      # actor actions
    kind = a.split_call.model_schema()["$defs"]["IfItem"]["properties"]["kind"]["description"]
    assert "who the parties are are always process facts" in kind and "(requests, withdraws, pays" in kind


def conditional_orchestrator(tmp_path, event_answers):
    orch, llm = return_orchestrator(tmp_path, [RETURN_RELEVANT, RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN,
                                               RETURN_REQUIREMENT], case_events=True, event_check=True)
    check = MockLLM([json.dumps(e) if isinstance(e, dict) else e for e in event_answers])
    orch.applicability_agent.event_verifier_call.llm = check
    return orch, check


def test_f2b_same_event_keeps_the_requirement_and_saves_the_check(tmp_path):
    orch, check = conditional_orchestrator(tmp_path, [YES])
    out = orch.mediate_case("c", SHOP)
    record = out["passages"][0]
    assert record["label"] == "Applicable (conditional)" and record["requirement"]["requirement_invalid"] is False
    assert record["requirement"]["event_checks"] == [
        {"id": "C2", "event": "the customer returns the product", "kept_as": "If the customer returns the product",
         "answer": "yes", "reason": "the same return"}]
    assert out["knowledge_block"].endswith("- [P-1] " + RETURN_REQUIREMENT["requirement"])
    assert len(check.prompts_received) == 1
    assert ("CASE EVENT\nthe customer returns the product\n\nIF/WHEN PART OF A REQUIREMENT\nIf the customer returns "
            "the product\n") in check.prompts_received[0]


def test_f2b_a_different_event_makes_the_requirement_invalid(tmp_path):
    orch, _ = conditional_orchestrator(tmp_path, [NO])
    out = orch.mediate_case("c", SHOP)
    record = out["passages"][0]
    req = record["requirement"]
    assert req["requirement_invalid"] is True and req["requirement"] is None
    assert req["event_checks"][0]["answer"] == "no"
    assert record["label"] == "Applicable (conditional)"
    assert record["label_cause"] == ('requirement invalid: the If/When part "If the customer returns the product" does '
                                     'not describe the same event as case event C2 ("the customer returns the '
                                     'product"): buying is not returning')
    assert out["knowledge_block"] == NO_KNOWLEDGE


def test_f2b_no_valid_check_answer_gives_mediation_failed(tmp_path):
    orch, _ = conditional_orchestrator(tmp_path, ["not json", "not json"])
    record = orch.mediate_case("c", SHOP)["passages"][0]
    assert record["label"] == "Mediation failed" and record["failed_step"] == "requirement"
    assert "event check (EventVerifierCallV2)" in record["error"]


def test_f2b_no_check_without_case_events_or_with_an_invalid_requirement(tmp_path):
    a, _ = agent(tmp_path, ["{}"])
    a.event_verifier_call.llm = check = MockLLM([json.dumps(NO)])
    valid = {"requirement": "x", "requirement_invalid": False, "attempts": [{"problems": [], "case_events": []}]}
    invalid = {"requirement": None, "requirement_invalid": True, "attempts": [{"problems": ["p"], "case_events": []}]}
    events = [{"id": "C2", "text": "the customer returns the product"}]
    assert a.check_case_events("x", valid, []) and a.check_case_events("x", invalid, events)
    assert a.check_case_events("x", None, events)
    assert check.prompts_received == [] and valid["requirement_invalid"] is False and "event_checks" not in valid


def test_f2b_without_d5_no_case_events_and_no_check(tmp_path):
    a, _ = agent(tmp_path, [RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN], case_events=False)
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert record["label"] == "Indeterminate"


def test_f2b_event_check_is_a_verifier_call_and_gets_thinking(tmp_path):
    from scripts.oracle_o2 import give_thinking
    from src.agents.applicability_agent_v2 import EventVerifierCallV2, VerifierCallV2
    a, base = agent(tmp_path, ["{}"])
    think = MockLLM(["{}"])
    give_thinking(a, ["CheckIfCallV2", "SecondLookCallV2", "VerifierCallV2"], think)
    assert isinstance(a.event_verifier_call, EventVerifierCallV2) and isinstance(a.event_verifier_call, VerifierCallV2)
    assert a.event_verifier_call.llm is think and a.verifier_call.llm is think and a.split_call.llm is base
    schema = a.event_verifier_call.model_schema()
    assert schema["properties"]["answer"]["enum"] == ["yes", "no"] and set(schema["required"]) == {"answer", "reason"}


# ---------- dry-run defaults (31 Oct 2026): D5 off, event check off, F1 on, D4b off ----------

def test_default_d5_is_off_every_if_item_is_a_process_fact(tmp_path):
    a, _ = agent(tmp_path, [RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN])
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert a.case_events is False
    assert [(c["id"], c.get("item_kind"), c.get("split_kind")) for c in record["conditions"]] == [
        ("R1", None, None), ("C1", "process_fact", "process_fact"), ("C2", "process_fact", "case_event")]
    assert record["label"] == "Indeterminate"                               # not "Applicable (conditional)"


def test_default_event_check_is_off_even_with_d5_on(tmp_path):
    orch, _ = return_orchestrator(tmp_path, [RETURN_RELEVANT, RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN,
                                             RETURN_REQUIREMENT], case_events=True)
    orch.applicability_agent.event_verifier_call.llm = check = MockLLM([json.dumps(NO)])
    record = orch.mediate_case("c", SHOP)["passages"][0]
    assert orch.applicability_agent.event_check is False and check.prompts_received == []
    assert record["label"] == "Applicable (conditional)" and record["requirement"]["requirement_invalid"] is False
    assert "event_checks" not in record["requirement"]


def test_default_f1_is_on_duty_type_none_gives_no_duty(tmp_path):
    a, llm = agent(tmp_path, [NONE_SPLIT])
    assert a.first_look("x", SHOP, "P-1", LIMIT_PASSAGE)["label"] == NO_DUTY and len(llm.prompts_received) == 1


def test_default_d4b_is_off_special_cases_are_not_evaluated(tmp_path):
    from tests.test_design_round1 import MAIN_OPEN, SPECIAL_PASSAGE, SPECIAL_SPLIT, VASES
    a, llm = agent(tmp_path, [SPECIAL_SPLIT, MAIN_OPEN])
    assert a.sub_rules is False
    assert a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)["sub_rules"] == [] and len(llm.prompts_received) == 2
