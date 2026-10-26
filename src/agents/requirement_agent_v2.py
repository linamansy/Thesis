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
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.mediation.requirement_checker_v2 import RequirementCheckerV2


class RequirementOutputV2(BaseModel):
    requirement: str = Field(description="One or two sentences: what the rule requires, tied to the process step")


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

    def write(self, case_id: str, **inputs) -> dict | None:
        """The requirement after the code checks, or None if no answer was valid JSON (after the JSON retry).

        Returns {"requirement": text or None, "requirement_invalid": bool, "attempts": [...]}; each attempt keeps the
        answer, its measurements and the problems found."""
        attempts = []
        self.check_note = ""
        for _ in range(2):   # the answer, and one retry if the code check fails
            output = self.run(case_id, **inputs)
            if output is None:
                self.check_note = ""
                return None
            problems = self.checker.problems(output.requirement, inputs["passage_text"])
            attempts.append({"requirement": output.requirement, "problems": problems,
                             "measures": self.checker.measure(output.requirement, inputs["passage_text"])})
            if not problems:
                break
            self.check_note = self.retry_note.format(error="; ".join(problems))
        self.check_note = ""
        valid = not attempts[-1]["problems"]
        return {"requirement": attempts[-1]["requirement"] if valid else None, "requirement_invalid": not valid,
                "attempts": attempts}
