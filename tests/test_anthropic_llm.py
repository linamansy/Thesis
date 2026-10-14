"""Tests for AnthropicLLM. The real API is NEVER called: a fake client stands in for it,
and waiting is replaced by a function that only records how long it would have waited."""

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from run_experiment import create_llm
from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.llm.anthropic_llm import AnthropicLLM, MissingAPIKeyError
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

CONFIG = load_config()
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_error(error_class, status):
    return error_class(f"simulated {status}", response=httpx2.Response(status, request=REQUEST), body=None)


def answer(text='{"answer": "yes"}', model="claude-test-model-2026"):
    """What a successful API response looks like: a thinking block (ignored) and a text block."""
    return SimpleNamespace(model=model, stop_reason="end_turn",
                           content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Stands in for anthropic.Anthropic: raises the given errors in order, then answers."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.messages = self   # so that client.messages.create(...) works

    def create(self, **params):
        self.calls.append(params)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_llm(client, temperature=0, max_retries=5):
    waits = []
    llm = AnthropicLLM("claude-test-model", temperature, 4096, max_retries, 2, client=client, sleep=waits.append)
    return llm, waits


# ---------- retries on temporary errors ----------

def test_retries_on_rate_limit_with_increasing_waits():
    client = FakeClient(api_error(anthropic.RateLimitError, 429), api_error(anthropic.RateLimitError, 429), answer())
    llm, waits = make_llm(client)

    text = llm.complete("Hello")

    assert text == '{"answer": "yes"}'
    assert len(client.calls) == 3            # 2 failures + 1 success
    assert waits == [2, 4]                    # increasing waits, no real sleeping
    assert client.calls[0] == client.calls[2]  # the identical request is repeated


@pytest.mark.parametrize("error", [
    api_error(anthropic.OverloadedError, 529),
    api_error(anthropic.InternalServerError, 500),
    api_error(anthropic.ServiceUnavailableError, 503),
    anthropic.APITimeoutError(request=REQUEST),
    anthropic.APIConnectionError(request=REQUEST),
])
def test_other_temporary_errors_are_retried(error):
    llm, waits = make_llm(FakeClient(error, answer()))
    assert llm.complete("Hello") == '{"answer": "yes"}'
    assert waits == [2]


def test_gives_up_after_five_retries():
    client = FakeClient(*[api_error(anthropic.RateLimitError, 429)] * 6)
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match="after 5 retries"):
        llm.complete("Hello")
    assert len(client.calls) == 6             # first attempt + 5 retries
    assert waits == [2, 4, 8, 16, 32]


@pytest.mark.parametrize("error", [api_error(anthropic.BadRequestError, 400),
                                   api_error(anthropic.NotFoundError, 404)])
def test_other_api_errors_are_not_retried_and_stop_the_run(error):
    client = FakeClient(error, answer())
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match="not retried"):
        llm.complete("Hello")
    assert len(client.calls) == 1 and waits == []


# ---------- request and response ----------

def test_request_uses_config_values_and_returns_only_text():
    client = FakeClient(answer())
    llm, _ = make_llm(client)
    llm.complete("Model this process")
    assert client.calls[0] == {"model": "claude-test-model", "max_tokens": 4096, "temperature": 0,
                               "messages": [{"role": "user", "content": "Model this process"}]}


def test_temperature_null_is_not_sent():
    client = FakeClient(answer())
    llm, _ = make_llm(client, temperature=None)
    llm.complete("x")
    assert "temperature" not in client.calls[0]


def test_exact_returned_model_string_is_logged(tmp_path):
    class Out(BaseModel):
        answer: str

    class Agent(BaseAgent):
        output_schema = Out

        def build_prompt(self, question):
            return question

    llm, _ = make_llm(FakeClient(answer(model="claude-test-model-2026-10-01")))
    logger = RunLogger(tmp_path, "C1", "test")
    Agent(llm, logger, max_retries=1).run(case_id="01", question="?")

    record = json.loads(open(logger.log_path, encoding="utf-8").readline())
    assert record["model"] == "claude-test-model-2026-10-01"   # what the API returned, not what was asked
    assert record["temperature"] == 0


# ---------- setup errors ----------

def test_missing_api_key_stops_with_clear_message(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError, match="ANTHROPIC_API_KEY is not set"):
        AnthropicLLM("claude-test-model", 0, 4096, 5, 2)


def test_placeholder_model_is_refused():
    with pytest.raises(ValueError, match="real Claude model id"):
        AnthropicLLM("MODEL_NAME_PLACEHOLDER", 0, 4096, 5, 2, client=FakeClient())


def test_key_is_read_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test-not-a-real-key\n", encoding="utf-8")
    config = dict(CONFIG, llm=dict(CONFIG["llm"], provider="anthropic", model="claude-test-model"),
                  paths=dict(CONFIG["paths"], env_file=str(tmp_path / ".env")))

    llm = create_llm(config, "relevance")   # builds the real SDK client, but makes no request

    assert isinstance(llm, AnthropicLLM)
    assert llm.client.api_key == "sk-test-not-a-real-key"
    assert llm.client.max_retries == 0      # the SDK's own retries are off; AnthropicLLM retries itself
    assert llm.temperature == CONFIG["llm"]["temperature"] and llm.max_tokens == CONFIG["llm"]["max_tokens"]


def test_unknown_provider_is_refused():
    with pytest.raises(ValueError, match="must be one of \\['mock', 'ollama', 'gemini', 'anthropic'\\]"):
        create_llm(dict(CONFIG, llm=dict(CONFIG["llm"], provider="openai")))
