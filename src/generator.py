"""BPMNGenerator: the single generator shared by C1, C2 and C3.

The prompt template lives in one file (prompts/generator_prompt.txt) with three
fixed parts: instructions + JSON schema, the process description, and a
knowledge block. The conditions differ ONLY in the text put in the knowledge block.
"""

import json
from pathlib import Path

from src.agents.base_agent import BaseAgent
from src.config import load_config, project_path
from src.llm.base_llm import LLMClient
from src.logger import RunLogger
from src.schemas import ProcessModel

# Knowledge block used in condition C1.
NO_KNOWLEDGE_TEXT = "No domain knowledge provided."


class BPMNGenerator(BaseAgent):
    """Turns a process description (plus a knowledge block) into a ProcessModel."""

    output_schema = ProcessModel

    def __init__(self, llm: LLMClient, logger: RunLogger,
                 template_path: Path | None = None, max_retries: int | None = None):
        super().__init__(llm, logger, max_retries)
        if template_path is None:
            template_path = project_path(load_config()["paths"]["generator_prompt"])
        self.template = Path(template_path).read_text(encoding="utf-8")

    def build_prompt(self, description: str, knowledge_block: str) -> str:
        """Fill the three parts of the shared template."""
        schema = json.dumps(ProcessModel.model_json_schema(), indent=2)
        return self.template.format(schema=schema,
                                    description=description.strip(),
                                    knowledge=knowledge_block.strip())
