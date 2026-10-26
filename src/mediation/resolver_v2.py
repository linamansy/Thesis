"""ResolverV2 (C3 v2, box 3): the final label of a rule, by code only (NO LLM).

Input: the applicability record of one passage (ApplicabilityAgentV2), whose IF conditions and exceptions already
have their final status after the code quote check (confirmed / contradicted / not_stated).

  look_label(statuses)   the label of one look (first or second) from the IF statuses only:
                           any contradicted -> Not applicable; all confirmed -> Applicable; otherwise -> Indeterminate
                           (an empty IF list is Indeterminate: there is nothing to confirm the rule)
  ResolverV2.resolve()   the final label:
                           Applicable      only if all IF conditions are confirmed AND no stated exception applies
                           Not applicable  if an IF condition is contradicted OR a stated exception is confirmed
                           Indeterminate   otherwise
An exception "applies" only if the description confirms it (verified quote); an exception the description does not
mention does not block the rule. Only Applicable rules are passed on (to the RequirementAgentV2); Indeterminate and
Not applicable rules stay in the audit trail and never reach the knowledge block.
"""

from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE


def look_label(statuses: list[str]) -> str:
    if "contradicted" in statuses:
        return NOT_APPLICABLE
    if statuses and all(s == "confirmed" for s in statuses):
        return APPLICABLE
    return INDETERMINATE


class ResolverV2:
    """Combines the IF conditions and the exceptions of one rule into its final label."""

    def resolve(self, applicability: dict) -> dict:
        """applicability: the record from ApplicabilityAgentV2 (keys "conditions" and "exceptions", each a list of
        dicts with a final "status"). Returns the label and the reason, for the audit trail."""
        if_label = look_label([c["status"] for c in applicability["conditions"]])
        exceptions_applying = [e["text"] for e in applicability["exceptions"] if e["status"] == "confirmed"]
        if if_label == NOT_APPLICABLE:
            label, reason = NOT_APPLICABLE, "an IF condition is contradicted"
        elif exceptions_applying:
            label, reason = NOT_APPLICABLE, "a stated exception applies"
        elif if_label == APPLICABLE:
            label, reason = APPLICABLE, "all IF conditions confirmed and no stated exception applies"
        else:
            label, reason = INDETERMINATE, "not all IF conditions are confirmed"
        return {"label": label, "if_label": if_label, "exceptions_applying": exceptions_applying, "reason": reason}
