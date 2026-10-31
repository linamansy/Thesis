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
     Substantive duty holder (D1, design round 1, 31 Oct 2026), by code: if the passage says "Member State(s) shall
     ensure ...", the duty is on the first role of the law's role list (config.yaml c3_v2.roles, never "public body"
     or "other") named after "shall ensure"; with no such role the split's roles are kept without "public body" (or
     "other" if none is left). The Member State only passes the duty on; it is never the duty holder.
     AND / OR (D4a, design round 1): "if" is a list of groups that must all hold, each with logic "all" (every item)
     or "any" (alternatives: "any of", "one of the following", "or"). The items are numbered C1, C2, ... across the
     groups and keep their group id (G1, ...) and logic; an "any" group counts as one unit for the label
     (src/mediation/resolver_v2.if_units). A plain text in "if" is read as an "all" group of one item.
     Sub-rules (D4b, design round 1): a special-case clause ("In the case of ...", "Where ..." introducing a
     different duty) is not part of the main rule; the split gives it in "special_cases" with its own roles, IF
     groups and THEN. Each becomes a sub-rule (K1, K2, ...) that goes through steps b-h on its own (own check-IF
     call; no exceptions of its own besides split-off "unless" clauses) and gets its own label and requirement from
     the OrchestratorV2. D1 applies to the main rule only.
  b. the IF list is built by code (R1, R2): one role item R1 + the scope item S1 (config.yaml c3_v2.scope_conditions,
     for every passage of that law, e.g. GDPR) + every situational condition C1, C2, ...
     Exception splitting (fix exc, 30 Oct 2026): an IF item containing "unless", "except where" or "except when" is
     cut by code; the part before stays the C item, the clause from the marker on becomes an extra exception E item
     (both keep the model's item as "original_text"). An exception that is not_stated does not block the rule.
  c. check-IF call (CheckIfCallV2: the description + the items that need a quote, not the law text): S1, the role
     facts of the named roles (c3_v2.role_facts: P1 for a processor, T1 for a trader / seller / service provider, D1
     for a debtor, D2 for a creditor), C1..., the exceptions E1... -> each item confirmed / not_stated / contradicted,
     with 1-3 quotes from the description (fix multiquote, 30 Oct 2026: before, one quote; a fact spread over two
     sentences could not be shown).
     Role binding (fix F2, 29 Oct 2026): in the C and E items sent to this call, a role name is replaced by the actor
     it refers to in the process (role_binding: a duty role decided by a role fact or A1 -> the organisation running
     the described process; a role decided by the scope item -> its customer; other roles unchanged). The saved
     item keeps its original "text" and records the sent "text_sent". The second look gets the same text_sent (fix 2).
  d. code quote check (match_quote, tolerant since fix tolquote, 30 Oct 2026: plural -s, at most 1 extra word per 6
     quote words from 3 words on, shorter quotes exactly (fix shortquote)), for EACH quote of the item (fix
     multiquote): a confirmed or contradicted item with no quote found in the description becomes not_stated (recorded
     as downgraded). The matched exact spans of the quotes that were found are saved as quotes_canonical (a list).
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
  h. verifier (VerifierCallV2, fix verifier, 30 Oct 2026), after the quote check of the first and of the second look:
     every item that is still confirmed or contradicted gets one more call with ONLY its statement as sent (text_sent)
     and ALL its canonical quotes together (fix multiquote): "Do these sentences, on their own and together, state
     that the statement is true / false?". "no" ->
     not_stated (downgrade_cause "verifier rejected"). It runs before the roles and the look label are decided, so a
     rejected item can still be looked at again by the second look.
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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.mediation.applicability_resolver import INDETERMINATE
from src.mediation.quote_checker import match_quote
from src.mediation.resolver_v2 import look_label

SPLIT_INVALID = "Split invalid"
Status = Literal["confirmed", "not_stated", "contradicted"]
MAX_QUOTES = 3   # quotes per item (fix multiquote); fixed by the task, not a study parameter


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


# D1 (design round 1): "Member States shall ensure (that) ..." passes a duty on to someone named after it.
SHALL_ENSURE = re.compile(r"\bMember States?\s+shall\s+ensure\b", re.IGNORECASE)
NOT_A_DUTY_HOLDER = ("public body", "other")


def substantive_duty_holder(passage_text: str, role_names) -> tuple[bool, str | None]:
    """(True, role) if the passage says "Member State(s) shall ensure": role = the first of role_names (without
    NOT_A_DUTY_HOLDER) named after it (whole words, plural -s, any case), or None if none is named.
    (False, None) if the passage has no "shall ensure"."""
    match = SHALL_ENSURE.search(passage_text)
    if not match:
        return False, None
    rest = passage_text[match.end():]
    found = [(m.start(), name) for name in role_names if name not in NOT_A_DUTY_HOLDER
             for m in [re.search(rf"\b{re.escape(name)}s?\b", rest, re.IGNORECASE)] if m]
    return True, (min(found)[1] if found else None)


def duty_roles(split_roles: list[str], passage_text: str, role_names) -> tuple[list[str], dict | None]:
    """The roles the rule places its duty on, after D1, and the D1 record (None if D1 does not apply)."""
    roles = list(dict.fromkeys(split_roles))
    applies, holder = substantive_duty_holder(passage_text, role_names)
    if not applies:
        return roles, None
    new = [holder] if holder else ([r for r in roles if r != "public body"] or ["other"])
    return new, {"rule": "D1 Member States shall ensure", "split_roles": roles, "role_found": holder, "roles": new}


# Exception splitting (fix exc, 30 Oct 2026): words that start an exception inside an IF item.
EXCEPTION_MARKERS = ("unless", "except where", "except when")
EXCEPTION_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in EXCEPTION_MARKERS) + r")\b", re.IGNORECASE)


