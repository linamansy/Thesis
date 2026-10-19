"""C3 v1 is frozen (fix C2): any change to a C3 agent prompt, an agent output schema, the retry note or the C3 block
template fails this test. To change C3 on purpose, make a NEW version (new hashes file, config mediation.c3_version)
instead of editing v1. Hashes: tests/c3_v1_hashes.json; fingerprint: src/c3_version.py.
"""

import json
import subprocess

import pytest

from src.c3_version import AGENTS, c3_fingerprint, changed_items, frozen_fingerprint, text_sha256
from src.config import PROJECT_ROOT, load_config

CONFIG = load_config()


def test_c3_is_unchanged_since_v1():
    assert changed_items(CONFIG) == []


def test_every_c3_part_is_fingerprinted():
    assert set(frozen_fingerprint(CONFIG)["hashes"]) == \
        {f"{kind}:{name}" for kind in ("prompt", "schema") for name in AGENTS} | {"json_retry_note", "c3_block_template"}


def test_a_change_is_detected(tmp_path):
    template = json.loads((PROJECT_ROOT / CONFIG["paths"]["c3_block_template"]).read_text(encoding="utf-8"))
    template["empty_section"] = "(nothing)"
    changed_file = tmp_path / "c3_block_template.json"
    changed_file.write_text(json.dumps(template), encoding="utf-8")
    prompt_file = tmp_path / "relevance_prompt.txt"
    prompt_file.write_text((PROJECT_ROOT / CONFIG["paths"]["relevance_prompt"]).read_text(encoding="utf-8") + " ",
                           encoding="utf-8")
    config = dict(CONFIG, paths=dict(CONFIG["paths"], c3_block_template=str(changed_file),
                                     relevance_prompt=str(prompt_file)))
    assert changed_items(config) == ["c3_block_template", "prompt:relevance"]


def test_only_line_endings_do_not_count():
    assert text_sha256("a\r\nb") == text_sha256("a\nb")


def test_wrong_version_name_is_refused():
    config = dict(CONFIG, mediation=dict(CONFIG["mediation"], c3_version="v2"))
    with pytest.raises(ValueError, match="holds C3 v1"):
        frozen_fingerprint(config)


def test_tag_points_at_the_study1_commit():
    result = subprocess.run(["git", "rev-parse", "--short", "c3-v1-study1^{commit}"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("tag c3-v1-study1 not in this clone")
    assert result.stdout.strip() == frozen_fingerprint(CONFIG)["commit"]


def test_agent_prompt_files_equal_the_tagged_version():
    for name, agent in AGENTS.items():
        path = CONFIG["paths"][agent.prompt_key]
        result = subprocess.run(["git", "show", f"c3-v1-study1:{path}"], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            pytest.skip("tag c3-v1-study1 not in this clone")
        assert text_sha256(result.stdout) == c3_fingerprint(CONFIG)[f"prompt:{name}"]
