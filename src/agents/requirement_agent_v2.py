"""RequirementAgent v2 (C3 v2, box 4): turn an APPLICABLE rule's THEN part into a requirement for one process step.

Runs only for rules ResolverV2 labelled "Applicable" (the OrchestratorV2 enforces this).
Input:  the process description, the passage, its THEN part (from the split call of ApplicabilityAgentV2), and the
        process step RelevanceAgentV2 named (process_step + description_quote).
Output: one or two plain sentences (at most c3_v2.requirement_checks.max_words words) that say what is required at
        that step. The prompt forbids adding anything that is not in the THEN part and any instruction to add or draw
        something in a model. v1 (src/agents/requirement_agent.py) stays frozen for Study 1.

Round 1 fixes (docs/C3_V2_DEVELOPMENT.md section 7): write() runs the call (JSON check + 1 retry, as every agent), then
RequirementCheckerV2 (code) checks word and sentence count, banned words and text copied from the passage. On a failed
check the call is made once more with the failure reasons added (the JSON retry note); if that answer fails again, the
requirement is marked requirement_invalid and the orchestrator does not pass it on.

Round 3 (docs/C3_V2_DEVELOPMENT.md section 9, R6): the answer also has a step_quote (the words of the description that
name the step) and a triggers list (each trigger of the THEN part, copied from it, with the words of the requirement
that keep it). The code check (RequirementCheckerV2.quote_problems) finds the step_quote in the description, each
trigger in the full legal passage (fix A, 28 Oct 2026: the split moves triggers into the IF part) and each kept_as
in the requirement; a failure is handled like the other checks.

Duty check (28 Oct 2026): the answer also has a duty ("from_then": the words of the THEN part that say what must be
done, "kept_as": the words of the requirement that keep them). Without it a requirement could pass every check while
only restating the process step and stating no duty at all (GDPR-Art13-2-a, case 01.1). The checker also rejects an
empty triggers list when the IF part has situational conditions; a role-only rule may leave it empty.
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.mediation.requirement_checker_v2 import RequirementCheckerV2


class TriggerKept(BaseModel):
    trigger: str = Field(description="A trigger or condition of the obligation, copied exactly from the OBLIGATION")
    kept_as: str = Field(description="The words of the requirement, copied exactly, that keep this trigger")


class DutyKept(BaseModel):
    from_then: str = Field(description="The words of the OBLIGATION that say what must be done, copied exactly "
                                       "(at least 3 words)")
    kept_as: str = Field(description="The words of the requirement, copied exactly, that say the same thing")


class RequirementOutputV2(BaseModel):
    requirement: str = Field(description="One or two sentences: what the rule requires, tied to the process step")
    step_quote: str = Field(description="Exact words copied from the process description that name the step")
    triggers: list[TriggerKept] = Field(description="Every trigger or condition the obligation states; empty list "
                                                    "if none")
    duty: DutyKept = Field(description="The duty of the obligation, and the words of the requirement that keep it")


class RequirementAgentV2(BaseAgent):
    output_schema = RequirementOutputV2
    prompt_key = "requirement_prompt_v2"

    def __init__(self, llm, logger, max_retries: int | None = None, config: dict | None = None):
        super().__init__(llm, logger, max_retries)
        self.checker = RequirementCheckerV2(config or load_config())
        self.check_note = ""   # failure reasons of the code check, added to the prompt of the check retry

    def build_prompt(self, description: str, passage_id: str, passage_text: str, then: str, process_step: str,
                     description_quote: str) -> str:
        if not then.strip():
            raise ValueError("RequirementAgentV2 needs the THEN part of an Applicable rule")
        banned = self.checker.banned_words
        banned_text = ", ".join(f'"{w}"' for w in banned[:-1]) + f' or "{banned[-1]}"'
        prompt = self.template.format(schema=self.schema_text(), description=description.strip(),
                                      passage=f"[{passage_id}] {passage_text.strip()}", then=then.strip(),
                                      step=f'{process_step} ("{description_quote}")',
                                      max_words=self.checker.max_words, banned_words=banned_text)
        return prompt + self.check_note

    def write(self, case_id: str, if_items: list[dict] | None = None, **inputs) -> dict | None:
        """The requirement after the code checks, or None if no answer was valid JSON (after the JSON retry).

        if_items: the IF items of the split (the applicability record's "conditions", each with its "kind").
        They are not part of the prompt; the checker only uses them to see whether the rule has situational
        conditions, because only a role-only rule may leave the triggers list empty.

        Returns {"requirement": text or None, "requirement_invalid": bool, "attempts": [...]}; each attempt keeps the
        answer, its measurements and the problems found."""
        attempts = []
        self.check_note = ""
        for _ in range(2):   # the answer, and one retry if the code check fails
            output = self.run(case_id, **inputs)
            if output is None:
                self.check_note = ""
                return None
            problems = (self.checker.problems(output.requirement, inputs["passage_text"])
                        + self.checker.quote_problems(output, inputs["description"], inputs["passage_text"],
                                                      inputs["then"], if_items))
            duty = getattr(output, "duty", None)
            attempts.append({"requirement": output.requirement, "step_quote": output.step_quote,
                             "triggers": [t.model_dump() for t in output.triggers],
                             "duty": duty.model_dump() if duty else None, "problems": problems,
                             "measures": self.checker.measure(output.requirement, inputs["passage_text"])})
            if not problems:
                break
            self.check_note = self.retry_note.format(error="; ".join(problems))
        self.check_note = ""
        valid = not attempts[-1]["problems"]
        return {"requirement": attempts[-1]["requirement"] if valid else None, "requirement_invalid": not valid,
                "attempts": attempts}
