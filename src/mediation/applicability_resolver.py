"""ApplicabilityResolver: decides whether a rule applies, using code only (NO LLM).

Input: the ApplicabilityAgent's conditions and the process description.

Step (a), verify the evidence. A "satisfied" or "contradicted" status is only accepted
if its evidence quote really appears in the description, checked by QuoteChecker
(src/mediation/quote_checker.py): case, whitespace, quote/apostrophe style, dashes and
punctuation are ignored, but the words must be the same and in the same order.
If the quote is not found, or there is no quote at all, the status is changed to
"not_stated" and this is recorded (original_status, evidence_found, downgraded, note).
A "not_stated" condition needs no evidence.

Step (b), decide the label:
  any condition contradicted   -> "Not applicable"
  all conditions satisfied     -> "Applicable"
  otherwise                    -> "Indeterminate"
A rule without any conditions is "Indeterminate" (there is nothing to confirm it).

One resolver is used for a whole run; it counts how many conditions it checked and how
many it downgraded, so run_summary() shows how often quotes were rejected.
"""

from src.agents.applicability_agent import Condition
from src.mediation.quote_checker import QuoteChecker

APPLICABLE = "Applicable"
NOT_APPLICABLE = "Not applicable"
INDETERMINATE = "Indeterminate"


class ApplicabilityResolver:
    """Verifies evidence quotes and combines condition statuses into one label."""

    def __init__(self):
        self.quote_checker = QuoteChecker()
        self.n_conditions = 0                     # conditions checked in this run
        self.n_downgraded = 0                     # of which downgraded to not_stated
        self.n_downgraded_quote_not_found = 0     #   ... because the quote was not in the description
        self.n_downgraded_no_quote = 0            #   ... because no quote was given

    def verify(self, conditions: list[Condition], description: str) -> list[dict]:
        """Step (a): one record per condition, with the verified (final) status."""
        verified = []
        for c in conditions:
            found = self.quote_checker.found(c.evidence, description)  # None = no quote given
            record = {
                "condition": c.condition,
                "status": c.status,            # final status, after verification
                "original_status": c.status,   # what the ApplicabilityAgent said
                "evidence": c.evidence,
                "evidence_found": found,
                "downgraded": False,
                "note": None,
            }
            if c.status in ("satisfied", "contradicted") and not found:
                record["status"] = "not_stated"
                record["downgraded"] = True
                if found is None:
                    record["note"] = "no evidence quote given"
                    self.n_downgraded_no_quote += 1
                else:
                    record["note"] = "evidence quote not found in the description"
                    self.n_downgraded_quote_not_found += 1
                self.n_downgraded += 1
            self.n_conditions += 1
            verified.append(record)
        return verified

    def decide(self, statuses: list[str]) -> str:
        """Step (b): the label for a list of (verified) statuses."""
        if "contradicted" in statuses:
            return NOT_APPLICABLE
        if statuses and all(s == "satisfied" for s in statuses):
            return APPLICABLE
        return INDETERMINATE

    def resolve(self, conditions: list[Condition], description: str) -> dict:
        """Both steps: the verified conditions, the label and the number of downgrades."""
        verified = self.verify(conditions, description)
        return {
            "label": self.decide([c["status"] for c in verified]),
            "conditions": verified,
            "n_downgraded": sum(c["downgraded"] for c in verified),
        }

    def run_summary(self) -> dict:
        """Counts for the whole run (all rules resolved by this resolver)."""
        return {
            "conditions_checked": self.n_conditions,
            "downgraded": self.n_downgraded,
            "downgraded_quote_not_found": self.n_downgraded_quote_not_found,
            "downgraded_no_quote": self.n_downgraded_no_quote,
        }

    @staticmethod
    def satisfied_conditions(resolution: dict) -> list[dict]:
        """The verified satisfied conditions: the input for the RequirementAgent."""
        return [c for c in resolution["conditions"] if c["status"] == "satisfied"]
