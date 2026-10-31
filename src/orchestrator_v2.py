"""OrchestratorV2: runs the four boxes of C3 v2 for each frozen passage of a case (docs/C3_V2_DEVELOPMENT.md).

For every passage of the case, in rank order:
  1. RelevanceAgentV2 + RelevanceV2Checker (code quote check)
     not final_relevant        -> label "Irrelevant", stop
  2. ApplicabilityAgentV2, first look: split (law only) -> check-IF -> quote check -> first-look label
     split with an obligation word in an IF item -> label "Split invalid", stop
     split with duty_type "none" (F1, design round 2: no duty or right of its own) -> label "No duty", stop
     Indeterminate with open IF conditions -> second look, with the description + only the other retrieved
     paragraphs of the same article (fix sameart)
  3. ResolverV2 (code): Applicable only if all IF conditions are confirmed AND no stated exception applies
  4. RequirementAgentV2, ONLY for Applicable: the THEN part -> 1-2 plain sentences tied to RelevanceAgentV2's process
     step, checked by code (RequirementCheckerV2); failing twice -> requirement_invalid, never passed on
  D5 (design round 1): "Applicable (conditional)" (role, scope and process facts confirmed, case events not
     contradicted) is treated like Applicable: requirement (which must keep each case event as "If/When ...") and
     block line.
  Sub-rules (D4b, design round 1): every special case the split gave (applicability "sub_rules", K1, ...) gets
     steps 2 (second look) to 4 on its own, after the main rule; its label, resolution and requirement are saved in
     the sub-rule. The passage label is the main rule's. A requirement of an Applicable sub-rule goes into the block
     like a main rule's (same line, same passage id). A failed call marks only that sub-rule "Mediation failed".
A call with no valid answer after its retry gives "Mediation failed" (failed_step names the call) and the next
passage is processed. LLMUnavailableError is passed on (the run stops and can be resumed), as in v1.

Knowledge block: confirmed requirements that passed the code check only (prompts/c3_block_template_v2.json).
Indeterminate, Not applicable, Split invalid, No duty, Irrelevant, requirement_invalid and failed passages are kept in the audit
trail and never passed on. With no requirement, the block is C1's text ("No domain knowledge provided.", prompts/c1_no_knowledge.txt), so the generator gets the same
layout as C1. The neutral label in front of the block is added by the generator, as for C1 and C2.

Audit trail (by code): output_dir/<case_id>.json with every intermediate step per passage (relevance answer and quote
check, split, check-IF answer, verified conditions and exceptions, first-look label, second-look answer, look,
resolver result, requirement) and the knowledge block. Fix B (28 Oct 2026) adds "label_cause": the CODE's reason for
the label (e.g. "law_quote not found", "requirement invalid: ..."), so a report never shows the model's own reason next
to a label the code decided. Written only when the case is complete; an existing file is
reused and no agent is called again (resumed run).
"""

import json
from pathlib import Path

from src.agents.applicability_agent_v2 import NO_DUTY, SPLIT_INVALID, ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.llm.base_llm import LLMUnavailableError
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE
from src.mediation.relevance_v2_checker import RelevanceV2Checker
from src.mediation.resolver_v2 import APPLICABLE_LABELS, ResolverV2
from src.orchestrator import IRRELEVANT, MEDIATION_FAILED


