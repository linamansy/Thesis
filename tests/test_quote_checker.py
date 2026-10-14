"""Tests for QuoteChecker and RelevanceEvidenceChecker."""

import pytest

from src.agents.relevance_agent import RelevanceOutput
from src.mediation.quote_checker import QuoteChecker, normalise_for_quotes
from src.mediation.relevance_evidence_checker import RelevanceEvidenceChecker

TEXT = "The trader’s “order confirmation” is sent — at the latest — on delivery, e-mail included."


def test_normalisation():
    assert normalise_for_quotes("The Trader’s  “Order”—sent, e-mail!") == "the trader s order sent e mail"


@pytest.mark.parametrize("quote", [
    "The trader's \"order confirmation\" is sent",       # straight quotes and apostrophe
    "the TRADER’S order confirmation is sent",            # case, no quote marks
    "is sent - at the latest - on delivery",              # hyphen instead of em dash
    "on delivery e-mail included",                        # missing comma
    "on delivery, e mail included.",                      # hyphen dropped, extra full stop
])
def test_character_differences_are_accepted(quote):
    assert QuoteChecker().found(quote, TEXT) is True


@pytest.mark.parametrize("quote", [
    "The trader's order confirmation is posted",          # changed word
    "is sent at the latest by delivery",                  # changed word
    "order confirmation sent",                            # missing word
    "delivery on the latest",                             # wrong order
    "trade",                                              # part of a word only
])
def test_word_differences_are_rejected(quote):
    assert QuoteChecker().found(quote, TEXT) is False


@pytest.mark.parametrize("quote", [None, "", "   ", "“ ” — ,"])
def test_no_quote_gives_none(quote):
    assert QuoteChecker().found(quote, TEXT) is None


# ---------- RelevanceEvidenceChecker ----------

def relevance(relevant, evidence_process):
    return RelevanceOutput(relevant=relevant, reason="r", evidence_process=evidence_process, evidence_passage=None)


def test_relevance_quote_found_is_recorded():
    checker = RelevanceEvidenceChecker()
    result = checker.check(relevance(True, "the trader's order confirmation"), TEXT)
    assert result["quote_found"] is True and result["relevant"] is True


def test_relevance_decision_is_never_changed():
    checker = RelevanceEvidenceChecker()
    invented = checker.check(relevance(True, "the consumer may withdraw"), TEXT)
    missing = checker.check(relevance(False, None), TEXT)
    assert (invented["relevant"], invented["quote_found"]) == (True, False)
    assert (missing["relevant"], missing["quote_found"]) == (False, None)
    assert {k: invented[k] for k in ("reason", "evidence_process", "evidence_passage")} == \
        {"reason": "r", "evidence_process": "the consumer may withdraw", "evidence_passage": None}
    assert checker.run_summary() == {"process_quotes_checked": 1, "process_quotes_not_found": 1}
