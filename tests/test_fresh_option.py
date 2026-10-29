"""--fresh in the debug scripts: unload_model unloads the model (keep_alive 0) before each run. Fake Ollama only."""

import json

import httpx
import pytest

import scripts.oracle_o2 as oracle
from scripts.debug_single_case import add_fresh_option, unload_model
from src.config import load_config

CONFIG = load_config()
MODEL = CONFIG["model"]["name"]


def fake_ollama(ps_answers: list[list[str]], requests: list):
    """A fake Ollama: records every request; /api/ps answers with the next list of loaded models."""
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/ps":
            loaded = ps_answers.pop(0) if len(ps_answers) > 1 else ps_answers[0]
            return httpx.Response(200, json={"models": [{"name": n} for n in loaded]})
        return httpx.Response(200, json={"done": True, "done_reason": "unload"})
    return httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handle))


def test_unload_sends_keep_alive_0_for_the_configured_model():
    requests = []
    unload_model(CONFIG, fake_ollama([[]], requests), sleep=lambda s: None)
    generate = requests[0]
    assert generate.url.path == "/api/generate"
    assert json.loads(generate.content) == {"model": MODEL, "keep_alive": 0}   # no prompt: nothing is generated


def test_unload_waits_until_ollama_no_longer_lists_the_model():
    requests, sleeps = [], []
    unload_model(CONFIG, fake_ollama([[MODEL], [MODEL], []], requests), sleep=sleeps.append)
    assert [r.url.path for r in requests] == ["/api/generate", "/api/ps", "/api/ps", "/api/ps"] and sleeps == [1, 1]


def test_unload_stops_if_the_model_stays_loaded():
    with pytest.raises(RuntimeError, match="still loaded"):
        unload_model(CONFIG, fake_ollama([[MODEL]], []), sleep=lambda s: None, wait_seconds=3)


def test_fresh_is_off_by_default():
    import argparse
    parser = argparse.ArgumentParser()
    add_fresh_option(parser)
    assert parser.parse_args([]).fresh is False and parser.parse_args(["--fresh"]).fresh is True


@pytest.mark.parametrize("fresh", [False, True])
def test_oracle_unloads_before_every_run_only_with_fresh(monkeypatch, fresh):
    events = []
    monkeypatch.setattr(oracle, "make_llm", lambda config: (None, {"model": MODEL}))
    monkeypatch.setattr(oracle, "unload_model", lambda config: events.append("unload"))

    def fake_run(config, case, description, key, llm, run_dir, run_info, think_calls=(), think_llm=None):
        run_dir.mkdir(parents=True)
        events.append(("run", run_info["fresh"]))
        return {"run": run_dir.name, "records": [{"passage_id": oracle.TARGET, "label": "Indeterminate",
                                                  "label_cause": "x", "requirement": None}], "knowledge_block": ""}
    monkeypatch.setattr(oracle, "oracle_run", fake_run)
    oracle.main(["fresh_test"] + (["--fresh"] if fresh else []))
    one = (["unload"] if fresh else []) + [("run", fresh)]
    assert events == one * oracle.RUNS


@pytest.mark.parametrize("script", ["debug_single_case", "debug_mediation_on_passages", "debug_rag_v3_steps",
                                    "oracle_o2"])
def test_every_debug_script_has_the_option(script):
    from pathlib import Path
    source = Path(f"scripts/{script}.py").read_text(encoding="utf-8")
    assert "add_fresh_option(parser)" in source and "if args.fresh:\n            unload_model(config)" in source
    assert '"fresh": args.fresh' in source   # stored in 00_run_info.json
