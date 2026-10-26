"""ApplicabilityAgent v2 (C3 v2, box 2): do the conditions of a relevant rule hold for this process?

v1 (src/agents/applicability_agent.py, frozen for Study 1) asked one call to split the rule AND check it against the
description; it listed obligations ("the trader shall provide ...") as conditions, so a rule could almost never be
Applicable (Problem 2 in docs/C3_V2_DEVELOPMENT.md). v2 makes the split its own call that sees the law text only.

Steps for one passage kept by RelevanceAgentV2:
  a. split call (SplitCallV2, law text only)  -> {"if": [...], "then": "...", "exceptions": [...]}
     Code rejects the split if an IF item contains an obligation word (config.yaml c3_v2.obligation_words:
     must / shall / is required to) -> label "Split invalid", nothing else runs.
  b. check-IF call (CheckIfCallV2: the description + this passage's IF list and exceptions, not the law text)
     -> each item confirmed / not_stated / contradicted, with a quote from the description.
  c. code quote check (QuoteChecker): a confirmed or contradicted item whose quote is missing or not found in the
     description becomes not_stated (recorded as downgraded).
  d. first look: the label from the IF statuses (src/mediation/resolver_v2.look_label).
  e. second look (SecondLookCallV2), ONLY for Indeterminate, started by the OrchestratorV2: the description + ALL 5
     retrieved passages of the case + the IF conditions still open. Same quote check. If the new statuses decide the
     label (Applicable or Not applicable) it is used; otherwise the rule stays Indeterminate. look = "second".
An empty IF list is valid but gives Indeterminate without a check call (nothing can confirm the rule).
The final label (with exceptions) is decided by ResolverV2 (src/mediation/resolver_v2.py), not here.

Each call is its own BaseAgent subclass (own prompt file, own schema, the same JSON check and one retry).
ApplicabilityAgentV2 runs them in order and does the code steps.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.mediation.applicability_resolver import INDETERMINATE
from src.mediation.quote_checker import QuoteChecker
from src.mediation.resolver_v2 import look_label

SPLIT_INVALID = "Split invalid"
Status = Literal["confirmed", "not_stated", "contradicted"]


# ---------- schemas ----------

class SplitOutputV2(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    conditions: list[str] = Field(alias="if", description="The conditions under which the rule applies (when it "
                                                          "applies, never what must be done); empty list if none")
    then: str = Field(description="What the rule requires to be done when it applies")
    exceptions: list[str] = Field(description="Situations the rule itself names in which it does not apply; empty "
                                              "list if none")


class ItemCheck(BaseModel):
    id: str = Field(description="The id of the item, as given in the list")
    status: Status = Field(description="confirmed, contradicted or not_stated, judged from the description only")
    quote: str | None = Field(description="Exact words copied from the process description, or null for not_stated")


class CheckOutputV2(BaseModel):
    results: list[ItemCheck] = Field(description="One result for every item of the list")


# ---------- the three calls ----------

class SplitCallV2(BaseAgent):
    output_schema = SplitOutputV2
    prompt_key = "applicability_split_prompt_v2"

    def build_prompt(self, passage_id: str, passage_text: str) -> str:
        return self.template.format(schema=self.schema_text(), passage=f"[{passage_id}] {passage_text.strip()}")


class ItemCheckCall(BaseAgent):
    """Shared by the check-IF call and the second look: the answer must have exactly one result per item id."""
    output_schema = CheckOutputV2

    def parse_output(self, raw_output: str):
        parsed, error = super().parse_output(raw_output)
        if parsed is not None:
            ids = [r.id for r in parsed.results]
            if sorted(ids) != sorted(self.expected_ids):
                return None, f"the results must have exactly these ids, once each: {', '.join(self.expected_ids)}"
        return parsed, error

    def item_lines(self, items: list[dict]) -> str:
        self.expected_ids = [item["id"] for item in items]   # checked by parse_output
        return "\n".join(f'{item["id"]}: {item["text"]}' for item in items)


class CheckIfCallV2(ItemCheckCall):
    prompt_key = "applicability_check_prompt_v2"

    def build_prompt(self, description: str, items: list[dict]) -> str:
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    items=self.item_lines(items))


class SecondLookCallV2(ItemCheckCall):
    prompt_key = "applicability_second_look_prompt_v2"

    def build_prompt(self, description: str, passages: list[dict], passage_id: str, items: list[dict]) -> str:
        """passages: all retrieved passages of the case (dicts with passage_id and text, in rank order)."""
        passage_lines = "\n\n".join(f"[{p['passage_id']}] {p['text'].strip()}" for p in passages)
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    passages=passage_lines, passage_id=passage_id, items=self.item_lines(items))


# ---------- the agent ----------

class ApplicabilityAgentV2:
    """Runs split -> check-IF -> quote check -> first look, and the second look when the orchestrator asks."""

    def __init__(self, llm, logger, max_retries: int | None = None, config: dict | None = None):
        config = config or load_config()
        self.split_call = SplitCallV2(llm, logger, max_retries)
        self.check_call = CheckIfCallV2(llm, logger, max_retries)
        self.second_look_call = SecondLookCallV2(llm, logger, max_retries)
        words = "|".join(re.escape(w) for w in config["c3_v2"]["obligation_words"])
        self.obligation_pattern = re.compile(rf"\b({words})\b", re.IGNORECASE)
        self.quote_checker = QuoteChecker()

    def first_look(self, case_id: str, description: str, passage_id: str, passage_text: str) -> dict:
        """Steps a-d. Returns the applicability record for the audit trail. If a call has no valid answer after its
        retry, "failed_step" names it ("split" or "check") and "label" is None."""
        record = {"split": None, "split_valid": None, "rejected_if": [], "check": None, "conditions": [],
                  "exceptions": [], "first_look_label": None, "second_look": None, "look": "first",
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

        record["conditions"] = [{"id": f"C{i}", "text": t} for i, t in enumerate(split.conditions, 1)]
        record["exceptions"] = [{"id": f"E{i}", "text": t} for i, t in enumerate(split.exceptions, 1)]
        if not split.conditions:
            record["first_look_label"] = record["label"] = INDETERMINATE
            record["note"] = "no IF conditions: nothing can confirm the rule"
            for e in record["exceptions"]:
                e.update(status="not_stated", original_status=None, quote=None, quote_found=None, downgraded=False)
            return record

        # b. check-IF call, c. quote check
        items = record["conditions"] + record["exceptions"]
        check = self.check_call.run(case_id, description=description, items=items)
        if check is None:
            record["failed_step"] = "check"
            return record
        record["check"] = check.model_dump()
        self.verify(items, check, description)

        # d. first look
        record["first_look_label"] = record["label"] = look_label([c["status"] for c in record["conditions"]])
        return record

    def open_conditions(self, record: dict) -> list[dict]:
        """The IF conditions the first look could not confirm (input of the second look)."""
        return [c for c in record["conditions"] if c["status"] != "confirmed"]

    def second_look(self, case_id: str, description: str, record: dict, passage_id: str,
                    case_passages: list[dict]) -> dict:
        """Step e, for an Indeterminate record with open conditions. Updates and returns the record; if the call has
        no valid answer after its retry, "failed_step" is "second_look"."""
        open_items = self.open_conditions(record)
        record["look"] = "second"
        answer = self.second_look_call.run(case_id, description=description, passages=case_passages,
                                           passage_id=passage_id, items=open_items)
        if answer is None:
            record["failed_step"] = "second_look"
            return record
        record["second_look"] = answer.model_dump()
        for c in open_items:
            c["first_look_status"] = c["status"]
        self.verify(open_items, answer, description)

        label = look_label([c["status"] for c in record["conditions"]])
        record["second_look_decided"] = label != INDETERMINATE
        record["label"] = label
        return record

    def verify(self, items: list[dict], answer: CheckOutputV2, description: str) -> None:
        """Step c: copy each item's answer into it; a confirmed or contradicted status needs a quote that is really in
        the description, otherwise it becomes not_stated."""
        by_id = {r.id: r for r in answer.results}
        for item in items:
            result = by_id[item["id"]]
            found = self.quote_checker.found(result.quote, description)   # None = no quote given
            downgraded = result.status != "not_stated" and not found
            item.update(status="not_stated" if downgraded else result.status, original_status=result.status,
                        quote=result.quote, quote_found=found, downgraded=downgraded)
