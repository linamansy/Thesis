"""C3 version fingerprint: SHA-256 of everything that makes up a C3 mediation prompt or the C3 knowledge block
(fix C2, 19 Oct 2026). Used by tests/test_c3_frozen.py and the preflight check.

C3 v1 = the mediation used for Study 1 (git tag c3-v1-study1 = commit aa1ca1e, the code that ran Study 1).
Its hashes are stored in the file named by config.yaml mediation.c3_hashes_file; mediation.c3_version names the
frozen version. Fingerprinted, per item:
  prompt:<agent>       the agent's prompt template file (prompts/relevance|applicability|requirement_prompt.txt)
  schema:<agent>       the agent's JSON output schema, which is pasted into its prompt ({schema})
  json_retry_note      the note added after an invalid answer (prompts/json_retry_note.json)
  c3_block_template    the C3 knowledge block layout (prompts/c3_block_template.json, without its comments)
Text is hashed after normalising line endings to "\\n", so a Windows checkout (CRLF) gives the same hashes.
"""

import hashlib
import json

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.config import project_path
from src.prompt_texts import load_c3_block_template, load_json_retry_note

AGENTS = {"relevance": RelevanceAgent, "applicability": ApplicabilityAgent, "requirement": RequirementAgent}


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def c3_fingerprint(config: dict) -> dict[str, str]:
    """{item: sha256} for the current files and code."""
    fingerprint = {}
    for name, agent in AGENTS.items():
        template = project_path(config["paths"][agent.prompt_key]).read_text(encoding="utf-8")
        fingerprint[f"prompt:{name}"] = text_sha256(template)
        fingerprint[f"schema:{name}"] = text_sha256(json.dumps(agent.output_schema.model_json_schema(), indent=2))
    fingerprint["json_retry_note"] = text_sha256(load_json_retry_note(config))
    fingerprint["c3_block_template"] = text_sha256(json.dumps(load_c3_block_template(config), sort_keys=True,
                                                              ensure_ascii=False))
    return dict(sorted(fingerprint.items()))


def frozen_fingerprint(config: dict) -> dict:
    """The stored hashes of the frozen version named in config.yaml (mediation.c3_version)."""
    data = json.loads(project_path(config["mediation"]["c3_hashes_file"]).read_text(encoding="utf-8"))
    if data["version"] != config["mediation"]["c3_version"]:
        raise ValueError(f"{config['mediation']['c3_hashes_file']} holds C3 {data['version']}, but config.yaml "
                         f"names {config['mediation']['c3_version']}")
    return data


def changed_items(config: dict) -> list[str]:
    """Items whose current hash differs from the frozen version (empty = C3 unchanged)."""
    frozen = frozen_fingerprint(config)["hashes"]
    current = c3_fingerprint(config)
    return sorted(k for k in set(frozen) | set(current) if frozen.get(k) != current.get(k))
