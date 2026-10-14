"""RelevanceEvidenceChecker: records whether the RelevanceAgent's process quote is real (NO LLM).

It uses the same QuoteChecker as the ApplicabilityResolver on evidence_process (the quote
from the process description) and adds quote_found: true, false, or null when there was no
quote. The relevance decision itself is NEVER changed: this is a record for later analysis
(e.g. RQ3), not a filter.
"""

from src.agents.relevance_agent import RelevanceOutput
from src.mediation.quote_checker import QuoteChecker


class RelevanceEvidenceChecker:
    """Adds quote_found to relevance outputs and counts the results over a run."""

    def __init__(self):
        self.quote_checker = QuoteChecker()
        self.n_checked = 0     # relevance outputs with a process quote
        self.n_not_found = 0   # of which the quote was not in the description

    def check(self, relevance: RelevanceOutput, description: str) -> dict:
        """The relevance output as a dict, plus quote_found. "relevant" is copied unchanged."""
        found = self.quote_checker.found(relevance.evidence_process, description)
        if found is not None:
            self.n_checked += 1
            self.n_not_found += not found
        return {**relevance.model_dump(), "quote_found": found}

    def run_summary(self) -> dict:
        return {"process_quotes_checked": self.n_checked, "process_quotes_not_found": self.n_not_found}
