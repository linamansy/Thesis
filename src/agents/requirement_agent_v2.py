"""RequirementAgent v2 (C3 v2, box 4): turn an APPLICABLE rule's THEN part into a requirement for one process step.

Runs only for rules ResolverV2 labelled "Applicable" (the OrchestratorV2 enforces this).
Input:  the process description, the passage, its THEN part (from the split call of ApplicabilityAgentV2), and the
        process step RelevanceAgentV2 named (process_step + description_quote).
Output: one or two sentences that state the obligation and tie it to that step. The prompt forbids adding anything
        that is not in the THEN part. v1 (src/agents/requirement_agent.py) stays frozen for Study 1.
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent


class RequirementOutputV2(BaseModel):
    requirement: str = Field(description="One or two sentences: what the rule requires, tied to the process step")


class RequirementAgentV2(BaseAgent):
    output_schema = RequirementOutputV2
    prompt_key = "requirement_prompt_v2"

    def build_prompt(self, description: str, passage_id: str, passage_text: str, then: str, process_step: str,
                     description_quote: str) -> str:
        if not then.strip():
            raise ValueError("RequirementAgentV2 needs the THEN part of an Applicable rule")
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}", then=then.strip(),
                                    step=f'{process_step} ("{description_quote}")')
