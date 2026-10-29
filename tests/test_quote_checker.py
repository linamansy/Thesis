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


# ---------- fix tolquote (30 Oct 2026): tolerant matching, used by every C3 v2 quote check ----------

from src.mediation.quote_checker import match_quote

DESCRIPTION = ("The sales staff write down the customer's name, phone number and email address. "
               "The shop sends the offer to the customer.")


def test_one_missing_word_in_a_short_quote_is_accepted_and_the_exact_span_is_saved():
    assert match_quote("phone and email", DESCRIPTION) == (True, "phone number and email")


def test_plural_s_is_accepted():
    assert match_quote("sends the offers", DESCRIPTION) == (True, "sends the offer")
    assert match_quote("distance contracts", "rules for a distance contract")[0] is False   # 2 words: too short
    assert match_quote("for distance contracts", "rules for distance contract")[0] is True


def test_reordered_words_are_rejected():
    assert match_quote("email and phone number", DESCRIPTION) == (False, None)


def test_a_quote_from_another_sentence_is_rejected():
    assert match_quote("the customer pays the invoice", DESCRIPTION) == (False, None)


def test_a_two_word_quote_is_rejected():
    assert match_quote("phone number", DESCRIPTION) == (False, None)


def test_more_extra_words_than_allowed_are_rejected():
    # 3 quote words allow 1 extra word; "name, phone number and email" has 2 extra words between name and email
    assert match_quote("name and email", DESCRIPTION) == (False, None)


def test_no_quote_still_gives_none():
    assert match_quote(None, DESCRIPTION) == (None, None)
    assert match_quote(" — ", DESCRIPTION) == (None, None)