class OrchestratorV2:
    """Runs RelevanceAgentV2 -> ApplicabilityAgentV2 (+ second look) -> ResolverV2 -> RequirementAgentV2."""

    def __init__(self, relevance_agent: RelevanceAgentV2, applicability_agent: ApplicabilityAgentV2,
                 requirement_agent: RequirementAgentV2, frozen_cases: dict, output_dir: Path, block_template: dict,
                 no_knowledge_text: str):
        """block_template: src/prompt_texts.load_c3_block_template(config, "c3_block_template_v2");
        no_knowledge_text: src/prompt_texts.load_no_knowledge_text(config)."""
        self.relevance_agent = relevance_agent
        self.applicability_agent = applicability_agent
        self.requirement_agent = requirement_agent
        self.frozen_cases = frozen_cases   # "cases" part of a frozen retrieval file
        self.output_dir = Path(output_dir)
        self.template = block_template
        self.no_knowledge_text = no_knowledge_text
        self.relevance_checker = RelevanceV2Checker()
        self.resolver = ResolverV2()

    # ---------- one case ----------

    def mediate_case(self, case_id: str, description: str) -> dict:
        if case_id not in self.frozen_cases:
            raise KeyError(f"case {case_id} is missing from the frozen retrieval file")
        path = self.output_dir / f"{case_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

        passages = sorted(self.frozen_cases[case_id]["passages"], key=lambda p: p["rank"])
        records = [self.mediate_passage(case_id, description, p, passages) for p in passages]
        result = {"case_id": case_id, "c3_version": "v2", "passages": records,
                  "knowledge_block": self.knowledge_block(records)}

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def mediate_passage(self, case_id: str, description: str, passage: dict, case_passages: list[dict]) -> dict:
        """The four boxes for one passage. Returns its audit-trail record."""
        passage_id, text = passage["passage_id"], passage["text"]
        record = {"rank": passage["rank"], "passage_id": passage_id, "passage_text": text, "label": None,
                  "label_cause": None, "failed_step": None, "error": None, "relevance": None, "applicability": None,
                  "resolution": None, "requirement": None}

        # Box 1: relevance
        relevance = self._step(record, "relevance", lambda: self.relevance_agent.run(
            case_id, description=description, passage_id=passage_id, passage_text=text))
        if relevance is None:
            return record
        record["relevance"] = self.relevance_checker.check(relevance, text, description)
        if not record["relevance"]["final_relevant"]:
            record["label"] = IRRELEVANT
            record["label_cause"] = record["relevance"]["cause"]
            return record

        # Box 2: applicability, first look and (only for Indeterminate) second look
        applicability = self._step(record, "applicability", lambda: self.applicability_agent.first_look(
            case_id, description, passage_id, text))
        if applicability is None:
            return record
        record["applicability"] = applicability
        if applicability["label"] == INDETERMINATE and self.applicability_agent.open_conditions(applicability):
            self._step(record, "applicability", lambda: self.applicability_agent.second_look(
                case_id, description, applicability, passage_id, case_passages))
        if applicability["failed_step"]:
            return self._failed(record, applicability["failed_step"], "no valid output after retry (see the log file)")
        if applicability["label"] == NO_DUTY:
            record["label"] = NO_DUTY
            record["label_cause"] = ("duty_type none: the passage places no duty and gives no right of its own; it only "
                                     "limits, excludes or refers to other rules")
            return record
        if applicability["label"] == SPLIT_INVALID:
            record["label"] = SPLIT_INVALID
            record["label_cause"] = "obligation word in the IF item(s): " + "; ".join(applicability["rejected_if"])
            return record

        # Box 3: resolver (code)
        record["resolution"] = self.resolver.resolve(applicability)
        record["label"] = record["resolution"]["label"]
        record["label_cause"] = record["resolution"]["reason"]

        # Box 4: requirement, only for Applicable rules (D5: also Applicable (conditional), keeping its case events)
        if record["label"] in APPLICABLE_LABELS:
            record["requirement"] = self._step(record, "requirement", lambda: self.write_requirement(
                case_id, description, record, text, applicability["split"]["then"], applicability["conditions"],
                record["resolution"]["case_events"]))
            if record["requirement"] and record["requirement"]["requirement_invalid"]:
                record["label_cause"] = ("requirement invalid: "
                                         + "; ".join(record["requirement"]["attempts"][-1]["problems"]))

        # D4b: the sub-rules (special cases) of the passage, each resolved on its own
        for sub in applicability.get("sub_rules") or []:
            self.mediate_sub_rule(case_id, description, record, sub, case_passages)
        return record

    def write_requirement(self, case_id: str, description: str, record: dict, text: str, then: str,
                          conditions: list[dict], case_events: list[dict]) -> dict | None:
        """Box 4 for one Applicable rule (the main rule or a sub-rule), tied to RelevanceAgentV2's process step.
        case_events (D5): the resolver's case events, which the requirement must keep as its "If/When ..." trigger."""
        return self.requirement_agent.write(
            case_id, description=description, passage_id=record["passage_id"], passage_text=text, then=then,
            process_step=record["relevance"]["process_step"],
            description_quote=record["relevance"]["description_quote"], if_items=conditions,
            case_events=case_events)

    def mediate_sub_rule(self, case_id: str, description: str, record: dict, sub: dict,
                         case_passages: list[dict]) -> None:
        """D4b: second look (only for Indeterminate), resolver and requirement (only for Applicable) of one sub-rule,
        exactly as for the main rule. A call with no valid answer marks only this sub-rule "Mediation failed"."""
        agent = self.applicability_agent
        try:
            if not sub["failed_step"] and sub["label"] == INDETERMINATE and agent.open_conditions(sub):
                agent.second_look(case_id, description, sub, record["passage_id"], case_passages)
            if sub["failed_step"]:
                sub.update(label=MEDIATION_FAILED, label_cause=f"failed at {sub['failed_step']}: no valid output "
                                                               f"after retry (see the log file)")
                return
            sub["resolution"] = self.resolver.resolve(sub)
            sub["label"], sub["label_cause"] = sub["resolution"]["label"], sub["resolution"]["reason"]
            if sub["label"] not in APPLICABLE_LABELS:
                return
            sub["requirement"] = self.write_requirement(case_id, description, record, record["passage_text"],
                                                        sub["then"], sub["conditions"], sub["resolution"]["case_events"])
            if sub["requirement"] is None:
                sub.update(label=MEDIATION_FAILED, failed_step="requirement",
                           label_cause="failed at requirement: no valid output after retry (see the log file)")
            elif sub["requirement"]["requirement_invalid"]:
                sub["label_cause"] = "requirement invalid: " + "; ".join(sub["requirement"]["attempts"][-1]["problems"])
        except LLMUnavailableError:
            raise
        except Exception as e:
            sub.update(label=MEDIATION_FAILED, failed_step=sub["failed_step"] or "sub-rule",
                       error=f"{type(e).__name__}: {e}", label_cause=f"failed: {type(e).__name__}: {e}")

    def _step(self, record: dict, step: str, call):
        """Run one step. On no valid output or an error, mark the passage "Mediation failed" and return None."""
        try:
            output = call()
        except LLMUnavailableError:
            raise  # the API is unreachable: stop the run (it can be resumed), do not record a result
        except Exception as e:  # any other error: record it and go on with the next passage
            self._failed(record, step, f"{type(e).__name__}: {e}")
            return None
        if output is None:
            self._failed(record, step, "no valid output after retry (see the log file)")
        return output

    @staticmethod
    def _failed(record: dict, step: str, error: str) -> dict:
        record.update(label=MEDIATION_FAILED, failed_step=step, error=error, label_cause=f"failed at {step}: {error}")
        return record

    # ---------- knowledge block ----------

    def knowledge_block(self, records: list[dict]) -> str:
        """Confirmed requirements that passed the code check only (of the main rule and of every sub-rule, D4b, in
        passage order); C1's text when there are none."""
        lines = [self.template["requirement_line"].format(passage_id=r["passage_id"],
                                                          requirement=rule["requirement"]["requirement"].strip())
                 for r in records for rule in [r] + ((r.get("applicability") or {}).get("sub_rules") or [])
                 if rule["label"] in APPLICABLE_LABELS and rule.get("requirement")
                 and not rule["requirement"]["requirement_invalid"]]
        if not lines:
            return self.no_knowledge_text
        return self.template["block"].format(requirements="\n".join(lines))
