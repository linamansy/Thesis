"""RelevanceV2Checker: the code check on RelevanceAgent v2's answer (NO LLM).

Both quotes are checked with the same QuoteChecker as v1 and the ApplicabilityResolver (same normalisation, whole
words in the same order):
  law_quote_found          law_quote appears in the passage (True / False, or None if the quote is empty)
  description_quote_found  description_quote appears in the description (True / False, or None if empty)
Final label: relevant only if the model said relevant = true AND both quotes are found. Anything else (model said
false, a quote not found, an empty quote) gives irrelevant. The model's own answer is kept unchanged next to it.

Fix B (28 Oct 2026), LAW QUOTE ONLY: a long article is often quoted with an ellipsis ("The controller shall take
appropriate measures ... using clear and plain language"). The plain QuoteChecker rejected such a quote even though
every fragment was verbatim, so a relevant passage was labelled Irrelevant (GDPR-Art12-1, case 01.1). A law quote
with "..." or "…" is therefore split at the ellipses and accepted only if EVERY fragment
  - has at least MIN_FRAGMENT_WORDS words (so "the" or "data" cannot stand for a whole sentence),
  - appears word for word in the passage (the same normalisation and whole-word rule as QuoteChecker), and
  - comes after the previous fragment in the passage (the fragments keep their order).
A law quote without an ellipsis is checked exactly as before, and so is the description quote.

Fix tolquote (30 Oct 2026): both quotes, and every ellipsis fragment, are now matched with the ONE tolerant function
match_quote / find_span (src/mediation/quote_checker.py: plural -s, at most 1 extra word per 6 quote words, at least
3 words). The fragment rules above stay on top of it; each fragment is matched after the span of the previous one.
The matched exact spans are saved as law_quote_canonical and description_quote_canonical (fragments joined
with " ... ").

cause() turns the three findings into one short, code-decided sentence, so the audit trail and the printed tables say
why the label is Irrelevant instead of showing the model's own reason next to a label the code decided.
"""

import re

from src.agents.relevance_agent_v2 import RelevanceOutputV2
from src.mediation.quote_checker import LETTERS_OR_DIGITS, find_span, match_quote, source_words

ELLIPSIS = re.compile(r"\.\s*\.\s*\.+|…")
MIN_FRAGMENT_WORDS = 4   # fixed here, not a study parameter: the smallest fragment that can still identify a rule


class RelevanceV2Checker:
    """Checks the two quotes and decides the final relevance label."""

    def law_quote_found(self, quote: str | None, passage_text: str) -> bool | None:
        """True / False, or None if the quote is empty (see law_quote_match)."""
        return self.law_quote_match(quote, passage_text)[0]

    @staticmethod
    def law_quote_match(quote: str | None, passage_text: str) -> tuple[bool | None, str | None]:
        """As match_quote, but a quote with an ellipsis is checked fragment by fragment (fix B)."""
        if not quote or not ELLIPSIS.search(quote):
            return match_quote(quote, passage_text)
        fragments = [f for f in ELLIPSIS.split(quote) if LETTERS_OR_DIGITS.search(f)]
        if not fragments:
            return None, None                # the quote is only ellipses and punctuation: no quote at all
        words = source_words(passage_text)
        start, spans = 0, []                 # fragments must appear in order, one after the other
        for fragment in fragments:
            if len(LETTERS_OR_DIGITS.findall(fragment)) < MIN_FRAGMENT_WORDS:
                return False, None
            span = find_span(fragment, words, start)
            if span is None:
                return False, None
            spans.append(passage_text[words[span[0]][1]:words[span[1] - 1][2]])
            start = span[1]
        return True, " ... ".join(spans)

    def check(self, answer: RelevanceOutputV2, passage_text: str, description: str) -> dict:
        law_found, law_canonical = self.law_quote_match(answer.law_quote, passage_text)
        description_found, description_canonical = match_quote(answer.description_quote, description)
        final = bool(answer.relevant and law_found and description_found)
        result = {**answer.model_dump(), "law_quote_found": law_found, "description_quote_found": description_found,
                  "law_quote_canonical": law_canonical, "description_quote_canonical": description_canonical,
                  "final_relevant": final}
        result["cause"] = self.cause(result)
        return result

    @staticmethod
    def cause(result: dict) -> str:
        """Why the code decided this way: "relevant" when it passed, else the checks that failed."""
        if result["final_relevant"]:
            return "relevant"
        reasons = []
        if not result["relevant"]:
            reasons.append("the model said not relevant")
        for name, found in (("law_quote", result["law_quote_found"]),
                            ("description_quote", result["description_quote_found"])):
            if found is None:
                reasons.append(f"{name} empty")
            elif not found:
                reasons.append(f"{name} not found")
        return ", ".join(reasons)
