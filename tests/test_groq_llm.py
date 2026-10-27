"""Tests for GroqLLM. Groq is NEVER called: httpx.MockTransport answers instead, and waiting is recorded only."""

import json

import httpx
import pytest
from pydantic import BaseModel

from src.agents.base_agent import BaseAgent
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.llm.groq_llm import GroqLLM, MissingGroqKeyError, parse_duration
from src.logger import RunLogger

CONFIG = load_config()
MODEL = "openai/gpt-oss-120b"


def answer(content='{"answer": "yes"}', model=MODEL, finish="stop", reasoning="Let me think.", fingerprint="fp_1"):
    return httpx.Response(200, json={"model": model, "system_fingerprint": fingerprint, "choices": [
        {"finish_reason": finish, "message": {"role": "assistant", "content": content, "reasoning": reasoning}}]})


def rate_limited(retry_after="3"):
    return httpx.Response(429, headers={"retry-after": retry_after}, json={"error": {"message": "Rate limit reached"}})


def fake_groq(*responses):
    """A client that answers with the given responses (or raises the given errors) in order."""
    queue, requests = list(responses), []

    def handler(request):
        requests.append(json.loads(request.content))
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    client = httpx.Client(base_url="https://api.groq.com/openai/v1", transport=httpx.MockTransport(handler))
    return client, requests


def make_llm(client, max_retries=2, max_wait=900):
    waits = []
    llm = GroqLLM(MODEL, 0, 5000, max_retries, 2, max_wait, "https://api.groq.com/openai/v1", 120,
                  CONFIG["silver"]["groq_max_rate_limit_waits"], client=client, sleep=waits.append)
    return llm, waits


def test_request_and_response():
    client, requests = fake_groq(answer())
    llm, _ = make_llm(client)
    assert llm.complete("Label this passage") == '{"answer": "yes"}'
    assert requests[0] == {"model": MODEL, "messages": [{"role": "user", "content": "Label this passage"}],
                           "temperature": 0, "max_tokens": 5000}
    assert (llm.last_response_model, llm.last_system_fingerprint, llm.last_finish_reason) == (MODEL, "fp_1", "STOP")
    assert llm.last_reasoning == "Let me think."


def test_settings_come_from_the_silver_section():
    llm = GroqLLM.from_config(dict(CONFIG, silver=dict(CONFIG["silver"], provider="groq")), client=fake_groq()[0])
    silver = CONFIG["silver"]
    assert (llm.model, llm.temperature, llm.max_tokens) == (silver["model"], 0, silver["max_tokens"])
    assert silver["model"] == MODEL and silver["provider"] == "groq"


def test_rate_limits_are_waited_out_and_not_counted_as_failures():
    # 6 rate limits in a row, more than max_retries=2: still succeeds, because 429 is not a failure
    client, requests = fake_groq(*[rate_limited("3")] * 6, answer())
    llm, waits = make_llm(client, max_retries=2)
    assert llm.complete("x") == '{"answer": "yes"}'
    assert waits == [3.0] * 6 and llm.rate_limit_waits == [3.0] * 6 and llm.retry_waits == []
    assert len(requests) == 7


def test_rate_limit_wait_from_reset_headers():
    reset = httpx.Response(429, headers={"x-ratelimit-reset-tokens": "7.5s", "x-ratelimit-reset-requests": "1m2s"})
    client, _ = fake_groq(reset, answer())
    llm, waits = make_llm(client)
    llm.complete("x")
    assert waits == [7.5]                        # the token (per-minute) reset, not the longer requests reset
    assert parse_duration("1m26.4s") == pytest.approx(86.4) and parse_duration("850ms") == pytest.approx(0.85)


def test_daily_limit_stops_the_run():
    client, _ = fake_groq(rate_limited("3600"))  # asked to wait an hour: daily limit
    llm, waits = make_llm(client, max_wait=900)
    with pytest.raises(LLMUnavailableError, match="daily limit"):
        llm.complete("x")
    assert waits == []


def test_server_errors_and_timeouts_are_counted_retries():
    client, _ = fake_groq(httpx.Response(503), httpx.ReadTimeout("slow"), answer())
    llm, waits = make_llm(client, max_retries=2)
    assert llm.complete("x") == '{"answer": "yes"}'
    assert llm.retry_waits == [2, 4] and llm.rate_limit_waits == []

    client, _ = fake_groq(*[httpx.Response(500)] * 3)
    llm, _ = make_llm(client, max_retries=2)
    with pytest.raises(LLMUnavailableError, match="after 2 retries"):
        llm.complete("x")


@pytest.mark.parametrize("status", [401, 404, 413])
def test_other_errors_stop_at_once(status):
    client, requests = fake_groq(httpx.Response(status, json={"error": {"message": "no"}}), answer())
    llm, waits = make_llm(client)
    with pytest.raises(LLMUnavailableError, match=f"not retried.*{status}"):
        llm.complete("x")
    assert len(requests) == 1 and waits == []


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(MissingGroqKeyError, match="GROQ_API_KEY is not set"):
        GroqLLM(MODEL, 0, 5000, 2, 2, 900, "https://api.groq.com/openai/v1", 120, 100)


def test_model_name_finish_reason_and_reasoning_are_logged(tmp_path):
    class Out(BaseModel):
        answer: str

    class Agent(BaseAgent):
        output_schema = Out

        def build_prompt(self, question):
            return question

    client, _ = fake_groq(answer(finish="length", content='{"ans'), answer())
    llm, _ = make_llm(client)
    logger = RunLogger(tmp_path, "SILVER", "test")
    Agent(llm, logger, max_retries=1).run(case_id="01", question="?")
    records = [json.loads(line) for line in open(logger.log_path, encoding="utf-8")]
    assert [(r["model"], r["finish_reason"], r["valid_json"]) for r in records] == [
        (MODEL, "MAX_TOKENS", False), (MODEL, "STOP", True)]
    assert records[1]["reasoning"] == "Let me think."   # the reasoning is saved too
