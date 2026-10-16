"""Tests for OllamaLLM (no real Ollama server: httpx.MockTransport answers instead)."""

import json

import httpx
import pytest

from src.llm.base_llm import LLMUnavailableError
from src.llm.ollama_llm import OllamaLLM, ollama_model_digest, strip_think


def make_llm(handler, retries=2):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaLLM("qwen3:8b", 0, "http://ollama:11434/", 16384, 60, retries, 2,
                     client=client, sleep=lambda s: None)


def answer(content, done_reason="stop"):
    return httpx.Response(200, json={"model": "qwen3:8b", "message": {"role": "assistant", "content": content},
                                     "done": True, "done_reason": done_reason,
                                     "prompt_eval_count": 120, "eval_count": 30})


def test_request_has_fixed_settings():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return answer('{"relevant": true}')

    llm = make_llm(handler)
    assert llm.complete("Is this relevant?") == '{"relevant": true}'
    body = seen["body"]
    assert seen["url"] == "http://ollama:11434/api/chat"
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["think"] is False
    assert body["options"] == {"num_ctx": 16384, "temperature": 0}
    assert body["format"] == "json"
    assert body["messages"] == [{"role": "user", "content": "Is this relevant?"}]


def test_reports_model_finish_reason_and_tokens():
    llm = make_llm(lambda r: answer("{}", done_reason="length"))
    llm.complete("x")
    assert llm.last_response_model == "qwen3:8b"
    assert llm.last_finish_reason == "length"
    assert (llm.last_prompt_tokens, llm.last_output_tokens) == (120, 30)


def test_think_blocks_are_removed():
    assert strip_think("<think>hmm</think>\n{\"a\": 1}") == '{"a": 1}'
    assert make_llm(lambda r: answer("<think>x</think>{}")).complete("x") == "{}"


def test_connection_errors_are_retried_then_stop_the_run():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("refused")

    llm = make_llm(handler, retries=2)
    with pytest.raises(LLMUnavailableError, match="not reachable"):
        llm.complete("x")
    assert len(calls) == 3 and llm.retry_waits == [2, 4]


def test_http_error_stops_the_run_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(404, text='{"error":"model not found"}')

    with pytest.raises(LLMUnavailableError, match="404"):
        make_llm(handler).complete("x")
    assert len(calls) == 1


def test_model_digest():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3:8b", "digest": "aaa"},
                                                    {"name": "qwen3:8b", "digest": "bbb"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ollama_model_digest("http://ollama:11434", "qwen3:8b", client) == "bbb"
    assert ollama_model_digest("http://ollama:11434", "mistral", client) is None
