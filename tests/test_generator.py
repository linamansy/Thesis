"""Tests for src/generator.py and the per-case loop in run_experiment.py."""

import json

from run_experiment import ExperimentRunner
from src.config import load_config
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger


def make_generator(tmp_path, responses=("{}",)):
    return BPMNGenerator(MockLLM(list(responses)), RunLogger(tmp_path, "C1", "test"))


def test_prompt_has_three_parts_in_order(tmp_path):
    prompt = make_generator(tmp_path).build_prompt("The clerk checks the order.", NO_KNOWLEDGE_TEXT)
    instructions = prompt.index("INSTRUCTIONS")
    description = prompt.index("PROCESS DESCRIPTION")
    knowledge = prompt.index("DOMAIN KNOWLEDGE")
    assert instructions < description < knowledge
    assert "The clerk checks the order." in prompt
    assert prompt.rstrip().endswith(NO_KNOWLEDGE_TEXT)
    assert '"sequence_flows"' in prompt  # the JSON schema is included


def test_only_knowledge_block_changes(tmp_path):
    generator = make_generator(tmp_path)
    a = generator.build_prompt("Same description.", NO_KNOWLEDGE_TEXT)
    b = generator.build_prompt("Same description.", "CRD-Art9-1: some rule text")
    assert a.split("DOMAIN KNOWLEDGE")[0] == b.split("DOMAIN KNOWLEDGE")[0]
    assert a != b


def test_failed_generation_is_recorded_not_skipped(tmp_path, monkeypatch):
    config = load_config()
    config["paths"] = dict(config["paths"], results=str(tmp_path / "results"))
    config["cases"] = {"ids": ["01"]}
    logger = RunLogger(tmp_path / "logs", "C1", "test")
    runner = ExperimentRunner(config, "C1", MockLLM(["not json"]), logger)

    record = runner.run_case("01")

    case_dir = tmp_path / "results" / "C1" / "01"
    saved = json.loads((case_dir / "validation.json").read_text(encoding="utf-8"))
    assert saved == record
    assert record["generation_succeeded"] is False and record["valid"] is False
    assert not (case_dir / "generated.bpmn").exists()
    assert len(open(logger.log_path, encoding="utf-8").readlines()) == 2  # attempt + one retry
