"""ResolverV2 (C3 v2, box 3): the final label of a rule, by code only (NO LLM).

Input: the applicability record of one passage (ApplicabilityAgentV2), whose IF items (role R1, scope S1, situational
C1...) and exceptions already have their final status after the code quote check and the role rules
(confirmed / contradicted / not_stated).

  look_label(conditions) the label of one look (first or second) from the IF statuses only:
                           any contradicted -> Not applicable; all confirmed -> Applicable; otherwise -> Indeterminate
                           (an empty IF list is Indeterminate: there is nothing to confirm the rule)
                           D4a (design round 1, 31 Oct 2026): the items of an "any" group of the split count as ONE
                           unit (if_units): confirmed if at least one item is confirmed (with a checked quote in the
                           resolver), contradicted only if all its items are
                           D5 (design round 1): a case-event unit (an item the split marked "case_event", or an "any"
                           group of them not confirmed by a process fact) need not be confirmed; if every other unit
                           is confirmed and no case event is contradicted -> Applicable (conditional): the rule applies
                           when the case event happens, and its requirement must keep the case event as "If/When ..."
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

APPLICABLE_CONDITIONAL = "Applicable (conditional)"   # D5: applies when its case events happen
APPLICABLE_LABELS = (APPLICABLE, APPLICABLE_CONDITIONAL)   # the labels that get a requirement


def is_case_event(item: dict) -> bool:
    """D5: a situational IF item the split marked as a case event (happens only in some cases)."""
    return item.get("kind") == "situation" and item.get("item_kind") == "case_event"


def if_units(conditions: list[dict], status_of=None) -> list[dict]:
    """The units a label is decided on (D4a, design round 1): every IF item on its own, except the items of an "any"
    group (the split's alternatives: "any of", "one of the following", "or"), which form one unit (id = the group id):
    confirmed if at least one of its items is confirmed, contradicted only if all are, otherwise not_stated.
    status_of(item) gives an item's status (default: its "status")."""
    status_of = status_of or (lambda c: c["status"])
    units, groups = [], {}
    for c in conditions:
        if c.get("logic") == "any":
            if c["group"] not in groups:
                groups[c["group"]] = {"id": c["group"], "logic": "any", "items": []}
                units.append(groups[c["group"]])
            groups[c["group"]]["items"].append(c)
        else:
            units.append({"id": c["id"], "logic": "one", "items": [c]})
    for u in units:
        statuses = [status_of(c) for c in u["items"]]
        u["status"] = ("confirmed" if "confirmed" in statuses else
                       "contradicted" if all(s == "contradicted" for s in statuses) else "not_stated")
        # D5: a unit is a case event unless a process fact (or the role / scope) decides it: a single case-event
        # item, or an "any" group not confirmed by a process fact that still has a case event that may happen
        by_fact = any(status_of(c) == "confirmed" and not is_case_event(c) for c in u["items"])
        u["case_event"] = not by_fact and any(is_case_event(c) and status_of(c) != "contradicted"
                                              for c in u["items"])
    return units


def case_events(conditions: list[dict], status_of=None) -> list[dict]:
    """D5: the case events a requirement must keep as its "If/When ..." trigger, as {"id", "text"}: every case-event
    unit (if_units) that is not contradicted. A single item keeps its id and text as sent; an "any" group gets its
    group id and "one of: ..." with the texts of its items that are not contradicted."""
    status_of = status_of or (lambda c: c["status"])
    events = []
    for u in if_units(conditions, status_of):
        if not u["case_event"] or u["status"] == "contradicted":
            continue
        texts = [c.get("text_sent") or c["text"] for c in u["items"] if status_of(c) != "contradicted"]
        events.append({"id": u["id"], "text": texts[0] if u["logic"] == "one" else "one of: " + "; ".join(texts)})
    return events


def look_label(conditions: list[dict], status_of=None) -> str:
    """The label from the IF items (dicts with "status"), with "any" groups as one unit each (if_units).
    D5: only the units that are not case events must be confirmed; if they are and there is a case event (none is
    contradicted, else Not applicable), the label is Applicable (conditional)."""
    units = if_units(conditions, status_of)
    if any(u["status"] == "contradicted" for u in units):
        return NOT_APPLICABLE
    if units and all(u["status"] == "confirmed" for u in units if not u["case_event"]):
        return APPLICABLE_CONDITIONAL if any(u["case_event"] for u in units) else APPLICABLE
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
        if_label = look_label(conditions, checked_status)
        has_role = any(c.get("kind") == "role" for c in conditions)
        exceptions_applying = [e["text"] for e in applicability["exceptions"] if checked_status(e) == "confirmed"]
        if if_label == NOT_APPLICABLE:
            label, reason = NOT_APPLICABLE, "an IF item is contradicted"
        elif exceptions_applying:
            label, reason = NOT_APPLICABLE, "a stated exception applies"
        elif if_label in APPLICABLE_LABELS and not has_role:
            label, reason = INDETERMINATE, "the IF list has no role item (R1)"
        elif if_label == APPLICABLE:
            label, reason = APPLICABLE, "every IF item confirmed and no stated exception applies"
        elif if_label == APPLICABLE_CONDITIONAL:
            label, reason = APPLICABLE_CONDITIONAL, ("role, scope and every process fact confirmed, no case event "
                                                     "contradicted and no stated exception applies; the case events "
                                                     "stay the requirement's triggers")
        else:
            label, reason = INDETERMINATE, "not every IF item is confirmed"
        decided_by = {c["id"]: c.get("decided_by") for c in conditions}
        units = [{"id": u["id"], "logic": u["logic"], "status": u["status"], "case_event": u["case_event"],
                  "items": [c["id"] for c in u["items"]]} for u in if_units(conditions, checked_status)]
        return {"label": label, "if_label": if_label, "exceptions_applying": exceptions_applying, "reason": reason,
                "decided_by": decided_by, "units": units, "case_events": case_events(conditions, checked_status)}
