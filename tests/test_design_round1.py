"""Tests for C3 v2 design round 1 (31 Oct 2026), one section per fix (MockLLM answers only, no Ollama):
  D1 substantive duty holder of a "Member States shall ensure" rule (code)
  D2 relevance prompt: a rule that could govern a step (e.g. the step that triggers its duty) is relevant
  D3 verifier prompt: ordinary reading, an everyday equivalent of a legal concept counts
Passages and descriptions below are made up unless a real passage id is named.
"""

import itertools
import json

import pytest

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, duty_roles, substantive_duty_holder
from src.config import load_config
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

pytestmark = pytest.mark.usefixtures("verifier_yes")   # the verifier says "yes"; it is tested in test_verifier_v2.py

CONFIG = load_config()
RUN_IDS = itertools.count()
ECD_ROLES = CONFIG["c3_v2"]["roles"]["ECD-"]["names"]
LPD_ROLES = CONFIG["c3_v2"]["roles"]["LPD-"]["names"]


def agent(tmp_path, answers):
    llm = MockLLM([json.dumps(a) for a in answers])
    return ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}")), llm


# ---------- D1: substantive duty holder ----------

SHALL_ENSURE_PASSAGE = ("1. Member States shall ensure, except when otherwise agreed, that in cases where a recipient "
                        "orders a parcel, the service provider has to confirm the order.")


def test_d1_first_role_after_shall_ensure_is_the_duty_holder():
    assert substantive_duty_holder(SHALL_ENSURE_PASSAGE, ECD_ROLES) == (True, "service provider")


def test_d1_the_first_named_role_wins_and_plurals_count():
    text = "Member States shall ensure that creditors may charge debtors interest."
    assert substantive_duty_holder(text, LPD_ROLES) == (True, "creditor")
    text = "Member State shall ensure that the debtor pays the creditor."
    assert substantive_duty_holder(text, LPD_ROLES) == (True, "debtor")


def test_d1_does_not_apply_without_shall_ensure():
    assert substantive_duty_holder("The service provider shall confirm the order.", ECD_ROLES) == (False, None)
    assert duty_roles(["public body"], "Each Member State shall publish the list.", ECD_ROLES) == (["public body"], None)


def test_d1_never_a_public_body_even_without_a_named_role():
    roles, d1 = duty_roles(["public body"], "Member States shall ensure that the list is published.", ECD_ROLES)
    assert roles == ["other"] and d1["role_found"] is None and d1["split_roles"] == ["public body"]
    roles, _ = duty_roles(["public body", "service provider"], "Member States shall ensure that lists exist.", ECD_ROLES)
    assert roles == ["service provider"]


def test_d1_replaces_the_split_roles_in_the_record(tmp_path):
    split = {"roles": ["public body"], "if": ["a recipient orders a parcel"], "then": "confirm the order",
             "exceptions": []}
    description = "A shop sells parcels online to companies. A recipient orders a parcel on the website."
    check = {"results": [
        {"id": "S1", "closest_sentence": None, "status": "not_stated", "quotes": []},
        {"id": "T1", "closest_sentence": None, "status": "confirmed",
         "quotes": ["A shop sells parcels online to companies"]},
        {"id": "C1", "closest_sentence": None, "status": "confirmed",
         "quotes": ["A recipient orders a parcel on the website"]}]}
    a, llm = agent(tmp_path, [split, check])
    record = a.first_look("x", description, "ECD-Art99-1", SHALL_ENSURE_PASSAGE)
    r1 = record["conditions"][0]
    assert r1["text"] == "the duty is on: service provider" and r1["status"] == "confirmed"   # by T1, not contradicted
    assert record["duty_holder"]["split_roles"] == ["public body"]
    assert record["role_binding"] == {"service provider": "the organisation running the described process"}
    assert "T1:" in llm.prompts_received[1]


def test_d1_leaves_other_rules_unchanged(tmp_path):
    split = {"roles": ["controller"], "if": [], "then": "keep a list", "exceptions": []}
    a, _ = agent(tmp_path, [split])
    record = a.first_look("x", "The shop keeps a list.", "P-1", "The controller shall keep a list.")
    assert record["duty_holder"] is None and record["conditions"][0]["text"] == "the duty is on: controller"


# ---------- D2: relevance covers the step that triggers a duty ----------

def test_d2_relevance_prompt_counts_the_triggering_step_and_keeps_the_json_fields(tmp_path):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2, RelevanceOutputV2
    a = RelevanceAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    prompt = a.build_prompt(description="The tenant hands back the keys.", passage_id="P-1", passage_text="A rule.")
    assert "could govern an activity, an actor or an object of this process" in prompt
    assert "even when the duty itself is not performed" in prompt and "A missing duty step is not a reason for false" in prompt
    assert "EXAMPLE WITH A MISSING DUTY STEP (made up, from another domain)" in prompt
    assert list(RelevanceOutputV2.model_fields) == ["law_focus", "law_quote", "relevant", "process_step",
                                                    "description_quote", "reason"]          # same JSON fields


def test_d2_a_rule_whose_duty_step_is_missing_stays_relevant_after_the_code_check(tmp_path):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.mediation.relevance_v2_checker import RelevanceV2Checker
    description = "The tenant hands back the keys. The agent checks the flat for damage. The agent closes the file."
    passage = "When a tenant moves out, the landlord must return the deposit within 30 days."
    answer = {"law_focus": "a tenant moving out", "law_quote": "When a tenant moves out", "relevant": True,
              "process_step": "the tenant hands back the keys", "description_quote": "The tenant hands back the keys",
              "reason": "The process has the moving out; the deposit return is missing."}
    a = RelevanceAgentV2(MockLLM([json.dumps(answer)]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    out = a.run("x", description=description, passage_id="P-1", passage_text=passage)
    assert RelevanceV2Checker().check(out, passage, description)["final_relevant"] is True


# ---------- D3: verifier judges under an ordinary reading ----------

def test_d3_verifier_prompt_ordinary_reading_everyday_equivalent_and_different_event(tmp_path):
    from src.agents.applicability_agent_v2 import VerifierCallV2
    call = VerifierCallV2(MockLLM(["{}"]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    prompt = call.build_prompt(statement="the buyer is a consumer", quotes=["The shop sells to private persons"],
                               truth="true")
    assert "Under an ordinary reading" in prompt and "state that the statement is true?" in prompt
    assert "an everyday equivalent of a legal concept counts as stating it" in prompt
    assert "A sentence about a different event never confirms the statement." in prompt         # kept
    assert "EXAMPLE (made up, from another domain)" in prompt
    example = prompt.split("EXAMPLE (made up, from another domain)")[1].split("JSON SCHEMA")[0].lower()
    for word in ("consumer", "trader", "personal data", "controller", "payment", "order", "service"):
        assert word not in example, word                                   # the example is outside the corpus
    assert "- The shop sells to private persons" in prompt and prompt.count("{") > 0
