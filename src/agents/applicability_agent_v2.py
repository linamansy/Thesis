"""ApplicabilityAgent v2 (C3 v2, box 2): do the conditions of a relevant rule hold for this process?

v1 (src/agents/applicability_agent.py, frozen for Study 1) asked one call to split the rule AND check it against the
description; it listed obligations ("the trader shall provide ...") as conditions, so a rule could almost never be
Applicable (Problem 2 in docs/C3_V2_DEVELOPMENT.md). v2 makes the split its own call that sees the law text only.

Steps for one passage kept by RelevanceAgentV2 (round 3 decision logic, docs/C3_V2_DEVELOPMENT.md section 9):
  a. split call (SplitCallV2, law text only)  -> {"roles": [...], "if": [...], "then": "...", "exceptions": [...]}
     "roles" = who the duty is on, using only the role names of the passage's law (config.yaml c3_v2.roles, by passage
     id prefix; GDPR and any other prefix: controller / processor / public body / other; e.g. CRD: trader / consumer /
     public body / other), "if" = the situational conditions.
     Code rejects the split if an IF item contains an obligation word (config.yaml c3_v2.obligation_words:
     must / shall / is required to) -> label "Split invalid", nothing else runs.
  b. the IF list is built by code (R1, R2): one role item R1 + the scope item S1 (config.yaml c3_v2.scope_conditions,
     for every passage of that law, e.g. GDPR) + every situational condition C1, C2, ...
     Exception splitting (fix exc, 30 Oct 2026): an IF item containing "unless", "except where" or "except when" is
     cut by code; the part before stays the C item, the clause from the marker on becomes an extra exception E item
     (both keep the model's item as "original_text"). An exception that is not_stated does not block the rule.
  c. check-IF call (CheckIfCallV2: the description + the items that need a quote, not the law text): S1, the role
     facts of the named roles (c3_v2.role_facts: P1 for a processor, T1 for a trader / seller / service provider, D1
     for a debtor, D2 for a creditor), C1..., the exceptions E1... -> each item confirmed / not_stated / contradicted,
     with a quote from the description.
     Role binding (fix F2, 29 Oct 2026): in the C and E items sent to this call, a role name is replaced by the actor
     it refers to in the process (role_binding: a duty role decided by a role fact or A1 -> the organisation running
     the described process; a role decided by the scope item -> its customer; other roles unchanged). The saved
     item keeps its original "text" and records the sent "text_sent". The second look gets the same text_sent (fix 2).
  d. code quote check (match_quote, tolerant since fix tolquote, 30 Oct 2026: plural -s, at most 1 extra word per 6
     quote words, at least 3 words): a confirmed or contradicted item whose quote is missing or not found in the
     description becomes not_stated (recorded as downgraded). The matched exact span is saved as quote_canonical.
  e. roles by code (R3, config.yaml c3_v2.roles): controller -> confirmed by assumption A1 (c3_v2.controller_assumption);
     processor -> confirmed only if P1 is confirmed with a checked quote, otherwise contradicted (A1: the organisation
     is the controller); trader / seller / service provider (A2) -> confirmed only if T1 is confirmed, debtor only if
     D1 is, creditor only if D2 is (contradicted if that fact is contradicted, otherwise not_stated); consumer -> the
     status of the scope item S1; public body -> contradicted; other -> not_stated. R1 is confirmed if any of its roles
     is confirmed, contradicted if all are, otherwise not_stated.
  f. first look: the label from the statuses of R1, S1 and C1... (src/mediation/resolver_v2.look_label).
  g. second look (SecondLookCallV2), ONLY for Indeterminate, started by the OrchestratorV2, and ONLY for the
     situational conditions still not_stated (R5): the description + ONLY the other retrieved paragraphs of the SAME
     article as the passage being checked (none if there are none; fix sameart, 29 Oct 2026: with all retrieved
     passages the call was distracted by unrelated rules). Same quote check. Roles and scope are never looked at again.
Every IF item records "decided_by": "code rule", "first look" or "second look" (None while not_stated).
The final label (with exceptions) is decided by ResolverV2 (src/mediation/resolver_v2.py), not here.
A1, the role meanings, the role facts and the scope texts are fixed in config.yaml, the same for every case, and never reach the
generator (only requirements of Applicable rules are passed on).

Each call is its own BaseAgent subclass (own prompt file, own schema, the same JSON check and one retry).
ApplicabilityAgentV2 runs them in order and does the code steps.
"""

