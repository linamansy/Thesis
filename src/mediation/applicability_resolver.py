"""ApplicabilityResolver: decides whether a rule applies, using code only (NO LLM).

Input: the ApplicabilityAgent's conditions and the process description.

Step (a), verify the evidence. A "satisfied" or "contradicted" status is only accepted
if its evidence quote really appears in the description. The comparison ignores upper/lower
case and differences in whitespace (spaces, tabs, line breaks). If the quote is not found,
or there is no quote at all, the status is changed to "not_stated" and this is recorded
(original_status, evidence_found, downgraded, note). A "not_stated" condition needs no evidence.

Step (b), decide the label:
  any condition contradicted   -> "Not applicable"
  all conditions satisfied     -> "Applicable"
  otherwise                    -> "Indeterminate"
A rule without any conditions is "Indeterminate" (there is nothing to confirm it).
"""

from src.agents.applicability_agent import Condition

APPLICABLE = "Applicable"
NOT_APPLICABLE = "Not applicable"
INDETERMINATE = "Indeterminate"


def normalise(text: str) -> str:
    """Lowercase and collapse all whitespace into single spaces."""
    return " ".join(text.lower().split())


class ApplicabilityResolver:
    """Verifies evidence quotes and combines condition statuses into one label."""

    def verify(self, conditions: list[Condition], description: str) -> list[dict]:
        """Step (a): one record per condition, with the verified (final) status."""
        haystack = normalise(description)
        verified = []
        for c in conditions:
            quote = (c.evidence or "").strip()
            found = bool(quote) and normalise(quote) in haystack
            record = {
                "condition": c.condition,
                "status": c.status,            # final status, after verification
                "original_status": c.status,   # what the ApplicabilityAgent said
                "evidence": c.evidence,
                "evidence_found": found if quote else None,  # None = no quote given
                "downgraded": False,
                "note": None,
            }
            if c.status in ("satisfied", "contradicted") and not found:
                record["status"] = "not_stated"
                record["downgraded"] = True
                record["note"] = ("evidence quote not found in the description" if quote
                                  else "no evidence quote given")
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

    @staticmethod
    def satisfied_conditions(resolution: dict) -> list[dict]:
        """The verified satisfied conditions: the input for the RequirementAgent."""
        return [c for c in resolution["conditions"] if c["status"] == "satisfied"]
