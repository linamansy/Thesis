"""SilverAnnotator: builds the automatic ("silver") legal reference used for evaluation. NOT part of C3.

Why it exists: the PMo reference models were drawn from the process descriptions and contain no legal
steps, so a correct legal step added by a generator counts as an error. The silver reference states, per
case and per frozen passage, whether the rule applies and which process steps it requires. The evaluator
then (1) no longer counts generated tasks that realise a required step as errors and (2) measures
requirement coverage. It also gives an applicability label to compare C3's labels with (RQ3).

Independence from C3 (so C3 is not graded by its own work):
  - a DIFFERENT and stronger model (config.yaml, silver section: Gemini, not qwen3)
  - a DIFFERENT prompt (prompts/silver_annotation_prompt.txt), one call per passage, no shared code path
    with the mediation agents, and it never sees any generated model or any C3 output.
The labels are AI-made: they are SILVER (provisional), never gold. Decision 16 Oct 2026: no human audit,
so this is a stated limitation of the thesis.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent

SILVER_LABELS = ["applicable", "not_applicable", "indeterminate", "irrelevant"]


class Step(BaseModel):
    label: str = Field(description="Short BPMN task label, verb + object, e.g. 'Provide withdrawal information'")
    actor: str | None = Field(default=None, description="Who performs it, or null")
    timing: str | None = Field(default=None, description="When, relative to the existing steps, if the rule says so; or null")
    already_in_description: bool = Field(default=False, description="true if the description already contains this step")


class Fact(BaseModel):
    fact: str = Field(description="A fact the rule depends on, short")
    status: Literal["stated_true", "stated_false", "not_stated"]


class SilverOutput(BaseModel):
    label: Literal["applicable", "not_applicable", "indeterminate", "irrelevant"]
    facts: list[Fact] = Field(default_factory=list)
    reason: str = Field(description="One or two sentences")
    required_steps: list[Step] = Field(default_factory=list, description="Only for applicable")
    possible_steps: list[Step] = Field(default_factory=list, description="Only for indeterminate")
    evidence: list[str] = Field(default_factory=list, description="Exact quotes from the description")


class SilverAnnotator(BaseAgent):
    output_schema = SilverOutput
    prompt_key = "silver_prompt"

    def build_prompt(self, description: str, passage_id: str, passage_text: str) -> str:
        return self.template.format(schema=self.schema_text(), description=description.strip(),
                                    passage=f"[{passage_id}] {passage_text.strip()}")