import functools
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.mediation.applicability_resolver import INDETERMINATE
from src.mediation.quote_checker import match_quote
from src.mediation.resolver_v2 import look_label

SPLIT_INVALID = "Split invalid"
Status = Literal["confirmed", "not_stated", "contradicted"]


# ---------- schemas ----------

def article_of(passage_id: str) -> str:
    """The article part of a passage id: "GDPR-Art13-2-a" -> "GDPR-Art13"."""
    match = re.match(r"^(.+?-Art\d+)(?:-|$)", passage_id)
    return match.group(1) if match else passage_id


def same_article_passages(passage_id: str, case_passages: list[dict]) -> list[dict]:
    """The other retrieved paragraphs of the same article as this passage (in rank order), the only extra context of
    the second look (fix sameart). Empty if there are none."""
    article = article_of(passage_id)
    return [p for p in case_passages if p["passage_id"] != passage_id and article_of(p["passage_id"]) == article]


def law_roles(roles_config: dict, passage_id: str) -> dict:
    """The role list of the passage's law (config.yaml c3_v2.roles), chosen by passage id prefix; "default" (the GDPR
    list of round 3) for every prefix that has no list of its own."""
    for prefix, law in roles_config.items():
        if prefix != "default" and passage_id.startswith(prefix):
            return law
    return roles_config["default"]


# Role binding (fix F2, 29 Oct 2026): the actor a role name refers to in the described process. The organisation phrase
# is the one the role facts use (c3_v2.role_facts); the customer is the other side of the customer scope item.
ORGANISATION = "the organisation running the described process"
CUSTOMER = "its customer"


def role_binding(duty_roles: list[str], rules: dict) -> dict[str, str]:
    """{role name: actor} for one passage. rules: the role list of its law (config.yaml c3_v2.roles).
    A role the rule places its duty on (R1) that code decides by a role fact or by assumption A1 -> the organisation
    (exactly what R1 checks); a role decided by the scope item (the customer side) -> its customer. Every other role
    is left as it is."""
    binding = {r: ORGANISATION for r in dict.fromkeys(duty_roles) if rules[r]["decide"] in ("fact", "assumed")}
    binding.update({name: CUSTOMER for name, rule in rules.items()
                    if rule["decide"] == "scope" and name not in binding})
    return binding


def bind_roles(text: str, binding: dict[str, str]) -> str:
    """Replace each bound role name in an item text (with a leading "the" / "a" / "an", whole words, any case) by its
    actor. Longer role names first, so "service provider" is replaced before a shorter name inside it."""
    for role in sorted(binding, key=len, reverse=True):
        text = re.sub(rf"\b(?:(?:the|a|an)\s+)?{re.escape(role)}\b", binding[role], text, flags=re.IGNORECASE)
    return text


# Exception splitting (fix exc, 30 Oct 2026): words that start an exception inside an IF item.
EXCEPTION_MARKERS = ("unless", "except where", "except when")
EXCEPTION_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in EXCEPTION_MARKERS) + r")\b", re.IGNORECASE)


def split_exceptions(conditions: list[str]) -> tuple[list[dict], list[dict]]:
    """The situational IF items C1, C2, ... and the exceptions split off them by code. An IF item with an exception
    marker (EXCEPTION_MARKERS) is cut at the first marker: the part before stays the IF item, the clause from the
    marker on becomes an exception (numbered by the caller after the split's own exceptions). Both keep the
    model's item as "original_text". An item that starts with a marker becomes an exception only."""
    situational, split_off = [], []
    for text in conditions:
        match = EXCEPTION_PATTERN.search(text)
        if not match:
            situational.append({"text": text})
            continue
        before = text[:match.start()].strip().rstrip(",;:").strip()
        if before:
            situational.append({"text": before, "original_text": text})
        split_off.append({"text": text[match.start():].strip(), "original_text": text,
                          "split_from": f"C{len(situational)}" if before else None})
    return ([{"id": f"C{i}", "kind": "situation", **c} for i, c in enumerate(situational, 1)], split_off)


