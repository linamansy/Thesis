"""Tests for C3 v2 design round 1 (31 Oct 2026), one section per fix (MockLLM answers only, no Ollama):
  D1 substantive duty holder of a "Member States shall ensure" rule (code)
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
