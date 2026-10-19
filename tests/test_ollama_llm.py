"""Tests for OllamaLLM. Ollama is NEVER called: a fake client stands in for it, and
waiting is replaced by a function that only records how long it would have waited."""

import json

import httpx
import pytest
from pydantic import BaseModel

from run_experiment import MEDIATION_ROLES, create_llm
from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.llm.ollama_llm import OllamaLLM
from src.logger import RunLogger
from src.run_folder import RunFolder

CONFIG = load_config()
DIGEST = "a" * 64
TAGS = {"models": [{"name": "qwen3:8b", "digest": DIGEST}, {"name": "llama3:8b", "digest": "b" * 64}]}


def response(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://localhost:11434"))


def chat(content='{"answer": "yes"}', done_reason="stop"):
    return response(200, {"model": "qwen3:8b", "message": {"role": "assistant", "content": content},
                          "done": True, "done_reason": done_reason})


class FakeClient:
    """Stands in for httpx.Client: answers /api/tags with TAGS, and /api/chat with the given
    outcomes in order (an exception is raised, a response is returned)."""

    def __init__(self, *outcomes, tags=TAGS):
        self.outcomes = list(outcomes)
        self.tags = tags
        self.calls = []

    def request(self, method, path, json=None):
        self.calls.append((method, path, json))
        if path == "/api/tags":
            return response(200, self.tags)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def chat_calls(self):
        return [body for _, path, body in self.calls if path == "/api/chat"]


def make_llm(client, digest=DIGEST, max_retries=5):
    waits = []
    llm = OllamaLLM("qwen3:8b", 0, 8192, 42, 16384, False, digest, "http://localhost:11434", 900,
                    max_retries, 2, client=client, sleep=waits.append)
    return llm, waits


class Out(BaseModel):
    answer: str


class Agent(BaseAgent):
    output_schema = Out

    def build_prompt(self, question):
        return question


# ---------- request and response ----------

def test_request_sends_all_settings_with_thinking_off():
    client = FakeClient(chat())
    llm, _ = make_llm(client)
    assert llm.complete("Model this process") == '{"answer": "yes"}'
    body = client.chat_calls()[0]
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["think"] is False
    assert body["messages"] == [{"role": "user", "content": "Model this process"}]
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 16384, "num_predict": 8192}


def test_settings_are_read_from_config():
    config = dict(CONFIG, model=dict(CONFIG["model"], provider="ollama"))
    llm = OllamaLLM.from_config(config, client=FakeClient())
    shared, agents = CONFIG["model"], CONFIG["llm"]   # the one model block + the agents' own settings
    assert (llm.model, llm.temperature, llm.seed, llm.num_ctx, llm.think, llm.max_tokens) == (
        shared["name"], agents["temperature"], agents["seed"], shared["num_ctx"],
        shared["think"], agents["max_tokens"])
    assert llm.expected_digest == shared["ollama_model_digest"]


def test_model_name_digest_and_finish_reason_are_logged(tmp_path):
    llm, _ = make_llm(FakeClient(chat()))
    logger = RunLogger(tmp_path, "C1", "test")
    Agent(llm, logger, max_retries=1).run(case_id="19", question="?")

    record = json.loads(open(logger.log_path, encoding="utf-8").readline())
    assert (record["model"], record["model_digest"]) == ("qwen3:8b", DIGEST)
    assert record["finish_reason"] == "STOP" and record["temperature"] == 0


def test_cut_off_answer_is_logged_as_max_tokens(tmp_path):
    cut_off = chat(content='{"answ', done_reason="length")
    llm, _ = make_llm(FakeClient(cut_off, cut_off))
    logger = RunLogger(tmp_path, "C1", "test")
    Agent(llm, logger, max_retries=1).run(case_id="19", question="?")

    records = [json.loads(line) for line in open(logger.log_path, encoding="utf-8")]
    assert [(r["finish_reason"], r["valid_json"]) for r in records] == [("MAX_TOKENS", False)] * 2


def test_digest_is_checked_once_before_the_first_call():
    client = FakeClient(chat(), chat())
    llm, _ = make_llm(client)
    llm.complete("first")
    llm.complete("second")
    assert [path for _, path, _ in client.calls] == ["/api/tags", "/api/chat", "/api/chat"]


def test_other_digest_stops_the_run():
    client = FakeClient(chat())
    llm, _ = make_llm(client, digest="c" * 64)
    with pytest.raises(LLMUnavailableError, match="The model was changed"):
        llm.complete("x")
    assert client.chat_calls() == []           # no answer was asked for


def test_model_not_downloaded_stops_the_run():
    llm, _ = make_llm(FakeClient(chat(), tags={"models": []}))
    with pytest.raises(LLMUnavailableError, match="ollama pull qwen3:8b"):
        llm.complete("x")


# ---------- errors ----------

def test_ollama_not_running_is_retried_then_stops_the_run():
    class NotRunning:
        def request(self, method, path, json=None):
            raise httpx.ConnectError("connection refused")   # every request fails

    llm, waits = make_llm(NotRunning())
    with pytest.raises(LLMUnavailableError, match="Is Ollama running"):
        llm.complete("x")
    assert waits == [2, 4, 8, 16, 32]


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("simulated timeout"),
    httpx.ConnectError("simulated: Ollama restarting"),
    httpx.HTTPStatusError("server error", request=httpx.Request("POST", "/api/chat"),
                          response=httpx.Response(500, text="out of memory")),
])
def test_timeouts_and_server_errors_are_retried(error):
    llm, waits = make_llm(FakeClient(error, chat()))
    assert llm.complete("x") == '{"answer": "yes"}'
    assert waits == [2]


def test_404_is_not_retried():
    not_found = response(404, {"error": "model 'qwen3:8b' not found"})
    llm, waits = make_llm(FakeClient(not_found, chat()))
    with pytest.raises(LLMUnavailableError, match="not retried.*404.*not found"):
        llm.complete("x")
    assert waits == []


def test_api_error_does_not_mark_the_case_finished(tmp_path):
    """Ollama stops answering in the middle of a run: the case gets no validation.json."""
    from run_experiment import ExperimentRunner, RunInterrupted

    llm, _ = make_llm(FakeClient(*[httpx.ConnectError("refused")] * 6))
    runner = ExperimentRunner(CONFIG, "C1", llm, RunLogger(tmp_path / "logs", "C1", "test"), tmp_path / "C1")
    runner.case_ids = ["19"]
    with pytest.raises(RunInterrupted):
        runner.run_all()
    assert not runner.is_finished("19")


# ---------- setup ----------

def test_ollama_provider_shares_one_client():
    config = dict(CONFIG, model=dict(CONFIG["model"], provider="ollama"))
    shared = {}
    generator = create_llm(config, "generator", shared)   # makes no request
    agents = [create_llm(config, role, shared) for role in MEDIATION_ROLES]
    assert isinstance(generator, OllamaLLM)
    assert all(a is generator for a in agents)


def test_run_folder_records_the_digest_and_settings(tmp_path):
    config = dict(CONFIG, model=dict(CONFIG["model"], provider="ollama"),
                  paths=dict(CONFIG["paths"], runs=str(tmp_path)))
    settings = RunFolder(config, "smoke_test", 1).settings
    assert settings["model_digest"] == CONFIG["model"]["ollama_model_digest"]
    assert (settings["seed"], settings["num_ctx"], settings["think"]) == (42, 16384, False)
