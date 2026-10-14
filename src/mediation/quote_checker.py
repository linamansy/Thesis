"""QuoteChecker: does a quote really appear in a text? (NO LLM)

LLMs often copy a quote with small character differences: a straight apostrophe instead of a
curly one, a different dash, a missing comma. These should not count as invented quotes.
Before comparing, both the quote and the text are normalised:
  1. lowercase
  2. curly quotes and apostrophes -> straight ones ( ‘ ’ “ ” -> ' " ), all dashes -> "-"
  3. every punctuation character (anything that is not a letter or digit) -> a space
  4. whitespace collapsed to single spaces
The quote is accepted only if its words appear in the text as the same WHOLE words in the
same order. A changed, added or missing word means the quote is not found; "pay" does not
match inside "payment".
"""

import re

QUOTE_CHARACTERS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",   # single quotes and apostrophes
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',   # double quotes
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",  # dashes and minus
})
NOT_LETTER_OR_DIGIT = re.compile(r"[\W_]+")


def normalise_for_quotes(text: str) -> str:
    """Steps 1-4 above."""
    text = text.lower().translate(QUOTE_CHARACTERS)
    return " ".join(NOT_LETTER_OR_DIGIT.sub(" ", text).split())


class QuoteChecker:
    """Checks quotes against a text."""

    def found(self, quote: str | None, text: str) -> bool | None:
        """True / False, or None if there is no quote (null or only punctuation/whitespace)."""
        words = normalise_for_quotes(quote or "")
        if not words:
            return None
        # Padding with spaces makes the match work on whole words only.
        return f" {words} " in f" {normalise_for_quotes(text)} "
