"""Tests for the preflight (src/preflight.py, fix E1). No BPMNGen, no Ollama: the fake harness of
tests/test_bpmngen_generator.py, a fake BPMNGen file hasher, a fake Ollama probe and MockLLM agents.
The analysis plan lives in a throwaway git repository (skipped without git)."""

import hashlib
import json
import shutil
import subprocess

import pytest

from run_experiment import MEDIATION_ROLES, create_llm
from src.bpmngen_generator import BPMNGenGenerator
from src.config import project_path
from src.llm.base_llm import LLMUnavailableError
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.preflight import FAIL, PASS, SKIP, Preflight

from test_bpmngen_generator import bpmngen_config, fake_harness

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
HASHES = {"tools/ai/opensource.ts": "a" * 64}


class FakeFiles:
    def __init__(self, hashes=HASHES):
        self._hashes = hashes

    def hashes(self):
        return self._hashes


class FakeProbe:
    def __init__(self, digest, tokens=3000, up=True):
        self._digest, self.tokens, self.up, self.counted = digest, tokens, up, []

    def digest(self):
        if not self.up:
            raise LLMUnavailableError("connection refused")
        return self._digest

    def prompt_tokens(self, request):
        self.counted.append(request)
        return self.tokens


def sha(path):
    return hashlib.sha256(project_path(path).read_bytes()).hexdigest()


def make(tmp_path, plan_frozen=None, hashes=HASHES, probe=None, test_ids=(), generator_runner=None, **config_changes):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    config = bpmngen_config()
    frozen_sha = plan_frozen or sha(config["paths"]["frozen_retrieval"])
    plan = repo / "ANALYSIS_PLAN.md"
    plan.write_text(f"# Plan\n- addendum: `data/retrieval/frozen_retrieval.json` SHA-256 `{frozen_sha}`; "
                    f"`data/knowledge/passages.jsonl` SHA-256 `{sha(config['paths']['passages'])}`.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "plan"], cwd=repo, check=True, capture_output=True)
    record = tmp_path / "bpmngen_hashes.json"
    record.write_text(json.dumps({"hashes": hashes}), encoding="utf-8")
    config["paths"] = dict(config["paths"], analysis_plan=str(plan), bpmngen_expected_hashes=str(record),
                           **config_changes.pop("paths", {}))
    config["cases"] = dict(config["cases"], test_ids=list(test_ids))
    config |= config_changes
    generator = BPMNGenGenerator(config, RunLogger(tmp_path / "logs", "C1", "t"), runner=generator_runner or fake_harness())
    # bpmngen_config() names the real provider (ollama); the agents here must ALWAYS be MockLLM, never a real model
    mock_config = dict(config, model=dict(config["model"], provider="mock"))
    agents = {role: create_llm(mock_config, role, {}) for role in MEDIATION_ROLES}
    assert all(isinstance(llm, MockLLM) for llm in agents.values())
    probe = probe or FakeProbe(config["model"]["ollama_model_digest"])
    return Preflight(config, tmp_path / "preflight", generator=generator, files=FakeFiles(), probe=probe,
                     agent_llms=agents), probe


def statuses(preflight):
    return [status for status, _ in preflight.lines]


def test_everything_ready_passes_with_one_line_per_check(tmp_path):
    preflight, probe = make(tmp_path)
    assert preflight.run() is True
    texts = [text for _, text in preflight.lines]
    assert statuses(preflight).count(FAIL) == 0 and statuses(preflight)[-1] == SKIP   # no test cases defined
    assert any("analysis plan committed" in t for t in texts)
    assert any("frozen_retrieval.json checksum matches the plan" in t for t in texts)
    assert any("C3 prompts match frozen C3 v1" in t for t in texts)
    assert any("differ only in the knowledge block" in t for t in texts)
    assert sum("counted by Ollama" in t for t in texts) == 6          # 2 sample cases x 3 conditions
    assert len(probe.counted) == 6
    assert "PREFLIGHT PASSED" in (tmp_path / "preflight" / "report.txt").read_text(encoding="utf-8")


def test_sample_is_the_development_cases_with_the_longest_c2_prompt(tmp_path):
    preflight, _ = make(tmp_path)
    sample = preflight.sample_cases()
    assert len(sample) == 2 and set(sample) <= set(preflight.config["cases"]["development_ids"])
    sizes = {c: len((preflight.cases_dir / c / "description.txt").read_text(encoding="utf-8")) + len(preflight.c2_block(c))
             for c in preflight.config["cases"]["development_ids"]}
    assert min(sizes[c] for c in sample) >= max(s for c, s in sizes.items() if c not in sample)


def test_wrong_frozen_checksum_in_the_plan_fails(tmp_path):
    preflight, _ = make(tmp_path, plan_frozen="0" * 64)
    assert preflight.run() is False
    assert any(s == FAIL and "differs from the plan" in t for s, t in preflight.lines)


def test_changed_c3_prompt_fails(tmp_path):
    changed = tmp_path / "relevance_prompt.txt"
    changed.write_text(project_path("prompts/relevance_prompt.txt").read_text(encoding="utf-8") + "x", encoding="utf-8")
    preflight, _ = make(tmp_path, paths={"relevance_prompt": str(changed)})
    assert preflight.run() is False
    assert any(s == FAIL and "prompt:relevance" in t for s, t in preflight.lines)


def test_other_model_digest_or_bpmngen_files_fail(tmp_path):
    preflight, _ = make(tmp_path, probe=FakeProbe("f" * 64))
    preflight.files = FakeFiles({"tools/ai/opensource.ts": "b" * 64})
    assert preflight.run() is False
    texts = [t for s, t in preflight.lines if s == FAIL]
    assert any("model digest" in t for t in texts) and any("BPMNGen files differ" in t for t in texts)


def test_without_ollama_development_cases_are_not_checked_and_test_cases_are_estimated(tmp_path):
    preflight, _ = make(tmp_path, probe=FakeProbe(None, up=False), test_ids=["03"])
    assert preflight.run() is False
    texts = [t for _, t in preflight.lines]
    assert any("Ollama not reachable" in t for t in texts)
    assert any("development sample cases: not checked" in t for t in texts)
    assert sum("ESTIMATE" in t for t in texts) == 2                   # test case 03: C1 and C2 only
    assert not (tmp_path / "preflight" / "mediation").exists()        # agents never ran (no development case)


def test_agents_run_only_on_development_cases(tmp_path):
    preflight, _ = make(tmp_path, test_ids=["05"])
    preflight.config["cases"] = dict(preflight.config["cases"], development_ids=["01", "03"])
    preflight.run()
    mediated = sorted(p.stem for p in (tmp_path / "preflight" / "mediation").glob("*.json") if p.stem != "run_summary")
    assert mediated == sorted(preflight.sample_cases()) and "05" not in mediated
    assert any("test case 05: C1/C2 requests differ only" in t for _, t in preflight.lines)


def test_too_long_prompt_fails(tmp_path):
    preflight, probe = make(tmp_path)
    probe.tokens = 14000                                                # > 80% of 16384 = 13107
    assert preflight.run() is False
    assert any(s == FAIL and "14000 tokens" in t and ">= 13107" in t for s, t in preflight.lines)


def test_request_that_differs_from_config_fails(tmp_path):
    preflight, _ = make(tmp_path, generator_runner=fake_harness(request_changes={"think": True}))
    assert preflight.run() is False
    assert any(s == FAIL and "GeneratorSetupError" in t for s, t in preflight.lines)
