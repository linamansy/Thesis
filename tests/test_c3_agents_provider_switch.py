"""Tests for the C3 agents' provider switch (config.yaml c3_agents_llm) and GroqLLM's agent mode, used only by the
stronger-model mediation diagnostic (scripts/run_mediation_strong.py). Groq is NEVER called (httpx.MockTransport),
no waiting happens, and the Ollama default is checked to stay exactly as before."""

import copy
import json

import httpx

import src.orchestrator_v2
from run_experiment import create_llm
from src.config import load_config
from src.llm.groq_llm import GroqLLM
from src.llm.mock_llm import MockLLM
from src.llm.ollama_llm import OllamaLLM
from src.mediation_test import run

CONFIG = load_config()
MODEL = CONFIG["c3_agents_llm"]["groq"]["model"]


def fake_groq(*responses):
    queue, requests = list(responses), []

    def handler(request):
        requests.append(json.loads(request.content))
        return queue.pop(0)
    return httpx.Client(base_url="https://api.groq.com/openai/v1", transport=httpx.MockTransport(handler)), requests


def answer(content='{"relevant": true}'):
    return httpx.Response(200, json={"model": MODEL, "choices": [{"finish_reason": "stop",
                                                                   "message": {"content": content}}]})


def agent_llm(tmp_path, *responses):
    client, requests = fake_groq(*responses)
    config = copy.deepcopy(CONFIG)
    config["c3_agents_llm"]["groq"]["cache_dir"] = str(tmp_path / "cache")
    waits = []
    return GroqLLM.from_agent_config(config, client=client, sleep=waits.append), requests, waits


def real_config(agents_provider):
    """The config as in a real run (not forced to mock), with the given agents provider."""
    config = copy.deepcopy(CONFIG)
    config["model"]["provider"] = "ollama"
    config["c3_agents_llm"]["provider"] = agents_provider
    return config


def test_default_is_ollama_and_unchanged():
    assert CONFIG["c3_agents_llm"]["provider"] == "ollama"
    config = real_config("ollama")
    for role in ("generator", "relevance", "applicability", "requirement"):
        llm = create_llm(config, role)
        assert type(llm) is OllamaLLM
        assert llm.request_body("p") == OllamaLLM.from_config(config).request_body("p")


def test_groq_switch_only_for_the_agents(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    config, shared = real_config("groq"), {}
    agents = [create_llm(config, role, shared) for role in ("relevance", "applicability", "requirement")]
    assert all(a is agents[0] for a in agents) and type(agents[0]) is GroqLLM and agents[0].model == MODEL
    assert type(create_llm(config, "generator", shared)) is OllamaLLM


def test_force_mock_still_wins():
    config = copy.deepcopy(CONFIG)
    config["c3_agents_llm"]["provider"] = "groq"
    assert type(create_llm(config, "relevance")) is MockLLM


def test_agent_request_same_settings_as_ollama_agents(tmp_path):
    llm, requests, _ = agent_llm(tmp_path, answer())
    assert llm.complete("Is this relevant?") == '{"relevant": true}'
    assert requests[0] == {"model": MODEL, "messages": [{"role": "user", "content": "Is this relevant?"}],
                           "temperature": 0, "max_tokens": CONFIG["llm"]["max_tokens"], "seed": CONFIG["llm"]["seed"],
                           "response_format": {"type": "json_object"}}
    assert llm.last_finish_reason == "STOP"


def test_429_waits_resends_and_is_recorded(tmp_path):
    llm, requests, waits = agent_llm(tmp_path, httpx.Response(429, headers={"retry-after": "3"}), answer())
    assert llm.complete("p") == '{"relevant": true}'
    assert len(requests) == 2 and waits == [3.0]
    assert [r["http_status"] for r in llm.connection_retries] == [429]


def test_cache_sends_each_request_once(tmp_path):
    llm, requests, _ = agent_llm(tmp_path, answer('{"a": 1}'))
    assert llm.complete("p") == llm.complete("p") == '{"a": 1}'
    assert len(requests) == 1 and llm.cache_hits == 1
    again, requests2, _ = agent_llm(tmp_path)   # a new client (rerun) reads the same cache
    assert again.complete("p") == '{"a": 1}' and requests2 == []


def test_json_validate_failed_is_an_invalid_answer_not_a_stop(tmp_path):
    rejected = httpx.Response(400, json={"error": {"code": "json_validate_failed", "failed_generation": "not json"}})
    llm, _, _ = agent_llm(tmp_path, rejected)
    assert llm.complete("p") == "not json"
    assert llm.last_finish_reason == "JSON_VALIDATE_FAILED"


def test_silver_request_unchanged():
    llm = GroqLLM.from_config(CONFIG, client=fake_groq()[0])
    assert llm.request_body("p") == {"model": CONFIG["silver"]["model"], "messages": [{"role": "user", "content": "p"}],
                                     "temperature": 0, "max_tokens": CONFIG["silver"]["max_tokens"]}
    assert llm.cache_dir is None


def test_mediation_run_with_given_client_does_setting_o_only(tmp_path, monkeypatch):
    def fake_mediate(self, case_id, description, passage, passages):
        return {"passage_id": passage["passage_id"], "passage_text": passage["text"], "label": "Irrelevant"}
    monkeypatch.setattr(src.orchestrator_v2.OrchestratorV2, "mediate_passage", fake_mediate)
    m = run(CONFIG, "dev", llm=MockLLM(["{}"], temperature=0), out_dir=tmp_path, run_settings=("O",),
            model_label="test-model on Groq")
    records = json.loads((tmp_path / "answers.json").read_text(encoding="utf-8"))
    assert {r["setting"] for r in records} == {"O"}
    assert len(records) == 8 * 2 * 5 and m["summary"]["n_variants"] == 8 and m["summary"]["T1_hits"] == 0
    assert "test-model on Groq" in (tmp_path / "report.md").read_text(encoding="utf-8")
