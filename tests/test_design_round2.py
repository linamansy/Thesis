"""Tests for C3 v2 design round 2 (31 Oct 2026), one section per fix (MockLLM answers only, no Ollama):
  F1 the split also gives duty_type ("duty" / "right" / "none"); "none" -> label "No duty", no requirement
Passages and descriptions below are made up.
"""

import json

import pytest

from src.agents.applicability_agent_v2 import NO_DUTY, ApplicabilityAgentV2
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from tests.test_design_round1 import (BUY_CONFIRMED_RETURN_OPEN, NO_KNOWLEDGE, RETURN_PASSAGE, RETURN_RELEVANT,
                                      RETURN_SPLIT, RUN_IDS, SHOP, return_orchestrator)

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
    a, _ = agent(tmp_path, [{**RETURN_SPLIT, "duty_type": duty_type}, BUY_CONFIRMED_RETURN_OPEN])
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
    assert ('EXAMPLE WITH NO DUTY OF ITS OWN (made up, for the format only)\nRule: "Paragraphs 1 and 2 shall not '
            'apply to parcels below 1 kg, without prejudice to the rules on dangerous goods."\nAnswer: {"duty_type": '
            '"none", "roles": ["other"], "if": [], "then": "", "exceptions": [], "special_cases": []}') in prompt