@functools.cache
def split_schema(role_names: tuple[str, ...]) -> type[BaseModel]:
    """The schema of the split's answer, with "roles" limited to the role names of one law."""

    class SplitOutputV2(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        roles: list[Literal[role_names]] = Field(min_length=1, description="Who the rule places its duty on")
        conditions: list[str] = Field(alias="if", description="Every situational condition under which the rule "
                                                              "applies (when it applies, never a role and never what "
                                                              "must be done); empty list if none")
        then: str = Field(description="What the rule requires to be done when it applies")
        exceptions: list[str] = Field(description="Situations the rule itself names in which it does not apply; "
                                                  "empty list if none")

    return SplitOutputV2


class ItemCheck(BaseModel):
    """Field order (fix C, 29 Oct 2026, oracle O2 in scripts/oracle_o2.py): the model first copies the closest
    sentence of the description, then decides the status and the quote (search first, then judge)."""
    id: str = Field(description="The id of the item, as given in the list")
    closest_sentence: str | None = Field(description="The sentence of the process description that comes closest "
                                                     "to the statement, copied word for word, or null if none")
    status: Status = Field(description="confirmed, contradicted or not_stated, judged from the description only")
    quote: str | None = Field(description="Exact words copied from the process description, or null for not_stated")


class CheckOutputV2(BaseModel):
    results: list[ItemCheck] = Field(description="One result for every item of the list")


# ---------- the three calls ----------

class SplitCallV2(BaseAgent):
    prompt_key = "applicability_split_prompt_v2"
    json_format = True

    def __init__(self, llm, logger, max_retries: int | None = None):
        super().__init__(llm, logger, max_retries)
        self.roles_config = load_config()["c3_v2"]["roles"]

    def build_prompt(self, passage_id: str, passage_text: str) -> str:
        """The role list in the prompt and the allowed role names in the schema are those of the passage's law."""
        law = law_roles(self.roles_config, passage_id)
        self.output_schema = split_schema(tuple(law["names"]))   # also used by parse_output
        role_lines = ",\n".join(f'  - "{name}": {role["means"]}' for name, role in law["names"].items()) + "."
        return self.template.format(schema=self.schema_text(), role_lines=role_lines,
                                    pair_example=law["pair_example"], passage=f"[{passage_id}] {passage_text.strip()}")


class ItemCheckCall(BaseAgent):
    """Shared by the check-IF call and the second look: the answer must have exactly one result per item id."""
    output_schema = CheckOutputV2
    json_format = True

    def parse_output(self, raw_output: str):
        parsed, error = super().parse_output(raw_output)
        if parsed is not None:
            ids = [r.id for r in parsed.results]
            if sorted(ids) != sorted(self.expected_ids):
                return None, f"the results must have exactly these ids, once each: {', '.join(self.expected_ids)}"
        return parsed, error

    def item_lines(self, items: list[dict], key: str = "text") -> str:
        """key: the item field whose text is sent ("text_sent" for the check-IF call and the second look, with "text"
        as fallback)."""
        self.expected_ids = [item["id"] for item in items]   # checked by parse_output
        return "\n".join(f'{item["id"]}: {item.get(key, item["text"])}' for item in items)


class CheckIfCallV2(ItemCheckCall):
    prompt_key = "applicability_check_prompt_v2"

    def build_prompt(self, description: str, items: list[dict]) -> str:
        """C and E items are sent with their role names bound (text_sent, fix F2); the other items as they are."""
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    items=self.item_lines(items, key="text_sent"))


class SecondLookCallV2(ItemCheckCall):
    prompt_key = "applicability_second_look_prompt_v2"

    def build_prompt(self, description: str, passages: list[dict], passage_id: str, items: list[dict]) -> str:
        """passages: the other retrieved paragraphs of the same article (dicts with passage_id and text, in rank order;
        may be empty). The items are sent with the same role-bound text_sent as in the check-IF call (fix 2)."""
        passage_lines = "\n\n".join(f"[{p['passage_id']}] {p['text'].strip()}" for p in passages)
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    passages=passage_lines, passage_id=passage_id, items=self.item_lines(items, key="text_sent"))


# ---------- the agent ----------

