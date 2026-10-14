"""ApplicabilityAgent (C3, step 2): which conditions of the rule does the process meet?

Input:  the process description and one RELEVANT passage.
Output: the rule split into its conditions; each condition gets a status
        (satisfied / contradicted / not_stated) and an exact quote from the description
        as evidence (or null).
The agent does NOT decide the final label. That is done by code, without an LLM, in
src/mediation/applicability_resolver.py, which also checks that every quote is real.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent

Status = Literal["satisfied", "contradicted", "not_stated"]


class Condition(BaseModel):
    condition: str = Field(description="One condition of the rule, as a short statement")
    status: Status = Field(description="satisfied, contradicted or not_stated, judged from the description only")
    evidence: str | None = Field(description="Exact quote from the process description, or null for not_stated")


class ApplicabilityOutput(BaseModel):
    conditions: list[Condition] = Field(min_length=1, description="All conditions the rule needs to apply")


class ApplicabilityAgent(BaseAgent):
    output_schema = ApplicabilityOutput
    prompt_key = "applicability_prompt"

    def build_prompt(self, description: str, passage_id: str, passage_text: str) -> str:
        return self.template.format(schema=self.schema_text(),
                                    description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}")
