"""RequirementAgent (C3, step 3): turn an APPLICABLE rule into one concrete requirement.

Runs only for rules the ApplicabilityResolver labelled "Applicable" (the Orchestrator
enforces this; the agent also refuses to run without confirmed conditions).
Input:  the process description, the passage, and the satisfied conditions with their evidence.
Output: actor, action, condition (or null), ordering relative to the process activities (or null).
The prompt forbids adding anything that is not in the rule.
"""

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent


class RequirementOutput(BaseModel):
    actor: str = Field(description="Who must act, as named in the rule")
    action: str = Field(description="What the actor must do, as stated in the rule")
    condition: str | None = Field(description="When the action is required, as stated in the rule, or null")
    ordering: str | None = Field(
        description="When the action must happen relative to activities in the description, or null")


class RequirementAgent(BaseAgent):
    output_schema = RequirementOutput
    prompt_key = "requirement_prompt"

    def build_prompt(self, description: str, passage_id: str, passage_text: str,
                     satisfied_conditions: list[dict]) -> str:
        """satisfied_conditions: dicts with "condition" and "evidence" (from the ApplicabilityResolver)."""
        if not satisfied_conditions:
            raise ValueError("RequirementAgent runs only for Applicable rules, which have satisfied conditions")
        conditions = "\n".join(f'- {c["condition"]} (evidence: "{c["evidence"]}")' for c in satisfied_conditions)
        return self.template.format(schema=self.schema_text(),
                                    description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}",
                                    conditions=conditions)
