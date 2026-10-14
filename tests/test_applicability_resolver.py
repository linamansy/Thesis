"""Tests for the ApplicabilityResolver (no LLM): evidence verification and the label decision."""

from src.agents.applicability_agent import Condition
from src.mediation.applicability_resolver import (APPLICABLE, INDETERMINATE, NOT_APPLICABLE,
                                                  ApplicabilityResolver)

DESCRIPTION = """Consider a process for purchasing items from an online shop.
The user starts an order by logging in to their account.
Afterward, the user either pays or completes an installment agreement.
The order is placed by a company buyer."""


def cond(status, evidence=None, text="some condition"):
    return Condition(condition=text, status=status, evidence=evidence)


def resolve(*conditions):
    return ApplicabilityResolver().resolve(list(conditions), DESCRIPTION)


# ---------- the four required cases ----------

def test_all_satisfied_is_applicable():
    result = resolve(cond("satisfied", "purchasing items from an online shop"),
                     cond("satisfied", "the user either pays or completes an installment agreement"))
    assert result["label"] == APPLICABLE
    assert result["n_downgraded"] == 0


def test_one_contradicted_is_not_applicable():
    result = resolve(cond("satisfied", "purchasing items from an online shop"),
                     cond("contradicted", "The order is placed by a company buyer."),
                     cond("not_stated"))
    assert result["label"] == NOT_APPLICABLE


def test_one_not_stated_is_indeterminate():
    result = resolve(cond("satisfied", "purchasing items from an online shop"), cond("not_stated"))
    assert result["label"] == INDETERMINATE


def test_made_up_quote_is_downgraded_to_not_stated():
    result = resolve(cond("satisfied", "purchasing items from an online shop"),
                     cond("satisfied", "the customer is a private consumer"))  # not in the description
    assert result["label"] == INDETERMINATE
    assert result["n_downgraded"] == 1
    made_up = result["conditions"][1]
    assert made_up["status"] == "not_stated"
    assert made_up["original_status"] == "satisfied"
    assert made_up["evidence_found"] is False
    assert made_up["downgraded"] is True
    assert made_up["note"] == "evidence quote not found in the description"
    assert made_up["evidence"] == "the customer is a private consumer"  # the original quote is kept


# ---------- details of the evidence check ----------

def test_quote_matching_ignores_case_and_whitespace():
    result = resolve(cond("satisfied", "  PURCHASING items\n from   an Online   SHOP "))
    assert result["conditions"][0]["evidence_found"] is True
    assert result["label"] == APPLICABLE


def test_quote_across_a_line_break_is_found():
    # The description has a line break between these two sentences.
    result = resolve(cond("satisfied", "online shop. The user starts an order"))
    assert result["label"] == APPLICABLE


def test_made_up_contradiction_cannot_make_a_rule_not_applicable():
    result = resolve(cond("satisfied", "purchasing items from an online shop"),
                     cond("contradicted", "the seller is a private person"))
    assert result["label"] == INDETERMINATE
    assert result["conditions"][1]["original_status"] == "contradicted"


def test_satisfied_without_any_quote_is_downgraded():
    result = resolve(cond("satisfied", None), cond("satisfied", "   "))
    assert result["label"] == INDETERMINATE
    assert [c["note"] for c in result["conditions"]] == ["no evidence quote given"] * 2
    assert [c["evidence_found"] for c in result["conditions"]] == [None, None]


def test_not_stated_is_never_changed():
    result = resolve(cond("not_stated", "a quote that does not exist"))
    c = result["conditions"][0]
    assert (c["status"], c["downgraded"], c["evidence_found"]) == ("not_stated", False, False)


def test_contradicted_wins_over_everything():
    statuses = ["satisfied", "not_stated", "contradicted"]
    assert ApplicabilityResolver().decide(statuses) == NOT_APPLICABLE


def test_no_conditions_is_indeterminate():
    assert ApplicabilityResolver().decide([]) == INDETERMINATE


def test_satisfied_conditions_for_requirement_agent():
    result = resolve(cond("satisfied", "purchasing items from an online shop", text="A"),
                     cond("not_stated", text="B"),
                     cond("satisfied", "made up", text="C"))
    assert [c["condition"] for c in ApplicabilityResolver.satisfied_conditions(result)] == ["A"]
