"""RelevanceAgent (C3, step 1): is this legal passage about this process at all?

Input:  the process description and one retrieved passage.
Output: relevant (true/false), a reason, and a quote from each text that shows the link.
Irrelevant passages stop here; relevant ones go on to the ApplicabilityAgent.
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent


class RelevanceOutput(BaseModel):
    relevant: bool = Field(description="true if the passage is about this kind of process")
    reason: str = Field(description="One or two sentences explaining the decision")
    evidence_process: str | None = Field(description="Exact quote from the process description, or null")
    evidence_passage: str | None = Field(description="Exact quote from the legal passage, or null")


class RelevanceAgent(BaseAgent):
    output_schema = RelevanceOutput
    prompt_key = "relevance_prompt"

    def build_prompt(self, description: str, passage_id: str, passage_text: str) -> str:
        return self.template.format(schema=self.schema_text(),
                                    description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}")
