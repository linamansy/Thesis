"""Tests for src/count_prompt_tokens.py: the counted prompt must be exactly the experiment's prompt."""

import json

from run_experiment import ExperimentRunner
from src.config import load_config, project_path
from src.count_prompt_tokens import build_prompt
from src.generator import BPMNGenerator
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

CONFIG = load_config()


def test_prompt_is_the_same_as_in_the_experiment(tmp_path):
    for condition in ("C1", "C2"):
        llm = MockLLM(["{}"])
        runner = ExperimentRunner(CONFIG, condition, llm, RunLogger(tmp_path, condition, "t"), tmp_path / condition)
        description = (project_path(CONFIG["paths"]["cases"]) / "19" / "description.txt").read_text(encoding="utf-8")
        expected = BPMNGenerator(llm, None).build_prompt(
            description=description, knowledge_block=runner.knowledge_block("19", description))
        assert build_prompt(CONFIG, condition, "19") == expected


def test_c2_prompt_contains_the_five_frozen_passages():
    frozen = json.loads(project_path(CONFIG["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
    prompt = build_prompt(CONFIG, "C2", "19")
    assert all(f"[{p['passage_id']}]" in prompt for p in frozen["19"]["passages"])