def split_exceptions(conditions: list) -> tuple[list[dict], list[dict]]:
    """The situational IF items C1, C2, ... and the exceptions split off them by code. An IF item with an exception
    marker (EXCEPTION_MARKERS) is cut at the first marker: the part before stays the IF item, the clause from the
    marker on becomes an exception (numbered by the caller after the split's own exceptions). Both keep the
    model's item as "original_text". An item that starts with a marker becomes an exception only.
    conditions: texts, or dicts with "text" and other keys (group, logic: D4a), which the IF item keeps."""
    situational, split_off = [], []
    for condition in conditions:
        text = condition if isinstance(condition, str) else condition["text"]
        extra = {} if isinstance(condition, str) else {k: v for k, v in condition.items() if k != "text"}
        match = EXCEPTION_PATTERN.search(text)
        if not match:
            situational.append({"text": text, **extra})
            continue
        before = text[:match.start()].strip().rstrip(",;:").strip()
        if before:
            situational.append({"text": before, "original_text": text, **extra})
        split_off.append({"text": text[match.start():].strip(), "original_text": text,
                          "split_from": f"C{len(situational)}" if before else None})
    return ([{"id": f"C{i}", "kind": "situation", **c} for i, c in enumerate(situational, 1)], split_off)


class IfGroup(BaseModel):
    # D4a (design round 1): a group of IF items with its logic. The groups of a rule must all hold. (A comment, not a
    # docstring: JSON agents send their schema without class descriptions, fix nodoc.)
    logic: Literal["all", "any"] = Field(description='"all": every item of the group must hold; "any": the items are '
                                                     'alternatives and at least one must hold ("any of", "one of the '
                                                     'following", "or")')
    items: list[str] = Field(min_length=1, description="The conditions of the group, each a short statement in the "
                                                       "words of the rule")


def as_groups(value):
    """A plain text in "if" (the format before D4a) is read as a group of one item that must hold."""
    if isinstance(value, list):
        return [{"logic": "all", "items": [v]} if isinstance(v, str) else v for v in value]
    return value


def flat_items(groups: list[IfGroup]) -> list[dict]:
    """The IF items of the split in order, each with its group id (G1, G2, ...) and the group's logic."""
    return [{"text": text, "group": f"G{g}", "logic": group.logic}
            for g, group in enumerate(groups, 1) for text in group.items]


