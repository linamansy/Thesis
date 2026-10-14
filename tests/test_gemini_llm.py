"""Tests for GeminiLLM. The real API is NEVER called: a fake client stands in for it, and
waiting is replaced by functions that only record how long they would have waited."""

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel

from run_experiment import MEDIATION_ROLES, create_llm
from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.llm.gemini_llm import GeminiLLM, MissingGeminiKeyError
from src.logger import RunLogger

CONFIG = load_config()


def api_error(code, status):
    error_class = errors.ClientError if code < 500 else errors.ServerError
    return error_class(code, {"error": {"code": code, "message": f"simulated {status}", "status": status}})


RATE_LIMIT = api_error(429, "RESOURCE_EXHAUSTED")


def answer(text='{"answer": "yes"}', model_version="gemini-test-001"):
    return SimpleNamespace(text=text, model_version=model_version,
                           candidates=[SimpleNamespace(finish_reason="STOP")])


class FakeClient:
    """Stands in for genai.Client: raises the given errors in order, then answers."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.models = self   # so that client.models.generate_content(...) works

    def generate_content(self, **params):
        self.calls.append(params)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_llm(client, max_retries=8, pause=0, clock=None):
    waits = []
    clock = clock or FakeClock()

    def sleep(seconds):
        waits.append(seconds)
        clock.sleep(seconds)

    llm = GeminiLLM("gemini-test-001", 0, 4096, max_retries, 2, pause, client=client, sleep=sleep, clock=clock)
    return llm, waits


# ---------- retries ----------

def test_retries_on_simulated_429_with_increasing_waits():
    client = FakeClient(RATE_LIMIT, RATE_LIMIT, answer())
    llm, waits = make_llm(client)

    assert llm.complete("Hello") == '{"answer": "yes"}'
    assert len(client.calls) == 3             # 2 rate-limit errors + 1 success, all via the fake client
    assert waits == [2, 4]
    assert llm.retry_waits == [2, 4]


@pytest.mark.parametrize("error", [
    api_error(503, "UNAVAILABLE"),            # overloaded
    api_error(500, "INTERNAL"),
    api_error(504, "DEADLINE_EXCEEDED"),
    httpx.ReadTimeout("simulated timeout"),
    httpx.ConnectError("simulated network error"),
])
def test_overload_server_errors_and_timeouts_are_retried(error):
    llm, waits = make_llm(FakeClient(error, answer()))
    assert llm.complete("Hello") == '{"answer": "yes"}'
    assert waits == [2]


def test_gives_up_after_eight_retries_with_llm_unavailable():
    client = FakeClient(*[RATE_LIMIT] * 9)
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match="after 8 retries"):
        llm.complete("Hello")
    assert len(client.calls) == 9             # first attempt + 8 retries
    assert waits == [2, 4, 8, 16, 32, 64, 128, 256]


def test_bad_request_is_not_retried():
    client = FakeClient(api_error(400, "INVALID_ARGUMENT"), answer())
    llm, waits = make_llm(client)
    with pytest.raises(errors.ClientError):
        llm.complete("Hello")
    assert len(client.calls) == 1 and waits == []


# ---------- request and response ----------

def test_request_sends_model_and_temperature_zero():
    client = FakeClient(answer())
    llm, _ = make_llm(client)
    llm.complete("Model this process")
    call = client.calls[0]
    assert call["model"] == "gemini-test-001" and call["contents"] == "Model this process"
    assert call["config"].temperature == 0 and call["config"].max_output_tokens == 4096


def test_empty_or_blocked_answer_becomes_empty_text():
    llm, _ = make_llm(FakeClient(SimpleNamespace(text=None, model_version="gemini-test-001", candidates=[])))
    assert llm.complete("x") == ""


def test_exact_model_version_is_logged(tmp_path):
    class Out(BaseModel):
        answer: str

    class Agent(BaseAgent):
        output_schema = Out

        def build_prompt(self, question):
            return question

    llm, _ = make_llm(FakeClient(answer(model_version="gemini-test-001-2026-09")))
    logger = RunLogger(tmp_path, "C1", "test")
    Agent(llm, logger, max_retries=1).run(case_id="01", question="?")

    record = json.loads(open(logger.log_path, encoding="utf-8").readline())
    assert record["model"] == "gemini-test-001-2026-09"
    assert record["temperature"] == 0
    assert record["finish_reason"] == "STOP"


def test_cut_off_answer_is_logged_as_max_tokens(tmp_path):
    from google.genai import types

    class Out(BaseModel):
        answer: str

    class Agent(BaseAgent):
        output_schema = Out

        def build_prompt(self, question):
            return question

    cut_off = SimpleNamespace(text='{"answ', model_version="gemini-test-001",
                              candidates=[SimpleNamespace(finish_reason=types.FinishReason.MAX_TOKENS)])
    llm, _ = make_llm(FakeClient(cut_off, cut_off))
    logger = RunLogger(tmp_path, "C1", "test")
    Agent(llm, logger, max_retries=1).run(case_id="01", question="?")

    records = [json.loads(line) for line in open(logger.log_path, encoding="utf-8")]
    assert [(r["finish_reason"], r["valid_json"]) for r in records] == [("MAX_TOKENS", False)] * 2


def test_pause_between_calls():
    clock = FakeClock()
    llm, waits = make_llm(FakeClient(answer(), answer(), answer()), pause=4, clock=clock)
    llm.complete("first")      # no pause before the first call
    clock.now += 1             # 1 second of other work
    llm.complete("second")     # waits the remaining 3 seconds
    clock.now += 10            # long enough: no pause needed
    llm.complete("third")
    assert llm.pause_waits == [3]


# ---------- setup ----------

def test_missing_key_stops_with_clear_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingGeminiKeyError, match="GEMINI_API_KEY is not set"):
        GeminiLLM("gemini-test-001", 0, 4096, 8, 2)


def test_placeholder_model_is_refused():
    with pytest.raises(ValueError, match="fixed Gemini model version"):
        GeminiLLM("MODEL_NAME_PLACEHOLDER", 0, 4096, 8, 2, client=FakeClient())


def test_gemini_provider_from_config_shares_one_client(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key-not-real\n", encoding="utf-8")
    config = dict(CONFIG, llm=dict(CONFIG["llm"], provider="gemini", model="gemini-test-001",
                                   gemini_pause_between_calls_seconds=4),
                  paths=dict(CONFIG["paths"], env_file=str(tmp_path / ".env")))

    shared = {}
    generator = create_llm(config, "generator", shared)   # builds the real client, but makes no request
    agents = [create_llm(config, role, shared) for role in MEDIATION_ROLES]

    assert isinstance(generator, GeminiLLM)
    assert all(a is generator for a in agents)   # one client: the pause counts over all agents together
    assert (generator.temperature, generator.api_max_retries, generator.pause_between_calls_seconds) == (0, 5, 4)
