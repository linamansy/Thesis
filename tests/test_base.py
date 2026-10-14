"""Tests for the foundation classes: MockLLM, RunLogger and BaseAgent.

A small DummyAgent inherits from BaseAgent to check the shared logic.
"""

import json

from pydantic import BaseModel

from src.agents.base_agent import BaseAgent
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

# The fields every log record must contain (from CLAUDE.md).
REQUIRED_FIELDS = {
    "timestamp", "run_id", "condition", "case_id", "component", "model",
    "temperature", "prompt", "raw_output", "parsed_output", "valid_json",
    "retries", "duration_seconds",
}

VALID_ANSWER = '{"answer": "yes", "confidence": 0.9}'


class DummyOutput(BaseModel):
    answer: str
    confidence: float


class DummyAgent(BaseAgent):
    output_schema = DummyOutput

    def build_prompt(self, question: str) -> str:
        return f"Answer the question as JSON with fields answer and confidence.\nQuestion: {question}"


def read_records(logger):
    with open(logger.log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def make_agent(tmp_path, responses):
    llm = MockLLM(responses)
    logger = RunLogger(tmp_path / "logs", condition="C1", run_id="test")
    return DummyAgent(llm, logger, max_retries=1), llm, logger


def test_valid_output_is_parsed_and_logged(tmp_path):
    agent, llm, logger = make_agent(tmp_path, [VALID_ANSWER])

    result = agent.run(case_id="01", question="Is the order confirmed?")

    assert result == DummyOutput(answer="yes", confidence=0.9)
    assert logger.log_path == tmp_path / "logs" / "C1_test.jsonl"
    records = read_records(logger)
    assert len(records) == 1
    record = records[0]
    assert set(record) == REQUIRED_FIELDS
    assert record["run_id"] == "test"
    assert record["condition"] == "C1"
    assert record["case_id"] == "01"
    assert record["component"] == "DummyAgent"
    assert record["model"] == "mock-llm"
    assert record["temperature"] == 0
    assert "Is the order confirmed?" in record["prompt"]
    assert record["raw_output"] == VALID_ANSWER
    assert record["parsed_output"] == {"answer": "yes", "confidence": 0.9}
    assert record["valid_json"] is True
    assert record["retries"] == 0
    assert record["duration_seconds"] >= 0


def test_retry_after_invalid_json(tmp_path):
    agent, llm, logger = make_agent(tmp_path, ["this is not json", VALID_ANSWER])

    result = agent.run(case_id="03", question="Is payment due?")

    assert result == DummyOutput(answer="yes", confidence=0.9)
    assert len(llm.prompts_received) == 2
    assert "could not be accepted" in llm.prompts_received[1]
    first, second = read_records(logger)
    assert (first["valid_json"], first["retries"], first["parsed_output"]) == (False, 0, None)
    assert (second["valid_json"], second["retries"]) == (True, 1)


def test_wrong_schema_counts_as_invalid(tmp_path):
    # Valid JSON, but "confidence" is missing, so the schema check fails.
    agent, llm, logger = make_agent(tmp_path, ['{"answer": "yes"}', VALID_ANSWER])

    result = agent.run(case_id="05", question="?")

    assert result is not None
    assert [r["valid_json"] for r in read_records(logger)] == [False, True]


def test_gives_up_after_one_retry(tmp_path):
    agent, llm, logger = make_agent(tmp_path, ["bad", "still bad"])

    result = agent.run(case_id="06", question="?")

    assert result is None
    assert len(llm.prompts_received) == 2  # first attempt + exactly one retry
    assert [r["retries"] for r in read_records(logger)] == [0, 1]


def test_json_inside_code_fence_is_accepted(tmp_path):
    agent, llm, logger = make_agent(tmp_path, ["```json\n" + VALID_ANSWER + "\n```"])

    assert agent.run(case_id="10", question="?") is not None


def test_max_retries_is_read_from_config(tmp_path):
    logger = RunLogger(tmp_path / "logs", condition="C1", run_id="test")
    agent = DummyAgent(MockLLM([VALID_ANSWER]), logger)

    assert agent.max_retries == 1