@functools.cache
def split_schema(role_names: tuple[str, ...]) -> type[BaseModel]:
    """The schema of the split's answer, with "roles" limited to the role names of one law."""

    class SpecialCaseV2(BaseModel):
        # D4b (design round 1): a special-case clause ("In the case of ...", "Where ..." with a different duty) as its
        # own sub-rule. (No docstring: JSON agents send their schema without class descriptions, fix nodoc.)
        model_config = ConfigDict(populate_by_name=True)
        clause: str = Field(description='The words of the rule that start the special case, copied (for example "In '
                                        'the case of ..." or "Where ...")')
        roles: list[Literal[role_names]] = Field(min_length=1, description="Who the special case places its duty on")
        conditions: list[IfGroup] = Field(alias="if", description="The conditions of the special case, in groups that "
                                                                  "must all hold")
        then: str = Field(description="What the special case requires to be done")

        @field_validator("conditions", mode="before")
        @classmethod
        def _groups(cls, value):
            return as_groups(value)

    class SplitOutputV2(BaseModel):
        model_config = ConfigDict(populate_by_name=True)
        roles: list[Literal[role_names]] = Field(min_length=1, description="Who the rule places its duty on")
        conditions: list[IfGroup] = Field(alias="if", description="Every situational condition under which the rule "
                                                                  "applies (when it applies, never a role and never "
                                                                  "what must be done), in groups that must all hold; "
                                                                  "empty list if none")

        @field_validator("conditions", mode="before")
        @classmethod
        def _groups(cls, value):
            return as_groups(value)

        then: str = Field(description="What the rule requires to be done when it applies")
        exceptions: list[str] = Field(description="Situations the rule itself names in which it does not apply; "
                                                  "empty list if none")
        special_cases: list[SpecialCaseV2] = Field(default_factory=list,
                                                   description="Clauses of the rule that start a special case with a "
                                                               "different duty, each as its own rule; empty list if "
                                                               "none")

    return SplitOutputV2


class ItemCheck(BaseModel):
    """Field order (fix C, 29 Oct 2026, oracle O2 in scripts/oracle_o2.py): the model first copies the closest
    sentence of the description, then decides the status and the quotes (search first, then judge).
    quotes (fix multiquote, 30 Oct 2026): 1-3 sentences instead of one quote, so a fact stated over two sentences can
    be shown; each is checked by code on its own (ApplicabilityAgentV2.verify)."""
    id: str = Field(description="The id of the item, as given in the list")
    closest_sentence: str | None = Field(description="The sentence of the process description that comes closest "
                                                     "to the statement, copied word for word, or null if none")
    status: Status = Field(description="confirmed, contradicted or not_stated, judged from the description only")
    quotes: list[str] = Field(max_length=MAX_QUOTES,
                              description="1 to 3 sentences copied word for word from the process description that "
                                          "together show the status; empty list for not_stated")


class CheckOutputV2(BaseModel):
    results: list[ItemCheck] = Field(description="One result for every item of the list")


class VerifierOutputV2(BaseModel):
    answer: Literal["yes", "no"] = Field(description="yes if the sentence on its own states it, otherwise no")
    reason: str = Field(description="One line of reason")


# ---------- the calls ----------

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


class VerifierCallV2(BaseAgent):
    prompt_key = "applicability_verifier_prompt_v2"
    output_schema = VerifierOutputV2
    json_format = True

    def build_prompt(self, statement: str, quotes: list[str], truth: str) -> str:
        """quotes: the item's canonical quotes, all sent together (fix multiquote), one per line.
        truth: "true" for a confirmed item, "false" for a contradicted one."""
        sentences = "\n".join(f"- {q.strip()}" for q in quotes)
        return self.template.format(schema=self.schema_text(), sentences=sentences, statement=statement.strip(),
                                    truth=truth)


# ---------- the agent ----------

def rule_record() -> dict:
    """The fields of one rule's applicability record (the main rule of a passage, or a sub-rule, D4b)."""
    return {"check": None, "conditions": [], "role_facts": [], "exceptions": [], "role_binding": {},
            "first_look_label": None, "second_look": None, "look": "first", "second_look_decided": None,
            "label": None, "failed_step": None}


