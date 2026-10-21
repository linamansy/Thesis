"""Tests for OpenRouterLLM (Study 2 agents). OpenRouter is NEVER called: httpx.MockTransport answers instead,
and waiting is recorded only."""

import json

import httpx
import pytest

from run_experiment import MEDIATION_ROLES, create_llm
from src.agents.relevance_agent import RelevanceAgent
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.llm.openrouter_llm import MissingOpenRouterKeyError, OpenRouterLLM
from src.logger import RunLogger

MODEL = "qwen/qwen3.5-397b-a17b"
RETURNED = "qwen/qwen3.5-397b-a17b-20260301"   # OpenRouter may return a more exact name than the one requested
BASE = "https://openrouter.ai/api/v1"


def answer(content='{"answer": "yes"}', model=RETURNED, finish="stop", reasoning=None, provider="SomeProvider"):
    return httpx.Response(200, json={"model": model, "provider": provider, "choices": [
        {"finish_reason": finish, "message": {"role": "assistant", "content": content, "reasoning": reasoning}}]})


def fake_openrouter(*responses):
    """A client that answers with the given responses (or raises the given errors) in order."""
    queue, requests = list(responses), []

    def handler(request):
        requests.append(json.loads(request.content))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler)), requests


def make_llm(client, max_retries=2):
    waits = []
    llm = OpenRouterLLM(MODEL, 0, 8192, 42, False, BASE, 300, max_retries, 2, client=client, sleep=waits.append)
    return llm, waits


def test_request_sends_temperature_0_and_the_agent_settings():
    client, requests = fake_openrouter(answer())
    llm, _ = make_llm(client)
    assert llm.complete("Hello") == '{"answer": "yes"}'
    assert requests == [{"model": MODEL, "messages": [{"role": "user", "content": "Hello"}], "temperature": 0,
                         "max_tokens": 8192, "seed": 42, "reasoning": {"enabled": False}}]


def test_records_the_exact_model_name_returned():
    client, _ = fake_openrouter(answer())
    llm, _ = make_llm(client)
    llm.complete("Hello")
    assert llm.last_response_model == RETURNED and llm.model_for_log == RETURNED
    assert llm.last_upstream_provider == "SomeProvider"


def test_finish_reason_and_reasoning():
    client, _ = fake_openrouter(answer(finish="length", reasoning="Let me think."))
    llm, _ = make_llm(client)
    llm.complete("Hello")
    assert llm.last_finish_reason == "MAX_TOKENS" and llm.last_reasoning == "Let me think."


@pytest.mark.parametrize("failure", [httpx.Response(429, json={"error": {"message": "rate limited"}}),
                                     httpx.Response(502, text="bad gateway"),
                                     httpx.ConnectError("refused"), httpx.ReadTimeout("slow"),
                                     httpx.Response(200, json={"error": {"code": 503, "message": "overloaded"}})])
def test_temporary_errors_are_retried_with_increasing_waits(failure):
    client, requests = fake_openrouter(failure, failure, answer())
    llm, waits = make_llm(client)
    assert llm.complete("Hello") == '{"answer": "yes"}'
    assert waits == [2, 4] and len(requests) == 3


def test_gives_up_after_the_retries():
    failure = httpx.Response(500, text="server error")
    client, _ = fake_openrouter(failure, failure, failure)
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match="after 2 retries"):
        llm.complete("Hello")
    assert waits == [2, 4]


@pytest.mark.parametrize("failure", [httpx.Response(401, json={"error": {"message": "No auth credentials"}}),
                                     httpx.Response(402, json={"error": {"message": "Insufficient credits"}}),
                                     httpx.Response(404, json={"error": {"message": "No such model"}}),
                                     httpx.Response(200, json={"error": {"code": 400, "message": "bad request"}})])
def test_other_errors_stop_at_once(failure):
    client, requests = fake_openrouter(failure)
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match="not retried"):
        llm.complete("Hello")
    assert waits == [] and len(requests) == 1


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(MissingOpenRouterKeyError):
        OpenRouterLLM(MODEL, 0, 8192, 42, False, BASE, 300, 2, 2)


def test_from_config_uses_the_one_model_and_the_agent_settings():
    config = load_config()
    config["model"] = dict(config["model"], provider="openrouter", name=MODEL)
    client, _ = fake_openrouter()
    llm = OpenRouterLLM.from_config(config, client=client)
    assert llm.model == MODEL
    assert (llm.temperature, llm.max_tokens, llm.seed) == (0, config["llm"]["max_tokens"], config["llm"]["seed"])
    assert llm.reasoning_enabled is config["openrouter"]["reasoning_enabled"] is False


def test_create_llm_gives_every_agent_the_same_openrouter_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")   # a client is made, but nothing is sent
    config = load_config()
    config["model"] = dict(config["model"], provider="openrouter", name=MODEL)
    shared = {}
    llms = {role: create_llm(config, role, shared) for role in MEDIATION_ROLES}
    assert all(isinstance(llm, OpenRouterLLM) for llm in llms.values())
    assert len({id(llm) for llm in llms.values()}) == 1


def test_an_existing_agent_runs_on_openrouter_and_logs_the_returned_model(tmp_path):
    output = {"relevant": True, "reason": "FAKE ANSWER for the test.", "evidence_process": "order",
              "evidence_passage": None}
    client, requests = fake_openrouter(answer(json.dumps(output)))
    llm, _ = make_llm(client)
    logger = RunLogger(tmp_path / "logs", "C3", "test")
    result = RelevanceAgent(llm, logger).run("19", description="The clerk checks the order.",
                                             passage_id="CRD-Art8-3", passage_text="Some rule.")
    assert result.relevant is True
    record = json.loads(logger.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["model"] == RETURNED and record["temperature"] == 0 and record["finish_reason"] == "STOP"
    assert "[CRD-Art8-3] Some rule." in requests[0]["messages"][0]["content"]
