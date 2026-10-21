"""Tests for BPMNGenServerGenerator (Study 2) and the bpmngen_server path of run_experiment.

BPMNGen is NEVER called: httpx.MockTransport plays the BPMNGen server. Like the real server it answers
POST /auth/login and POST /threads, writes a debug file into a temporary "BPMNGen folder" and appends
console lines to a temporary server log.
"""

import hashlib
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from run_experiment import ExperimentRunner, check_same_model
from src.bpmngen_generator import GeneratorSetupError
from src.bpmngen_server_generator import BPMNGenServerGenerator, parse_debug_info, read_log_text
from src.config import load_config
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger
from src.prompt_texts import load_no_knowledge_text
from src.run_folder import RunFolder

from bpmn_helpers import make_bpmn, sequential_model

MODEL = "qwen/qwen3.5-397b-a17b"
ENV = {"BPMNGEN_SERVER_EMAIL": "runner@example.com", "BPMNGEN_SERVER_PASSWORD": "not-a-real-password"}
DESCRIPTION = "The clerk checks the order."
XML = make_bpmn(*sequential_model())


def server_config(tmp_path: Path) -> dict:
    """config.yaml with generator.type bpmngen_server and a temporary BPMNGen folder and server log."""
    config = load_config()
    server_dir = tmp_path / "bpmngen" / "server"
    for name in config["bpmngen_server"]["instruction_files"]:
        (server_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (server_dir / name).write_text(f"instructions of {name}", encoding="utf-8")
    log = tmp_path / "server.log"
    log.write_text("Server is running on port 1207\n", encoding="utf-8")
    config["generator"] = dict(config["generator"], type="bpmngen_server", bpmngen_server_dir=str(server_dir))
    config["bpmngen_server"] = dict(config["bpmngen_server"], server_log_file=str(log))
    return config


def debug_html(info: dict) -> str:
    """A debug file as BPMNGen writes it: its JSON with \\n, \\r, \\" and backticks removed (ai.ts)."""
    text = json.dumps(info).replace("\\n", "").replace("\\r", "").replace('\\"', "").replace("`", "")
    return f"<html><script>const bpmnXML = `<xml/>`;\nconst jsonData = JSON.parse(`{text}`);\n</script></html>"


class FakeServer:
    """Plays BPMNGen's server. finish: the model's finish reason; continuation: print BPMNGen's continuation line;
    status/error: answer POST /threads with this HTTP error; usage_line: print the [AI-USAGE] line."""

    def __init__(self, config, finish="stop", continuation=False, status=201, error="", login_status=200,
                 usage_line=True, debug=True, think=""):
        self.server_dir = Path(config["generator"]["bpmngen_server_dir"])
        self.debug_dir = self.server_dir / config["bpmngen_server"]["debug_dir"]
        self.log = Path(config["bpmngen_server"]["server_log_file"])
        self.finish, self.continuation, self.status, self.error = finish, continuation, status, error
        self.login_status, self.usage_line, self.debug, self.think = login_status, usage_line, debug, think
        self.requests = []   # (method, path, json body, authorization header)
        self.threads = 0

    def console(self, text):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body, request.headers.get("authorization")))
        if request.url.path == "/auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={"error": "Invalid email or password"})
            return httpx.Response(200, json={"sessionToken": f"token-{len(self.requests)}", "user": {"role": "USER"}})
        if request.url.path == "/threads":
            self.console(f"POST /threads received")
            if self.status != 201:
                return httpx.Response(self.status, json={"error": self.error})
            self.threads += 1
            thread_id = f"thread-{self.threads}"
            messages = [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": body["inputString"]}]
            if self.continuation:
                self.console("[OpenRouterLLM] finish_reason=length — requesting continuation.")
            content = f"{self.think}{XML}"
            info = {"ai_input": {"model": body["model"], "messages": messages, "temperature": 0},
                    "ai_output": {"model": MODEL, "provider": "SomeProvider", "usage": {"prompt_tokens": 2100,
                                                                                       "completion_tokens": 900},
                                  "choices": [{"finish_reason": self.finish,
                                               "message": {"role": "assistant", "content": content}}]}}
            if self.usage_line:
                self.console(f"[AI-USAGE][diagram] model={MODEL} format=xml tokens={{}}")
            if self.debug:
                self.debug_dir.mkdir(parents=True, exist_ok=True)
                (self.debug_dir / f"debug_{thread_id}_1.html").write_text(debug_html(info), encoding="utf-8")
            return httpx.Response(201, json={"xml": XML, "model": f"{MODEL} (xml)", "threadId": thread_id})
        return httpx.Response(404, json={"error": "not found"})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://localhost:1207", transport=httpx.MockTransport(self.handler))


def make_generator(tmp_path, **server_options):
    config = server_config(tmp_path)
    server = FakeServer(config, **server_options)
    generator = BPMNGenServerGenerator(config, RunLogger(tmp_path / "logs", "C2", "test"), client=server.client(),
                                       env=ENV)
    return generator, server


def description_file(tmp_path):
    path = tmp_path / "description.txt"
    path.write_text(DESCRIPTION + "\n", encoding="utf-8")
    return path


def run_case(generator, tmp_path, case_id="19", knowledge="[CRD-Art8-3] passage text"):
    case_dir = tmp_path / "case" / case_id
    return generator.run(case_id, description_file(tmp_path), knowledge, case_dir), case_dir


# ---------- the request ----------

def test_request_body_has_the_study1_layout_and_config_settings(tmp_path):
    generator, server = make_generator(tmp_path)
    run_case(generator, tmp_path)
    method, path, body, auth = server.requests[1]
    label = load_config()["generator"]["knowledge_label"]
    assert (method, path) == ("POST", "/threads")
    assert body == {"inputString": f"{DESCRIPTION}\n\n{label}\n[CRD-Art8-3] passage text", "model": MODEL,
                    "mode": "quick", "format": "xml", "stream": False}
    assert auth == "Bearer token-1"


def test_c1_input_matches_the_harness_prompt_layout(tmp_path):
    """The same text the Study 1 harness builds: description, blank line, label, knowledge block."""
    generator, server = make_generator(tmp_path)
    no_knowledge = load_no_knowledge_text(load_config())
    run_case(generator, tmp_path, knowledge=no_knowledge)
    label = load_config()["generator"]["knowledge_label"]
    assert server.requests[1][2]["inputString"] == f"{DESCRIPTION}\n\n{label}\n{no_knowledge.strip()}"


def test_logs_in_before_each_case(tmp_path):
    generator, server = make_generator(tmp_path)
    run_case(generator, tmp_path, "19")
    run_case(generator, tmp_path, "21")
    assert [r[1] for r in server.requests] == ["/auth/login", "/threads", "/auth/login", "/threads"]
    assert server.requests[0][2] == {"email": ENV["BPMNGEN_SERVER_EMAIL"],
                                     "password": ENV["BPMNGEN_SERVER_PASSWORD"]}
    assert server.requests[3][3] == "Bearer token-3"   # the fresh token of the second login


# ---------- what is saved ----------

def test_saves_request_reply_debug_hashes_and_log_excerpt(tmp_path):
    generator, server = make_generator(tmp_path)
    meta, case_dir = run_case(generator, tmp_path)
    out = case_dir / "bpmngen"
    files = load_config()["bpmngen_server"]["files"]

    request = json.loads((out / files["request"]).read_text(encoding="utf-8"))
    assert request == server.requests[1][2] and "token" not in json.dumps(request)
    reply = json.loads((out / files["reply"]).read_text(encoding="utf-8"))
    assert reply == {"xml": XML, "model": f"{MODEL} (xml)", "threadId": "thread-1"}
    assert (out / files["debug"]).read_text(encoding="utf-8") == \
        (server.debug_dir / "debug_thread-1_1.html").read_text(encoding="utf-8")

    hashes = json.loads((out / files["instruction_hashes"]).read_text(encoding="utf-8"))
    for name in load_config()["bpmngen_server"]["instruction_files"]:
        assert hashes[name] == hashlib.sha256(f"instructions of {name}".encode("utf-8")).hexdigest()
    excerpt = (out / files["server_log"]).read_text(encoding="utf-8")
    assert "POST /threads received" in excerpt and "Server is running" not in excerpt   # only this case's lines

    assert (case_dir / "generated.bpmn").read_text(encoding="utf-8") == XML
    assert json.loads((out / files["meta"]).read_text(encoding="utf-8")) == meta
    assert meta["instruction_files_sha256"] == hashes


def test_meta_has_the_harness_keys_used_by_the_runner(tmp_path):
    generator, _ = make_generator(tmp_path)
    meta, _ = run_case(generator, tmp_path)
    assert meta["done_reason"] == "stop" and meta["timed_out"] is False and meta["fits_context"] is None
    assert meta["model_reported"] == MODEL and meta["ollama_model_reported"] == MODEL
    assert meta["upstream_provider"] == "SomeProvider" and meta["server_model"] == f"{MODEL} (xml)"
    assert (meta["temperature"], meta["prompt_tokens"], meta["output_tokens"]) == (0, 2100, 900)
    assert meta["raw_has_think_block"] is False and meta["debug_file"] == "debug_thread-1_1.html"


def test_log_record_has_the_messages_bpmngen_sent_and_the_reply(tmp_path):
    generator, _ = make_generator(tmp_path)
    run_case(generator, tmp_path)
    record = json.loads(generator.logger.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["component"] == "BPMNGenServerGenerator" and record["model"] == MODEL
    assert record["finish_reason"] == "stop" and record["valid_json"] is True
    assert json.loads(record["prompt"])[0] == {"role": "system", "content": "SYSTEM"}
    assert json.loads(record["raw_output"])["threadId"] == "thread-1"


def test_copies_the_newest_debug_file_of_this_thread(tmp_path):
    generator, server = make_generator(tmp_path)
    server.debug_dir.mkdir(parents=True)
    old = server.debug_dir / "debug_thread-1_0.html"
    old.write_text("old", encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    (server.debug_dir / "debug_thread-9_5.html").write_text("other thread", encoding="utf-8")
    meta, case_dir = run_case(generator, tmp_path)
    assert meta["debug_file"] == "debug_thread-1_1.html"
    assert "ai_output" in (case_dir / "bpmngen" / "debug.html").read_text(encoding="utf-8")


def test_debug_file_json_is_read_although_bpmngen_removes_escapes():
    info = {"ai_output": {"choices": [{"message": {"content": '<bpmn:task id="a" name="Check\norder"/>'}}]}}
    parsed = parse_debug_info(debug_html(info))
    assert parsed["ai_output"]["choices"][0]["message"]["content"] == "<bpmn:task id=a name=Checkorder/>"
    assert parse_debug_info("<html>no data</html>") is None


# ---------- continuation request ----------

def test_no_continuation(tmp_path):
    generator, _ = make_generator(tmp_path)
    meta, _ = run_case(generator, tmp_path)
    assert meta["continuation_requested"] is False and meta["continuation_failed"] is False


def test_continuation_is_recorded(tmp_path):
    generator, _ = make_generator(tmp_path, continuation=True)
    meta, _ = run_case(generator, tmp_path)
    assert meta["continuation_requested"] is True


def test_continuation_unknown_when_the_log_is_not_this_server(tmp_path, capsys):
    generator, _ = make_generator(tmp_path, usage_line=False)
    meta, _ = run_case(generator, tmp_path)
    assert meta["continuation_requested"] is None
    assert "continuation request unknown" in capsys.readouterr().out


def test_server_log_written_by_powershell_is_read(tmp_path):
    log = tmp_path / "ps.log"
    log.write_bytes("﻿[AI-USAGE][diagram] requesting continuation\n".encode("utf-16-le"))
    assert read_log_text(log) == "[AI-USAGE][diagram] requesting continuation\n"


def test_thinking_text_is_flagged(tmp_path):
    generator, _ = make_generator(tmp_path, think="<think>draft</think>")
    meta, _ = run_case(generator, tmp_path)
    assert meta["raw_has_think_block"] is True and meta["think_tags_in_answer"] == 2


# ---------- errors ----------

def test_model_failure_500_is_a_failed_generation(tmp_path):
    generator, _ = make_generator(tmp_path, status=500, error="Error generating response:\nError: Unable to "
                                                              "convert response to diagram output")
    with pytest.raises(RuntimeError, match="Unable to convert") as error:
        run_case(generator, tmp_path)
    assert not isinstance(error.value, (LLMUnavailableError, GeneratorSetupError))
    out = tmp_path / "case" / "19" / "bpmngen"
    assert json.loads((out / "meta.json").read_text(encoding="utf-8"))["http_status"] == 500
    assert "Unable to convert" in (out / "server_reply.json").read_text(encoding="utf-8")


@pytest.mark.parametrize("error", ["Error generating response:\nError: 401 No auth credentials found",
                                   "Error generating response:\nError: 429 Rate limit exceeded",
                                   "Error generating response:\nError: Connection error."])
def test_provider_errors_stop_the_run(tmp_path, error):
    generator, _ = make_generator(tmp_path, status=500, error=error)
    with pytest.raises(LLMUnavailableError):
        run_case(generator, tmp_path)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_refused_request_is_a_setup_error(tmp_path, status):
    generator, _ = make_generator(tmp_path, status=status, error="model not valid")
    with pytest.raises(GeneratorSetupError):
        run_case(generator, tmp_path)


def test_failed_login_is_a_setup_error(tmp_path):
    generator, server = make_generator(tmp_path, login_status=401)
    with pytest.raises(GeneratorSetupError, match="login failed"):
        run_case(generator, tmp_path)
    assert [r[1] for r in server.requests] == ["/auth/login"]   # nothing generated


def test_missing_debug_file_is_a_setup_error(tmp_path):
    generator, _ = make_generator(tmp_path, debug=False)
    with pytest.raises(GeneratorSetupError, match="PRODUCTION=false"):
        run_case(generator, tmp_path)


def test_server_not_reachable_stops_the_run(tmp_path):
    generator, _ = make_generator(tmp_path)

    def refuse(request):
        raise httpx.ConnectError("connection refused")
    generator.client = httpx.Client(base_url="http://localhost:1207", transport=httpx.MockTransport(refuse))
    with pytest.raises(LLMUnavailableError, match="not reachable"):
        run_case(generator, tmp_path)


def test_timeout_is_a_failed_generation(tmp_path):
    generator, server = make_generator(tmp_path)

    def slow(request):
        if request.url.path == "/threads":
            raise httpx.ReadTimeout("timed out")
        return server.handler(request)
    generator.client = httpx.Client(base_url="http://localhost:1207", transport=httpx.MockTransport(slow))
    meta, _ = run_case(generator, tmp_path)
    assert meta["timed_out"] is True and meta["seconds"] == generator.timeout_seconds


# ---------- setup checks ----------

def test_check_setup_passes(tmp_path):
    generator, _ = make_generator(tmp_path)
    generator.check_setup()


def test_check_setup_needs_the_server_log(tmp_path):
    generator, _ = make_generator(tmp_path)
    generator.server_log.unlink()
    with pytest.raises(FileNotFoundError, match="server log"):
        generator.check_setup()


def test_check_setup_needs_the_instruction_files(tmp_path):
    generator, _ = make_generator(tmp_path)
    (generator.server_dir / generator.instruction_files[0]).unlink()
    with pytest.raises(FileNotFoundError, match="instruction files"):
        generator.check_setup()


def test_check_setup_needs_the_account(tmp_path):
    config = server_config(tmp_path)
    generator = BPMNGenServerGenerator(config, RunLogger(tmp_path / "logs", "C1", "test"),
                                       client=FakeServer(config).client(), env={})
    with pytest.raises(GeneratorSetupError, match="BPMNGEN_SERVER_EMAIL"):
        generator.check_setup()


# ---------- run_experiment wiring ----------

def runner_for(tmp_path, condition="C1", **server_options):
    generator, server = make_generator(tmp_path, **server_options)
    config = server_config(tmp_path)
    logger = RunLogger(tmp_path / "logs", condition, "test")
    runner = ExperimentRunner(config, condition, None, logger, tmp_path / "run" / condition, bpmngen=generator)
    return runner, server


def test_experiment_runner_validates_the_server_model(tmp_path):
    runner, server = runner_for(tmp_path)
    record = runner.run_case("19")
    assert record["generation_succeeded"] is True and record["valid"] is True
    assert record["context_limit_hit"] is False and record["bpmngen"]["bpmnlint_valid"] is None
    assert server.requests[1][2]["inputString"].endswith(load_no_knowledge_text(load_config()).strip())


def test_experiment_runner_counts_a_cut_off_answer(tmp_path):
    runner, _ = runner_for(tmp_path, finish="length", continuation=True)
    record = runner.run_case("19")
    assert record["context_limit_hit"] is True and record["valid"] is False


def test_experiment_runner_creates_the_server_generator(tmp_path):
    config = server_config(tmp_path)
    runner = ExperimentRunner(config, "C1", None, RunLogger(tmp_path / "logs", "C1", "test"), tmp_path / "C1")
    assert isinstance(runner.generator, BPMNGenServerGenerator)


def test_run_folder_records_the_server_generator(tmp_path):
    config = server_config(tmp_path)
    assert RunFolder(config, "x", 1).settings["generator"] == f"bpmngen_server/{MODEL}"


def test_same_model_check(tmp_path):
    config = server_config(tmp_path)
    config["model"] = dict(config["model"], provider="ollama", name="qwen3:8b")
    with pytest.raises(ValueError, match="openrouter"):
        check_same_model(config)
    config["model"] = dict(config["model"], provider="openrouter", name="another/model")
    with pytest.raises(ValueError):
        check_same_model(config)
    config["model"] = dict(config["model"], provider="openrouter", name=MODEL)
    check_same_model(config)   # same model: passes
    config["model"]["provider"] = "mock"
    check_same_model(config)   # tests: no real model


def test_study1_generator_is_unchanged():
    """config.yaml still selects the Study 1 generator and model; the server is used only when chosen."""
    import yaml
    from src.config import CONFIG_PATH
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert raw["generator"]["type"] == "bpmngen" and raw["model"]["provider"] == "ollama"
    assert raw["model"]["name"] == "qwen3:8b"
