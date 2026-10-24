"""RelevanceAgent v2 (C3 v2, development round 1): does a step of the process do what the rule applies to?

v1 (src/agents/relevance_agent.py, frozen for Study 1) asked whether the passage's TOPIC matches the process, with a
list of consumer-law topics. On GDPR passages it called all 35 development passages irrelevant because "data
protection" did not sound like ordering or delivery. v2 is general, for any kind of law, with no topic list:
  1. law_trigger: the situation or activity the rule applies to, with law_quote copied from the passage
  2. process_step: the step of the description that does it, with description_quote copied from the description
  3. relevant: true only if some step does what the rule applies to
The model's answer is then checked by code (RelevanceV2Checker, src/mediation/relevance_v2_checker.py): the final
label is relevant only if the model said true AND both quotes are found.

Input:  the process description and one retrieved passage (as v1).
Output: the JSON below. Prompt: prompts/relevance_prompt_v2.txt (config.yaml paths.relevance_prompt_v2).
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent


class RelevanceOutputV2(BaseModel):
    law_trigger: str = Field(description="The situation or activity the rule applies to")
    law_quote: str = Field(description="Exact words copied from the legal passage that state the trigger")
    relevant: bool = Field(description="true if some step of the process does what the rule applies to")
    process_step: str = Field(description="The step of the process that does it; empty string if none")
    description_quote: str = Field(description="Exact words copied from the process description that state this "
                                               "step; empty string if none")
    reason: str = Field(description="One sentence explaining the decision")


class RelevanceAgentV2(BaseAgent):
    output_schema = RelevanceOutputV2
    prompt_key = "relevance_prompt_v2"

    def build_prompt(self, description: str, passage_id: str, passage_text: str) -> str:
        return self.template.format(schema=self.schema_text(),
                                    description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}")