class ApplicabilityAgentV2:
    """Runs split -> check-IF -> quote check -> first look, and the second look when the orchestrator asks."""

    def __init__(self, llm, logger, max_retries: int | None = None, config: dict | None = None):
        config = config or load_config()
        self.split_call = SplitCallV2(llm, logger, max_retries)
        self.check_call = CheckIfCallV2(llm, logger, max_retries)
        self.second_look_call = SecondLookCallV2(llm, logger, max_retries)
        self.verifier_call = VerifierCallV2(llm, logger, max_retries)
        settings = config["c3_v2"]
        words = "|".join(re.escape(w) for w in settings["obligation_words"])
        self.obligation_pattern = re.compile(rf"\b({words})\b", re.IGNORECASE)
        self.roles_config = settings["roles"]          # law -> role -> how code decides it (R3)
        self.controller_assumption = settings["controller_assumption"]   # A1
        self.role_facts = settings["role_facts"]       # P1, T1, D1, D2: facts that decide a role
        self.scope_conditions = settings["scope_conditions"]   # passage id prefix -> scope statement (R2)

    def first_look(self, case_id: str, description: str, passage_id: str, passage_text: str) -> dict:
        """Steps a-f. Returns the applicability record for the audit trail. If a call has no valid answer after its
        retry, "failed_step" names it ("split" or "check") and "label" is None.
        Sub-rules (D4b): every special case of the split is evaluated like the main rule (steps b-f, its own check-IF
        call) into record["sub_rules"] (ids K1, K2, ...); a failed call of a sub-rule marks only that sub-rule."""
        record = {"split": None, "split_valid": None, "rejected_if": [], "duty_holder": None, **rule_record(),
                  "sub_rules": [], "note": None}

        # a. split (law text only) + code check for obligation words (main rule and special cases)
        split = self.split_call.run(case_id, passage_id=passage_id, passage_text=passage_text)
        if split is None:
            record["failed_step"] = "split"
            return record
        record["split"] = split.model_dump(by_alias=True)
        if_items = flat_items(split.conditions)
        texts = [c["text"] for c in if_items] + [c["text"] for sc in split.special_cases
                                                 for c in flat_items(sc.conditions)]
        record["rejected_if"] = [t for t in texts if self.obligation_pattern.search(t)]
        record["split_valid"] = not record["rejected_if"]
        if not record["split_valid"]:
            record["label"] = SPLIT_INVALID
            return record

        # D1: the substantive duty holder of a "Member States shall ensure" rule
        rules = law_roles(self.roles_config, passage_id)["names"]
        roles, record["duty_holder"] = duty_roles(split.roles, passage_text, rules)
        self.evaluate_rule(case_id, description, passage_id, record, roles, if_items, split.exceptions, rules)
        if record["failed_step"]:
            return record

        # D4b: each special case as its own sub-rule
        for k, special in enumerate(split.special_cases, 1):
            sub = {"id": f"K{k}", "clause": special.clause, "then": special.then, **rule_record(),
                   "resolution": None, "requirement": None, "label_cause": None, "error": None}
            self.evaluate_rule(case_id, description, passage_id, sub, list(dict.fromkeys(special.roles)),
                               flat_items(special.conditions), [], rules)
            record["sub_rules"].append(sub)
        return record

    def evaluate_rule(self, case_id: str, description: str, passage_id: str, rule: dict, roles: list[str],
                      if_items: list[dict], exceptions: list[str], rules: dict) -> None:
        """Steps b-f for one rule: the passage's main rule, or one sub-rule (D4b). Fills rule's conditions,
        role_facts, exceptions, role_binding, check, first_look_label and label; on a call with no valid answer,
        failed_step ("check" or "verifier"). if_items: flat_items of its IF groups; rules: the law's role list."""
        # b. the IF list by code: role item + scope item + situational conditions (R1, R2)
        role_item = {"id": "R1", "kind": "role", "text": "the duty is on: " + " or ".join(roles),
                     "roles": [{"role": r} for r in roles]}
        scope = [{"id": "S1", "kind": "scope", "text": text} for prefix, text in self.scope_conditions.items()
                 if passage_id.startswith(prefix)]
        situational, split_off = split_exceptions(if_items)
        rule["conditions"] = [role_item] + scope + situational
        fact_ids = dict.fromkeys(rules[r["role"]]["fact"] for r in role_item["roles"]
                                 if rules[r["role"]]["decide"] == "fact")
        rule["role_facts"] = [{"id": f, "kind": "role_fact", "text": self.role_facts[f]} for f in fact_ids]
        rule["exceptions"] = [{"id": f"E{i}", "text": t} for i, t in enumerate(exceptions, 1)]
        for i, e in enumerate(split_off, len(rule["exceptions"]) + 1):
            rule["exceptions"].append({"id": f"E{i}", **e})
        rule["role_binding"] = binding = role_binding(roles, rules)
        for item in situational + rule["exceptions"]:
            item["text_sent"] = bind_roles(item["text"], binding)

        # c. check-IF call, d. quote check (only the items that need a quote from the description)
        items = scope + rule["role_facts"] + situational + rule["exceptions"]
        if items:
            check = self.check_call.run(case_id, description=description, items=items)
            if check is None:
                rule["failed_step"] = "check"
                return
            rule["check"] = check.model_dump()
            if not self.verify(case_id, items, check, description, "first look"):
                rule["failed_step"] = "verifier"
                return

        # e. roles by code (R3), f. first look
        self.decide_roles(role_item, rule["role_facts"], scope, rules)
        rule["first_look_label"] = rule["label"] = look_label(rule["conditions"])

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
            role_item.update(quotes_canonical=source[first["role"]]["quotes_canonical"], quote_found=True,
                             downgraded=False)
        else:
            role_item.update(quotes_canonical=[], quote_found=None, downgraded=False)

    def open_conditions(self, record: dict) -> list[dict]:
        """The situational IF conditions that are still not_stated (input of the second look, R5), without the
        alternatives of an "any" group that already has a confirmed item (D4a: the group holds)."""
        held = {c["group"] for c in record["conditions"] if c.get("logic") == "any" and c["status"] == "confirmed"}
        return [c for c in record["conditions"] if c["kind"] == "situation" and c["status"] == "not_stated"
                and not (c.get("logic") == "any" and c["group"] in held)]

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
        if not self.verify(case_id, open_items, answer, description, "second look"):
            record["failed_step"] = "verifier"
            return record

        label = look_label(record["conditions"])
        record["second_look_decided"] = label != INDETERMINATE
        record["label"] = label
        return record

    def verify(self, case_id: str, items: list[dict], answer: CheckOutputV2, description: str, look: str) -> bool:
        """Step d: copy each item's answer into it; every quote is checked on its own (fix multiquote): a confirmed or
        contradicted status needs at least one quote that is really in the description, otherwise it becomes
        not_stated. quote_found: True if at least one quote was found, False if none of the given quotes was, None if
        no quote was given. look ("first look" / "second look") is recorded as decided_by of a status that stays
        confirmed or contradicted. Then step h (the verifier). Returns False if a
        verifier call has no valid answer after its retry."""
        by_id = {r.id: r for r in answer.results}
        for item in items:
            result = by_id[item["id"]]
            matches = [match_quote(q, description) for q in result.quotes]   # (None, None) = a quote without words
            canonical = list(dict.fromkeys(c for found, c in matches if found))
            found = bool(canonical) if any(f is not None for f, _ in matches) else None
            downgraded = result.status != "not_stated" and not found
            status = "not_stated" if downgraded else result.status
            item.update(status=status, original_status=result.status, quotes=result.quotes,
                        quotes_found=[f for f, _ in matches], quotes_canonical=canonical, quote_found=found,
                        downgraded=downgraded, decided_by=look if status != "not_stated" else None,
                        downgrade_cause="quote not found" if downgraded else None, verifier=None)
        return self.run_verifier(case_id, items)

    def run_verifier(self, case_id: str, items: list[dict]) -> bool:
        """Step h: one verifier call for every item that is still confirmed or contradicted. Input: the statement as
        sent (text_sent, else text) and all its canonical quotes, judged together (fix multiquote). "no" -> not_stated,
        downgrade_cause "verifier rejected"."""
        for item in items:
            if item["status"] not in ("confirmed", "contradicted"):
                continue
            truth = "true" if item["status"] == "confirmed" else "false"
            answer = self.verifier_call.run(case_id, statement=item.get("text_sent", item["text"]),
                                            quotes=item["quotes_canonical"], truth=truth)
            if answer is None:
                return False
            item["verifier"] = {"asked": truth, "answer": answer.answer, "reason": answer.reason}
            if answer.answer == "no":
                item.update(status="not_stated", downgraded=True, downgrade_cause="verifier rejected", decided_by=None)
        return True
