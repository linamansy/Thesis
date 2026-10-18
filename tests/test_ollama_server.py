"""Tests for the Ollama server facts stored in run_info.json (version, digest, server environment variables).
Ollama is NEVER called: httpx.MockTransport answers instead, and the environment is a dictionary."""

import httpx
import pytest

from run_experiment import ollama_settings
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.ollama_server import ollama_version, server_environment
from src.run_folder import RunFolder

CONFIG = load_config()
DIGEST = CONFIG["llm"]["ollama_model_digest"]
EXPECTED_ENV = {"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}


def fake_ollama(version="0.40.6", digest=DIGEST):
    def handler(request):
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "model": "qwen3:8b", "digest": digest}]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def bpmngen_config():
    """The thesis settings (tests force the legacy generator, so switch BPMNGen back on, without running it)."""
    return dict(CONFIG, generator=dict(CONFIG["generator"], type="bpmngen"),
                llm=dict(CONFIG["llm"], provider="ollama", ollama_server_env=EXPECTED_ENV))


def test_config_fixes_the_server_settings():
    assert load_config()["llm"]["ollama_server_env"] == EXPECTED_ENV


def test_matching_server_environment_is_returned():
    assert server_environment(EXPECTED_ENV, EXPECTED_ENV.get) == EXPECTED_ENV


@pytest.mark.parametrize("actual", [
    {"OLLAMA_FLASH_ATTENTION": "1"},                                    # KV cache type not set
    {"OLLAMA_FLASH_ATTENTION": "0", "OLLAMA_KV_CACHE_TYPE": "q8_0"},    # flash attention off
])
def test_other_server_environment_refuses_to_start(actual):
    with pytest.raises(ValueError, match="restart Ollama"):
        server_environment(EXPECTED_ENV, actual.get)


def test_ollama_version_and_unreachable_server():
    assert ollama_version("http://localhost:11434", fake_ollama()) == "0.40.6"

    def refused(request):
        raise httpx.ConnectError("connection refused")
    with pytest.raises(LLMUnavailableError, match="not reachable"):
        ollama_version("http://localhost:11434", httpx.Client(transport=httpx.MockTransport(refused)))


def test_run_info_records_version_digest_and_server_settings(tmp_path):
    settings = ollama_settings(bpmngen_config(), fake_ollama(), EXPECTED_ENV.get)
    assert settings == {"generator_digest": DIGEST, "ollama_version": "0.40.6", "ollama_server_env": EXPECTED_ENV}

    config = dict(bpmngen_config(), paths=dict(CONFIG["paths"], runs=str(tmp_path)))
    folder = RunFolder(config, "ollama_rep1", 1, settings)
    folder.start_part("C1", 1, tmp_path / "log.jsonl")
    info = folder.read_info()
    assert (info["ollama_version"], info["ollama_server_env"]) == ("0.40.6", EXPECTED_ENV)

    # a later part after Ollama updated itself is refused: one run, one server version
    updated = RunFolder(config, "ollama_rep1", 1, ollama_settings(bpmngen_config(), fake_ollama("0.41.0"),
                                                                   EXPECTED_ENV.get))
    with pytest.raises(ValueError, match="other settings"):
        updated.check_can_start("C1")


def test_run_does_not_start_without_the_server_settings():
    with pytest.raises(ValueError, match="OLLAMA_KV_CACHE_TYPE"):
        ollama_settings(bpmngen_config(), fake_ollama(), {"OLLAMA_FLASH_ATTENTION": "1"}.get)
