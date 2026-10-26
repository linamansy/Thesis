"""Fixed texts that become part of a prompt, loaded from prompts/ (fix B7, 19 Oct 2026: they used to be written in code).

  c1_no_knowledge     prompts/c1_no_knowledge.txt     the knowledge block of C1 ("No domain knowledge provided.")
  c3_block_template   prompts/c3_block_template.json  the layout of the C3 knowledge block (src/orchestrator.py)
  json_retry_note     prompts/json_retry_note.json    added to an agent prompt after an invalid JSON answer
The exact-whitespace texts are JSON strings, so an editor cannot silently add or remove a newline.
The file paths are in config.yaml (paths section).
"""

import json

from src.config import project_path


def load_no_knowledge_text(config: dict) -> str:
    """The C1 knowledge block, without surrounding whitespace."""
    return project_path(config["paths"]["c1_no_knowledge"]).read_text(encoding="utf-8").strip()


def load_c3_block_template(config: dict, key: str = "c3_block_template") -> dict:
    """The parts of the C3 knowledge block: block, requirement_line, unconfirmed_rule_line,
    unconfirmed_condition_line, empty_section, missing_value (keys starting with "_" are comments).
    key="c3_block_template_v2" gives the C3 v2 layout (block, requirement_line)."""
    data = json.loads(project_path(config["paths"][key]).read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


def load_json_retry_note(config: dict) -> str:
    """The note added after an invalid JSON answer; contains {error}."""
    return json.loads(project_path(config["paths"]["json_retry_note"]).read_text(encoding="utf-8"))["note"]
