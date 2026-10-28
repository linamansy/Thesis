"""OrchestratorV2: runs the four boxes of C3 v2 for each frozen passage of a case (docs/C3_V2_DEVELOPMENT.md).

For every passage of the case, in rank order:
  1. RelevanceAgentV2 + RelevanceV2Checker (code quote check)
     not final_relevant        -> label "Irrelevant", stop
  2. ApplicabilityAgentV2, first look: split (law only) -> check-IF -> quote check -> first-look label
     split with an obligation word in an IF item -> label "Split invalid", stop
     Indeterminate with open IF conditions -> second look, with the description + ALL retrieved passages of the case
  3. ResolverV2 (code): Applicable only if all IF conditions are confirmed AND no stated exception applies
  4. RequirementAgentV2, ONLY for Applicable: the THEN part -> 1-2 plain sentences tied to RelevanceAgentV2's process
     step, checked by code (RequirementCheckerV2); failing twice -> requirement_invalid, never passed on
A call with no valid answer after its retry gives "Mediation failed" (failed_step names the call) and the next
passage is processed. LLMUnavailableError is passed on (the run stops and can be resumed), as in v1.

Knowledge block: confirmed requirements that passed the code check only (prompts/c3_block_template_v2.json).
Indeterminate, Not applicable, Split invalid, Irrelevant, requirement_invalid and failed passages are kept in the audit
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

from src.agents.applicability_agent_v2 import SPLIT_INVALID, ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.llm.base_llm import LLMUnavailableError
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE
from src.mediation.relevance_v2_checker import RelevanceV2Checker
from src.mediation.resolver_v2 import ResolverV2
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
        if applicability["label"] == SPLIT_INVALID:
            record["label"] = SPLIT_INVALID
            record["label_cause"] = "obligation word in the IF item(s): " + "; ".join(applicability["rejected_if"])
            return record

        # Box 3: resolver (code)
        record["resolution"] = self.resolver.resolve(applicability)
        record["label"] = record["resolution"]["label"]
        record["label_cause"] = record["resolution"]["reason"]
        if record["label"] != APPLICABLE:
            return record

        # Box 4: requirement, only for Applicable rules
        record["requirement"] = self._step(record, "requirement", lambda: self.requirement_agent.write(
            case_id, description=description, passage_id=passage_id, passage_text=text,
            then=applicability["split"]["then"], process_step=record["relevance"]["process_step"],
            description_quote=record["relevance"]["description_quote"]))
        if record["requirement"] and record["requirement"]["requirement_invalid"]:
            record["label_cause"] = ("requirement invalid: "
                                     + "; ".join(record["requirement"]["attempts"][-1]["problems"]))
        return record

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
        """Confirmed requirements that passed the code check only; C1's text when there are none."""
        lines = [self.template["requirement_line"].format(passage_id=r["passage_id"],
                                                          requirement=r["requirement"]["requirement"].strip())
                 for r in records if r["label"] == APPLICABLE and r["requirement"]
                 and not r["requirement"]["requirement_invalid"]]
        if not lines:
            return self.no_knowledge_text
        return self.template["block"].format(requirements="\n".join(lines))
