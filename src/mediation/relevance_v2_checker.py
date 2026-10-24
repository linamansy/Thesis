"""RelevanceV2Checker: the code check on RelevanceAgent v2's answer (NO LLM).

Both quotes are checked with the same QuoteChecker as v1 and the ApplicabilityResolver (same normalisation, whole
words in the same order):
  law_quote_found          law_quote appears in the passage (True / False, or None if the quote is empty)
  description_quote_found  description_quote appears in the description (True / False, or None if empty)
Final label: relevant only if the model said relevant = true AND both quotes are found. Anything else (model said
false, a quote not found, an empty quote) gives irrelevant. The model's own answer is kept unchanged next to it.
"""

from src.agents.relevance_agent_v2 import RelevanceOutputV2
from src.mediation.quote_checker import QuoteChecker


class RelevanceV2Checker:
    """Checks the two quotes and decides the final relevance label."""

    def __init__(self):
        self.quote_checker = QuoteChecker()

    def check(self, answer: RelevanceOutputV2, passage_text: str, description: str) -> dict:
        law_found = self.quote_checker.found(answer.law_quote, passage_text)
        description_found = self.quote_checker.found(answer.description_quote, description)
        final = bool(answer.relevant and law_found and description_found)
        return {**answer.model_dump(), "law_quote_found": law_found, "description_quote_found": description_found,
                "final_relevant": final}
