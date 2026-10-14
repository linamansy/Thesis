"""Tests for resuming a run that stopped because the API was unavailable (e.g. the daily free-tier limit).

A fake LLM answers normally for a number of calls and then behaves like an exhausted quota
(raises LLMUnavailableError, which GeminiLLM raises after all its API retries). No real API is used.
"""

import json

import pytest

from run_experiment import MEDIATION_ROLES, ExperimentRunner, RunInterrupted, create_llm
from src.config import load_config, project_path
from src.llm.base_llm import LLMUnavailableError
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

CONFIG = load_config()
SAMPLE = project_path(CONFIG["paths"]["mock_generator_response"]).read_text(encoding="utf-8")
CASES = ["01", "03", "05"]


class QuotaLLM(MockLLM):
    """Answers like MockLLM for `calls_left` calls, then the API is 'unavailable'."""

    def __init__(self, responses, calls_left):
        super().__init__(responses)
        self.calls_left = calls_left

    def complete(self, prompt):
        if self.calls_left == 0:
            raise LLMUnavailableError("simulated: daily request limit reached")
        self.calls_left -= 1
        return super().complete(prompt)


def make_runner(tmp_path, condition, llm, part, agent_llms=None):
    runner = ExperimentRunner(CONFIG, condition, llm, RunLogger(tmp_path / "logs", condition, "rep1", part),
                              tmp_path / "run" / condition, agent_llms)
    runner.case_ids = CASES
    return runner


def logged_cases(runner):
    return [json.loads(line)["case_id"] for line in open(runner.logger.log_path, encoding="utf-8")]


def test_interrupted_run_keeps_finished_cases_and_leaves_the_rest_unfinished(tmp_path):
    runner = make_runner(tmp_path, "C1", QuotaLLM([SAMPLE], calls_left=1), part=1)

    with pytest.raises(RunInterrupted, match="stopped at case 03"):
        runner.run_all()

    run_dir = tmp_path / "run" / "C1"
    assert (run_dir / "01" / "validation.json").exists()      # finished before the limit
    assert not (run_dir / "03" / "validation.json").exists()  # NOT recorded as a failed generation
    assert not (run_dir / "05").exists()
    assert runner.ran == ["01"]


def test_resume_skips_finished_cases_and_never_rewrites_them(tmp_path):
    first = make_runner(tmp_path, "C1", QuotaLLM([SAMPLE], calls_left=1), part=1)
    with pytest.raises(RunInterrupted):
        first.run_all()
    finished = tmp_path / "run" / "C1" / "01"
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in finished.iterdir()}

    second = make_runner(tmp_path, "C1", MockLLM([SAMPLE]), part=2)
    records = second.run_all()

    assert second.skipped == ["01"] and second.ran == ["03", "05"]
    assert [r["case_id"] for r in records] == CASES                      # complete result list
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in finished.iterdir()} == before
    assert second.logger.log_path.name == "C1_rep1_part2.jsonl"          # new log part
    assert logged_cases(second) == ["03", "05"]                           # no LLM call for case 01
    assert logged_cases(first) == ["01"]                                  # first part's log is untouched


def test_resuming_a_complete_condition_runs_nothing(tmp_path):
    make_runner(tmp_path, "C1", MockLLM([SAMPLE]), part=1).run_all()
    llm = MockLLM([SAMPLE])
    again = make_runner(tmp_path, "C1", llm, part=2)
    again.run_all()
    assert again.ran == [] and llm.prompts_received == []


def test_c3_quota_inside_mediation_stops_the_run_instead_of_mediation_failed(tmp_path):
    agent_llms = {role: create_llm(CONFIG, role) for role in MEDIATION_ROLES}
    agent_llms["relevance"] = QuotaLLM([create_llm(CONFIG, "relevance").responses[0]], calls_left=2)
    runner = make_runner(tmp_path, "C3", create_llm(CONFIG), part=1, agent_llms=agent_llms)

    with pytest.raises(RunInterrupted, match="stopped at case 01"):
        runner.run_all()

    mediation = tmp_path / "run" / "C3" / "mediation"
    assert not (mediation / "01.json").exists()       # incomplete mediation is not saved as a result
    assert not (tmp_path / "run" / "C3" / "01" / "validation.json").exists()


def test_c3_resume_reuses_complete_mediation(tmp_path):
    # Part 1: mediation of case 01 completes, then the quota runs out during generation.
    agent_llms = {role: create_llm(CONFIG, role) for role in MEDIATION_ROLES}
    first = make_runner(tmp_path, "C3", QuotaLLM([SAMPLE], calls_left=0), part=1, agent_llms=agent_llms)
    with pytest.raises(RunInterrupted, match="stopped at case 01"):
        first.run_all()
    mediation_file = tmp_path / "run" / "C3" / "mediation" / "01.json"
    saved = mediation_file.read_bytes()

    # Part 2: the saved mediation of case 01 is reused; the mediation agents are not called for it.
    fresh_agents = {role: create_llm(CONFIG, role) for role in MEDIATION_ROLES}
    second = make_runner(tmp_path, "C3", MockLLM([SAMPLE]), part=2, agent_llms=fresh_agents)
    second.run_all()

    assert second.orchestrator.reused_cases == ["01"]
    assert mediation_file.read_bytes() == saved
    assert sum("[CRD-Art" in p or "[LPD-Art" in p for p in fresh_agents["relevance"].prompts_received) == 10
    summary = json.loads((tmp_path / "run" / "C3" / "mediation" / "run_summary.json").read_text())
    assert summary["cases"] == CASES and summary["n_passages"] == 15   # counted over both parts
