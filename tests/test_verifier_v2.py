"""Tests for the verifier of ApplicabilityAgentV2 (fix verifier, 30 Oct 2026): after the quote check of the first and
the second look, every confirmed or contradicted item gets one more call (VerifierCallV2) with only its statement as
sent and its canonical quote; "no" -> not_stated, downgrade_cause "verifier rejected". MockLLM answers only.
"""

import itertools
import json

from scripts.oracle_o2 import give_thinking
from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, VerifierCallV2
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE

DESCRIPTION = "The customer chooses a product. The customer pays by card. The shop sends the product."
PASSAGE = "If a customer pays by card, the shop must give a receipt, unless the customer declines it."
SPLIT = {"roles": ["controller"], "if": ["a customer pays by card"], "then": "the shop must give a receipt",
         "exceptions": ["the customer declines the receipt"]}


def check(c1_status="confirmed", c1_quote="the customer PAYS by card", e1_status="not_stated", e1_quote=None):
    return {"results": [{"id": "C1", "closest_sentence": None, "status": c1_status,
                         "quotes": [c1_quote] if c1_quote else []},
                        {"id": "E1", "closest_sentence": None, "status": e1_status,
                         "quotes": [e1_quote] if e1_quote else []}]}


YES = {"answer": "yes", "reason": "The sentence says the customer pays by card."}
NO = {"answer": "no", "reason": "The sentence is about a different event."}
RUN_IDS = itertools.count()


def first_look(tmp_path, answers):
    llm = MockLLM([json.dumps(a) if isinstance(a, dict) else a for a in answers])
    agent = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "C3V2", f"v{next(RUN_IDS)}"))
    return agent, agent.first_look("x", DESCRIPTION, "P-1", PASSAGE), llm


def item(record, item_id):
    return next(c for c in record["conditions"] + record["exceptions"] if c["id"] == item_id)


def test_yes_keeps_the_status_and_saves_the_answer(tmp_path):
    _, record, llm = first_look(tmp_path, [SPLIT, check(), YES])
    c1 = item(record, "C1")
    assert (c1["status"], c1["decided_by"], c1["downgraded"], c1["downgrade_cause"]) == \
        ("confirmed", "first look", False, None)
    assert c1["verifier"] == {"asked": "true", "answer": "yes", "reason": YES["reason"]}
    assert item(record, "E1")["verifier"] is None              # not_stated: no verifier call
    assert len(llm.prompts_received) == 3 and record["label"] == APPLICABLE


def test_the_prompt_has_only_the_statement_as_sent_and_the_canonical_quote(tmp_path):
    _, record, llm = first_look(tmp_path, [SPLIT, check(), YES])
    prompt = llm.prompts_received[2]
    c1 = item(record, "C1")
    assert c1["text_sent"] in prompt and c1["quotes_canonical"] == ["The customer pays by card"]
    assert "The customer pays by card" in prompt and "the customer PAYS by card" not in prompt   # canonical, not the model's
    assert "chooses a product" not in prompt and PASSAGE not in prompt                       # no description, no law
    assert "state that the statement is true?" in prompt


def test_no_turns_the_item_into_not_stated(tmp_path):
    _, record, _ = first_look(tmp_path, [SPLIT, check(), NO])
    c1 = item(record, "C1")
    assert (c1["status"], c1["original_status"], c1["decided_by"], c1["downgraded"], c1["downgrade_cause"]) == \
        ("not_stated", "confirmed", None, True, "verifier rejected")
    assert c1["quote_found"] is True and c1["verifier"]["answer"] == "no"
    assert record["label"] == INDETERMINATE


def test_a_contradicted_item_is_asked_false(tmp_path):
    _, record, llm = first_look(tmp_path, [SPLIT, check(c1_status="contradicted"), YES])
    assert "state that the statement is false?" in llm.prompts_received[2]
    assert item(record, "C1")["verifier"]["asked"] == "false" and record["label"] == NOT_APPLICABLE


def test_a_quote_not_found_is_downgraded_by_the_quote_check_without_a_verifier_call(tmp_path):
    _, record, llm = first_look(tmp_path, [SPLIT, check(c1_quote="the customer pays in cash"), YES])
    c1 = item(record, "C1")
    assert (c1["status"], c1["downgrade_cause"], c1["verifier"]) == ("not_stated", "quote not found", None)
    assert len(llm.prompts_received) == 2


def test_every_confirmed_or_contradicted_item_gets_its_own_call(tmp_path):
    answers = [SPLIT, check(e1_status="contradicted", e1_quote="The shop sends the product"), YES, NO]
    _, record, llm = first_look(tmp_path, answers)
    assert len(llm.prompts_received) == 4
    assert (item(record, "C1")["status"], item(record, "E1")["status"]) == ("confirmed", "not_stated")
    assert item(record, "E1")["downgrade_cause"] == "verifier rejected"


def test_the_second_look_is_verified_too(tmp_path):
    second = {"results": [{"id": "C1", "closest_sentence": None, "status": "confirmed",
                           "quotes": ["The customer pays by card"]}]}
    agent, record, llm = first_look(tmp_path, [SPLIT, check(c1_status="not_stated", c1_quote=None), second, NO])
    assert record["label"] == INDETERMINATE
    agent.second_look("x", DESCRIPTION, record, "P-1", [])
    c1 = item(record, "C1")
    assert (c1["status"], c1["first_look_status"], c1["downgrade_cause"]) == ("not_stated", "not_stated",
                                                                              "verifier rejected")
    assert len(llm.prompts_received) == 4 and record["label"] == INDETERMINATE


def test_no_valid_verifier_answer_after_the_retry_fails_the_step(tmp_path):
    _, record, _ = first_look(tmp_path, [SPLIT, check(), "not json", "still not json"])
    assert record["failed_step"] == "verifier" and record["label"] is None


def test_json_schema_without_class_description():
    call = VerifierCallV2(MockLLM(["{}"]), None)
    schema = call.model_schema()
    assert "description" not in schema and set(schema["properties"]) == {"answer", "reason"}
    assert schema["properties"]["answer"]["enum"] == ["yes", "no"]
    assert call.format_schema() == schema


def test_think_calls_can_name_the_verifier(tmp_path):
    agent, _, _ = first_look(tmp_path, [SPLIT, check(), YES])
    thinking = MockLLM([json.dumps(YES)])
    give_thinking(agent, ["VerifierCallV2"], thinking)
    assert agent.verifier_call.llm is thinking and agent.check_call.llm is not thinking