class ApplicabilityAgentV2:
    """Runs split -> check-IF -> quote check -> first look, and the second look when the orchestrator asks."""

    def __init__(self, llm, logger, max_retries: int | None = None, config: dict | None = None):
        config = config or load_config()
        self.split_call = SplitCallV2(llm, logger, max_retries)
        self.check_call = CheckIfCallV2(llm, logger, max_retries)
        self.second_look_call = SecondLookCallV2(llm, logger, max_retries)
        settings = config["c3_v2"]
        words = "|".join(re.escape(w) for w in settings["obligation_words"])
        self.obligation_pattern = re.compile(rf"\b({words})\b", re.IGNORECASE)
        self.roles_config = settings["roles"]          # law -> role -> how code decides it (R3)
        self.controller_assumption = settings["controller_assumption"]   # A1
        self.role_facts = settings["role_facts"]       # P1, T1, D1, D2: facts that decide a role
        self.scope_conditions = settings["scope_conditions"]   # passage id prefix -> scope statement (R2)

    def first_look(self, case_id: str, description: str, passage_id: str, passage_text: str) -> dict:
        """Steps a-f. Returns the applicability record for the audit trail. If a call has no valid answer after its
        retry, "failed_step" names it ("split" or "check") and "label" is None."""
        record = {"split": None, "split_valid": None, "rejected_if": [], "check": None, "conditions": [],
                  "role_facts": [], "exceptions": [], "first_look_label": None, "second_look": None, "look": "first",
                  "second_look_decided": None, "label": None, "failed_step": None, "note": None}

        # a. split (law text only) + code check for obligation words
        split = self.split_call.run(case_id, passage_id=passage_id, passage_text=passage_text)
        if split is None:
            record["failed_step"] = "split"
            return record
        record["split"] = split.model_dump(by_alias=True)
        record["rejected_if"] = [c for c in split.conditions if self.obligation_pattern.search(c)]
        record["split_valid"] = not record["rejected_if"]
        if not record["split_valid"]:
            record["label"] = SPLIT_INVALID
            return record

        # b. the IF list by code: role item + scope item + situational conditions (R1, R2)
        role_item = {"id": "R1", "kind": "role", "text": "the duty is on: " + " or ".join(dict.fromkeys(split.roles)),
                     "roles": [{"role": r} for r in dict.fromkeys(split.roles)]}
        scope = [{"id": "S1", "kind": "scope", "text": text} for prefix, text in self.scope_conditions.items()
                 if passage_id.startswith(prefix)]
        situational, split_off = split_exceptions(split.conditions)
        record["conditions"] = [role_item] + scope + situational
        rules = law_roles(self.roles_config, passage_id)["names"]
        fact_ids = dict.fromkeys(rules[r["role"]]["fact"] for r in role_item["roles"]
                                 if rules[r["role"]]["decide"] == "fact")
        record["role_facts"] = [{"id": f, "kind": "role_fact", "text": self.role_facts[f]} for f in fact_ids]
        record["exceptions"] = [{"id": f"E{i}", "text": t} for i, t in enumerate(split.exceptions, 1)]
        for i, e in enumerate(split_off, len(record["exceptions"]) + 1):
            record["exceptions"].append({"id": f"E{i}", **e})
        record["role_binding"] = binding = role_binding(split.roles, rules)
        for item in situational + record["exceptions"]:
            item["text_sent"] = bind_roles(item["text"], binding)

        # c. check-IF call, d. quote check (only the items that need a quote from the description)
        items = scope + record["role_facts"] + situational + record["exceptions"]
        if items:
            check = self.check_call.run(case_id, description=description, items=items)
            if check is None:
                record["failed_step"] = "check"
                return record
            record["check"] = check.model_dump()
            self.verify(items, check, description, "first look")

        # e. roles by code (R3), f. first look
        self.decide_roles(role_item, record["role_facts"], scope, rules)
        record["first_look_label"] = record["label"] = look_label([c["status"] for c in record["conditions"]])
        return record

    def decide_roles(self, role_item: dict, role_facts: list[dict], scope: list[dict], rules: dict) -> None:
        """Step e (R3): the status of every role and of the role item R1, by code only. rules: the role list of the
        passage's law (config.yaml c3_v2.roles); role_facts and scope already have their checked status."""
        facts = {f["id"]: f for f in role_facts}
        source = {}                                    # role -> the checked item that confirmed it (role fact or S1)
        for r in role_item["roles"]:
            rule = rules[r["role"]]
            if rule["decide"] == "assumed":
                r.update(status="confirmed", decided_by="code rule", reason="A1: " + self.controller_assumption)
            elif rule["decide"] == "fact":
                fact = facts[rule["fact"]]
                if fact["status"] == "confirmed":
                    r.update(status="confirmed", decided_by="first look",
                             reason=f"{fact['id']} confirmed with a checked quote")
                    source[r["role"]] = fact
                elif rule["otherwise"] == "contradicted":
                    r.update(status="contradicted", decided_by="code rule",
                             reason=f"{fact['id']} not confirmed with a checked quote; A1: " + self.controller_assumption)
                elif fact["status"] == "contradicted":
                    r.update(status="contradicted", decided_by="first look",
                             reason=f"{fact['id']} contradicted with a checked quote")
                else:
                    r.update(status="not_stated", decided_by=None, reason=f"{fact['id']} not stated")
            elif rule["decide"] == "scope":
                s1 = scope[0] if scope else {"status": "not_stated", "decided_by": None}
                r.update(status=s1["status"], decided_by=s1["decided_by"], reason=f"the scope item S1 is {s1['status']}")
                if s1["status"] == "confirmed":
                    source[r["role"]] = s1
            elif rule["decide"] == "contradicted":
                r.update(status="contradicted", decided_by="code rule", reason="a public body is not a business")
            else:
                r.update(status="not_stated", decided_by=None, reason="this role is not decided by code")
        statuses = [r["status"] for r in role_item["roles"]]
        first = next((r for r in role_item["roles"] if r["status"] == "confirmed"), None)
        if first:
            role_item.update(status="confirmed", decided_by=first["decided_by"])
        elif all(s == "contradicted" for s in statuses):
            by_code = all(r["decided_by"] == "code rule" for r in role_item["roles"])
            role_item.update(status="contradicted", decided_by="code rule" if by_code else "first look")
        else:
            role_item.update(status="not_stated", decided_by=None)
        # a role confirmed through a role fact or S1 keeps that item's checked quote, so ResolverV2 counts it as
        # confirmed (bug fix 1)
        if first and first["role"] in source:
            role_item.update(quote=source[first["role"]]["quote"], quote_found=True, downgraded=False)
        else:
            role_item.update(quote=None, quote_found=None, downgraded=False)

    def open_conditions(self, record: dict) -> list[dict]:
        """The situational IF conditions that are still not_stated (input of the second look, R5)."""
        return [c for c in record["conditions"] if c["kind"] == "situation" and c["status"] == "not_stated"]

    def second_look(self, case_id: str, description: str, record: dict, passage_id: str,
                    case_passages: list[dict]) -> dict:
        """Step e, for an Indeterminate record with open conditions. Updates and returns the record; if the call has
        no valid answer after its retry, "failed_step" is "second_look"."""
        open_items = self.open_conditions(record)
        record["look"] = "second"
        answer = self.second_look_call.run(case_id, description=description,
                                           passages=same_article_passages(passage_id, case_passages),
                                           passage_id=passage_id, items=open_items)
        if answer is None:
            record["failed_step"] = "second_look"
            return record
        record["second_look"] = answer.model_dump()
        for c in open_items:
            c["first_look_status"] = c["status"]
        self.verify(open_items, answer, description, "second look")

        label = look_label([c["status"] for c in record["conditions"]])
        record["second_look_decided"] = label != INDETERMINATE
        record["label"] = label
        return record

    def verify(self, items: list[dict], answer: CheckOutputV2, description: str, look: str) -> None:
        """Step d: copy each item's answer into it; a confirmed or contradicted status needs a quote that is really in
        the description, otherwise it becomes not_stated. look ("first look" / "second look") is recorded as
        decided_by of a status that stays confirmed or contradicted."""
        by_id = {r.id: r for r in answer.results}
        for item in items:
            result = by_id[item["id"]]
            found, canonical = match_quote(result.quote, description)   # None = no quote given
            downgraded = result.status != "not_stated" and not found
            status = "not_stated" if downgraded else result.status
            item.update(status=status, original_status=result.status, quote=result.quote, quote_found=found,
                        quote_canonical=canonical, downgraded=downgraded, decided_by=look if status != "not_stated" else None)
