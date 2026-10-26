"""ResolverV2 (C3 v2, box 3): the final label of a rule, by code only (NO LLM).

Input: the applicability record of one passage (ApplicabilityAgentV2), whose IF items (role R1, scope S1, situational
C1...) and exceptions already have their final status after the code quote check and the role rules
(confirmed / contradicted / not_stated).

  look_label(statuses)   the label of one look (first or second) from the IF statuses only:
                           any contradicted -> Not applicable; all confirmed -> Applicable; otherwise -> Indeterminate
                           (an empty IF list is Indeterminate: there is nothing to confirm the rule)
  ResolverV2.resolve()   the final label (round 3, docs/C3_V2_DEVELOPMENT.md section 9, R4):
                           Not applicable  if an IF item is contradicted OR a stated exception is confirmed
                           Applicable      only if every IF item is confirmed, by a checked quote (first or second
                                           look) or by the code role rule (R3), the IF list has the role item (R1),
                                           and no stated exception applies
                           Indeterminate   otherwise
An exception "applies" only if the description confirms it (checked quote); an exception the description does not
mention does not block the rule. A "confirmed" item with neither a checked quote nor the code role rule counts as
not_stated here (a second guard; ApplicabilityAgentV2 already downgrades such items). Only Applicable rules are passed
on (to the RequirementAgentV2); Indeterminate and Not applicable rules stay in the audit trail and never reach the
knowledge block.
"""

from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE


def look_label(statuses: list[str]) -> str:
    if "contradicted" in statuses:
        return NOT_APPLICABLE
    if statuses and all(s == "confirmed" for s in statuses):
        return APPLICABLE
    return INDETERMINATE


def checked_status(item: dict) -> str:
    """The item's status, with "confirmed" kept only if a checked quote or the code role rule shows it."""
    if item["status"] == "confirmed" and not (item.get("quote_found") or item.get("decided_by") == "code rule"):
        return "not_stated"
    return item["status"]


class ResolverV2:
    """Combines the IF items and the exceptions of one rule into its final label."""

    def resolve(self, applicability: dict) -> dict:
        """applicability: the record from ApplicabilityAgentV2 (keys "conditions" and "exceptions", each a list of
        dicts with a final "status"). Returns the label and the reason, for the audit trail."""
        conditions = applicability["conditions"]
        if_label = look_label([checked_status(c) for c in conditions])
        has_role = any(c.get("kind") == "role" for c in conditions)
        exceptions_applying = [e["text"] for e in applicability["exceptions"] if checked_status(e) == "confirmed"]
        if if_label == NOT_APPLICABLE:
            label, reason = NOT_APPLICABLE, "an IF item is contradicted"
        elif exceptions_applying:
            label, reason = NOT_APPLICABLE, "a stated exception applies"
        elif if_label == APPLICABLE and not has_role:
            label, reason = INDETERMINATE, "the IF list has no role item (R1)"
        elif if_label == APPLICABLE:
            label, reason = APPLICABLE, "every IF item confirmed and no stated exception applies"
        else:
            label, reason = INDETERMINATE, "not every IF item is confirmed"
        decided_by = {c["id"]: c.get("decided_by") for c in conditions}
        return {"label": label, "if_label": if_label, "exceptions_applying": exceptions_applying, "reason": reason,
                "decided_by": decided_by}
