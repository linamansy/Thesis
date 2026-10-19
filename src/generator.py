"""BPMNGenerator: the single generator shared by C1, C2 and C3.

The prompt template lives in one file (prompts/generator_prompt.txt) with three
fixed parts: instructions + JSON schema, the process description, and a
knowledge block. The conditions differ ONLY in the text put in the knowledge block.
"""

from src.agents.base_agent import BaseAgent
from src.schemas import ProcessModel

# The knowledge block of C1 is in prompts/c1_no_knowledge.txt (src/prompt_texts.load_no_knowledge_text).


def format_passages(passages: list[dict]) -> str:
    """Knowledge block for C2: the frozen passages in rank order, each as "[passage id] full text".

    passages: entries from frozen_retrieval.json with the keys "rank", "passage_id" and "text".
    Passages are separated by an empty line.
    """
    ordered = sorted(passages, key=lambda p: p["rank"])
    return "\n\n".join(f"[{p['passage_id']}] {p['text']}" for p in ordered)


class BPMNGenerator(BaseAgent):
    """Turns a process description (plus a knowledge block) into a ProcessModel."""

    output_schema = ProcessModel
    prompt_key = "generator_prompt"

    def build_prompt(self, description: str, knowledge_block: str) -> str:
        """Fill the three parts of the shared template."""
        return self.template.format(schema=self.schema_text(),
                                    description=description.strip(),
                                    knowledge=knowledge_block.strip())
