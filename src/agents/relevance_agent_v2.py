"""RelevanceAgent v2 (C3 v2 development): is the rule about something this process does?

v1 (src/agents/relevance_agent.py, frozen for Study 1) asked whether the passage's TOPIC matches the process, with a
list of consumer-law topics. On GDPR passages it called all 35 development passages irrelevant because "data
protection" did not sound like ordering or delivery. v2 is general, for any kind of law, with no topic list.
Round 1 (commit 4ff3ee8):
  1. law_trigger: the situation or activity the rule applies to, with law_quote copied from the passage
  2. process_step: the step of the description that does it, with description_quote copied from the description
  3. relevant: true only if some step does what the rule applies to
Round 2 (24 Oct 2026): relevance is a broad "is this rule about something this process does?" judgement. Round 1
asked for the rule's trigger, and the model rejected passages whose specific trigger event was not described; IF
conditions, trigger events, deadlines and exceptions are now left to the applicability stage. law_trigger became
law_focus (what the rule is about); the code check is unchanged.
The model's answer is then checked by code (RelevanceV2Checker, src/mediation/relevance_v2_checker.py): the final
label is relevant only if the model said true AND both quotes are found.

Input:  the process description and one retrieved passage (as v1).
Output: the JSON below. Prompt: prompts/relevance_prompt_v2.txt (config.yaml paths.relevance_prompt_v2).
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent


class RelevanceOutputV2(BaseModel):
    law_focus: str = Field(description="What the rule is about: the kind of activity it deals with")
    law_quote: str = Field(description="Exact words copied from the legal passage that state what the rule is about")
    relevant: bool = Field(description="true if the rule is about something this process does")
    process_step: str = Field(description="The step of the process where that kind of activity happens; empty "
                                          "string if none")
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
