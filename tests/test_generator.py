"""Tests for src/generator.py and the per-case loop in run_experiment.py."""

import json

import pytest

from run_experiment import ExperimentRunner
from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator, format_passages
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

CONFIG = load_config()


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


def test_instructions_are_neutral_about_knowledge(tmp_path):
    prompt = make_generator(tmp_path).build_prompt("Some description.", NO_KNOWLEDGE_TEXT)
    instructions = prompt.split("PROCESS DESCRIPTION")[0]
    assert ("Model the process described in the process description. The domain knowledge block "
            "may contain additional information; use it only where it applies to this specific "
            "process.") in instructions
    # C2 passes raw passages that may not apply, so the fixed text must not call them requirements.
    assert "requirement" not in instructions.lower()


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


# ---------- C2 ----------

def make_runner(tmp_path, condition, responses=("{}",)):
    config = dict(CONFIG, paths=dict(CONFIG["paths"], results=str(tmp_path / "results")))
    return ExperimentRunner(config, condition, MockLLM(list(responses)), RunLogger(tmp_path / "logs", condition, "test"))


def case_prompt(runner, case_id):
    description = (runner.cases_dir / case_id / runner.description_file).read_text(encoding="utf-8")
    return runner.generator.build_prompt(description, runner.knowledge_block(case_id))


@pytest.mark.parametrize("case_id", CONFIG["cases"]["ids"])
def test_c1_and_c2_prompts_differ_only_in_knowledge_block(tmp_path, case_id):
    c1 = case_prompt(make_runner(tmp_path, "C1"), case_id)
    c2 = case_prompt(make_runner(tmp_path, "C2"), case_id)

    frozen = json.loads(project_path(CONFIG["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))
    passages = frozen["cases"][case_id]["passages"]
    block = "\n\n".join(f"[{p['passage_id']}] {p['text']}" for p in passages)

    # Replacing C1's knowledge text by the passage block must give EXACTLY the C2 prompt.
    assert c1.count(NO_KNOWLEDGE_TEXT) == 1
    assert c1.replace(NO_KNOWLEDGE_TEXT, block) == c2
    # The block holds the 5 passages in rank order.
    assert [line[1:line.index("]")] for line in c2.split("\n") if line.startswith("[")] == \
        [p["passage_id"] for p in passages]


def test_format_passages_sorts_by_rank():
    passages = [{"rank": 2, "passage_id": "B", "text": "second"}, {"rank": 1, "passage_id": "A", "text": "first"}]
    assert format_passages(passages) == "[A] first\n\n[B] second"


def test_c2_run_writes_same_files_as_c1(tmp_path):
    sample = project_path(CONFIG["paths"]["mock_generator_response"]).read_text(encoding="utf-8")
    runner = make_runner(tmp_path, "C2", [sample])

    record = runner.run_case("19")

    case_dir = tmp_path / "results" / "C2" / "19"
    assert sorted(p.name for p in case_dir.iterdir()) == ["generated.bpmn", "generated.json", "validation.json"]
    assert record["condition"] == "C2" and record["valid"] is True
