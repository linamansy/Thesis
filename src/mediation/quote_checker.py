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
QuoteChecker.found (strict) is used by the frozen Study 1 / v1 components only.

Tolerant quote matching (fix tolquote, 30 Oct 2026), used by EVERY quote check of C3 v2 (description quotes, law
quotes, duty from_then, triggers, kept_as; the ellipsis-fragment check of RelevanceV2Checker is built on it).
qwen3 sometimes drops or adds one word when it copies a quote ("phone and email" for "phone number and email"), and
the strict check then turned a confirmed condition into not_stated (GDPR-Art13-1, case 01.1). The rule, in match_quote:
  1. both texts are split into words: lowercase, punctuation removed, a simple plural -s removed (word_key)
  2. the quote must have at least MIN_QUOTE_WORDS words
  3. it matches a contiguous span of the source if ALL quote words appear in that span in the same order, the span
     starts with the first quote word and ends with the last, and the span has at most 1 extra word per 6 quote
     words (rounded up: 1 extra word for 3-6 quote words, 2 for 7-12, ...)
  4. the matched span, copied exactly from the source, is returned as the canonical quote and saved next to the
     model's quote
Reordered words, a changed word or words from elsewhere in the source do not match.
"""

import math
import re

QUOTE_CHARACTERS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",   # single quotes and apostrophes
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',   # double quotes
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",  # dashes and minus
})
NOT_LETTER_OR_DIGIT = re.compile(r"[\W_]+")
LETTERS_OR_DIGITS = re.compile(r"[^\W_]+")
MIN_QUOTE_WORDS = 3      # fixed by the task of 30 Oct 2026, not a study parameter
QUOTE_WORDS_PER_EXTRA = 6  # at most 1 extra source word per 6 quote words (rounded up)


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


# ---------- tolerant matching (fix tolquote) ----------

def word_key(word: str) -> str:
    """Lowercase word with a simple plural -s removed ("contracts" -> "contract"; "address", "is" stay)."""
    word = word.lower()
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def source_words(text: str) -> list[tuple[str, int, int]]:
    """Every word of the text as (key, start character, end character), so a span can be copied back exactly."""
    return [(word_key(m.group()), m.start(), m.end()) for m in LETTERS_OR_DIGITS.finditer(text or "")]


def find_span(quote: str, words: list[tuple[str, int, int]], start_word: int = 0) -> tuple[int, int] | None:
    """(first word, last word + 1) of the span from start_word on that the quote matches (step 3), else None.
    If several spans match, the one with the fewest extra words is taken (the earliest of those), so a quote of
    "The controller shall ..." does not start at an earlier "the" in the article title."""
    keys = [word_key(w) for w in LETTERS_OR_DIGITS.findall(quote or "")]
    if len(keys) < MIN_QUOTE_WORDS:
        return None
    max_span = len(keys) + math.ceil(len(keys) / QUOTE_WORDS_PER_EXTRA)
    best = None
    for first in range(start_word, len(words)):
        if words[first][0] != keys[0]:
            continue
        matched, position = 1, first + 1      # match the other quote words as early as possible (shortest span)
        while matched < len(keys) and position < len(words) and position - first < max_span:
            if words[position][0] == keys[matched]:
                matched += 1
            position += 1
        if matched == len(keys) and (best is None or position - first < best[1] - best[0]):
            best = (first, position)
            if position - first == len(keys):   # no extra word: nothing can be better
                break
    return best


def match_quote(quote: str | None, text: str) -> tuple[bool | None, str | None]:
    """(found, canonical quote). found is None if the quote has no words; the canonical quote is the exact span of
    the text that matched (None if not found)."""
    if not LETTERS_OR_DIGITS.search(quote or ""):
        return None, None
    words = source_words(text)
    span = find_span(quote, words)
    if span is None:
        return False, None
    return True, text[words[span[0]][1]:words[span[1] - 1][2]]
