"""BPMNGenServerGenerator: the STUDY 2 generator. Sends one case to BPMNGen's own server route POST /threads.

Study 1 uses BPMNGenGenerator (src/bpmngen_generator.py, the harness). This class is used only when
config.yaml generator.type is "bpmngen_server". BPMNGen is private Ulm code: it runs as its own server
(npm start in generator.bpmngen_server_dir, see docs/BPMNGEN_SERVER_ROUTE.md) and no BPMNGen file is changed.

What changes between conditions: ONLY the knowledge block, exactly as in Study 1. The text sent to BPMNGen
(the field inputString) has the same layout as the harness prompt:
    <description>

    <knowledge_label>
    <knowledge block>          C1: "No domain knowledge provided."  C2: passages  C3: mediated block
Model, mode, format and stream come from config.yaml (bpmngen_server).

Steps for one case:
  1. log in (POST /auth/login with the account in .env; the token lasts only 15 minutes, so once per case)
  2. POST /threads with the body above; BPMNGen builds its own system prompt, calls the model, cleans the XML,
     makes a title with a second model call and saves the thread in its database
  3. save everything in the case's bpmngen/ folder (file names: bpmngen_server.files):
       server_request.json            the exact request body (the login token is not in it)
       server_reply.json              BPMNGen's full JSON reply, exactly as received
       debug.html                     copy of the newest BPMNGen debug file of this thread (data/assistant/debug/
                                      generated/debug_<threadId>_<time>.html). It holds the request BPMNGen sent to
                                      the model and the raw answer. BPMNGen removes \\n, \\r, \\" and backticks from
                                      it, so it is NOT byte-identical to what was sent (route doc, section 4)
       instruction_files_sha256.json  SHA-256 of BPMNGen's instruction files (bpmngen_server.instruction_files)
       server_log_excerpt.txt         the server's console lines written during this case
       meta.json                      what we know about the call (below)
       generated.bpmn                 the XML of the reply (also copied to the case folder, the file evaluated)

Continuation request: when the model stops with finish_reason "length", BPMNGen's OpenRouter class sends ONE
more request and joins the two answers (openrouter.ts). The debug file does not show this (it keeps the first
request and the joined answer). BPMNGen only prints it on its console, so the server's console output must be
written to bpmngen_server.server_log_file. meta.json continuation_requested is True / False, or None (unknown)
when the case's console lines do not contain BPMNGen's usage line (then the log is not this server's output).

Results and errors (the same rules as for Study 1):
  - server timeout (bpmngen_server.timeout_seconds) -> a FAILED generation with timed_out = True (model result)
  - answer still cut off (finish_reason not "stop") -> context_limit_hit, recorded by the runner (model result)
  - HTTP 500 that is a model failure (e.g. BPMNGen could not read the answer as a diagram) -> RuntimeError,
    recorded by the runner as a failed generation
  - server not reachable, or an HTTP 500 passing on an API error of the model provider (401, 402, 429, 5xx,
    connection error) -> LLMUnavailableError: the run stops, the case stays unfinished (resumable)
  - wrong setup (login fails, HTTP 400/401/403/404, no debug file because PRODUCTION is not false, debug file
    cannot be read) -> GeneratorSetupError: the run stops, never recorded as a model result
"""

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Callable

import httpx
from dotenv import load_dotenv

from src.bpmngen_generator import GeneratorSetupError, resolve
from src.config import project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

# In an HTTP 500 reply, BPMNGen passes on the error text of the model API (OpenAI SDK: "<status> <message>",
# or "Connection error."). These mean "the model provider could not be used", not a result of the model.
UNAVAILABLE_PATTERN = re.compile(r"\b(401|402|403|408|429|5\d\d)\b|Connection error|ECONNREFUSED|ETIMEDOUT|"
                                 r"ENOTFOUND|fetch failed", re.IGNORECASE)
# HTTP codes that mean our request or setup is wrong (bad model name, login, missing API key in BPMNGen).
SETUP_ERROR_CODES = (400, 401, 403, 404)
# The debug data in BPMNGen's debug file: const jsonData = JSON.parse(`...`);
DEBUG_INFO_PATTERN = re.compile(r"JSON\.parse\(`(.*?)`\)", re.DOTALL)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_log_text(path: Path) -> str:
    """The server's console output. PowerShell's '>' writes UTF-16 (with a byte order mark), cmd's '>' UTF-8."""
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


def parse_debug_info(html: str) -> dict | None:
    """The JSON data BPMNGen put into its debug file (ai_input, ai_output, tokens, ...); None if not readable."""
    match = DEBUG_INFO_PATTERN.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


class BPMNGenServerGenerator:
    """Runs one case through BPMNGen's POST /threads and returns meta data in the same form as the harness."""

    def __init__(self, config: dict, logger: RunLogger, client: httpx.Client | None = None,
                 env: dict | None = None, clock: Callable[[], float] = time.monotonic):
        """client (a fake server), env (the .env values) and clock can be replaced in tests."""
        g, s, paths = config["generator"], config["bpmngen_server"], config["paths"]
        self.server_dir = resolve(g["bpmngen_server_dir"])
        self.knowledge_label = g["knowledge_label"]   # the same neutral label as in Study 1
        self.url = s["url"].rstrip("/")
        self.model = s["model"]
        self.mode = s["mode"]
        self.format = s["format"]
        self.stream = s["stream"]
        self.timeout_seconds = s["timeout_seconds"]
        self.login_timeout_seconds = s["login_timeout_seconds"]
        self.debug_dir = self.server_dir / s["debug_dir"]
        self.server_log = resolve(s["server_log_file"])
        self.continuation_marker = s["continuation_marker"]
        self.continuation_failed_marker = s["continuation_failed_marker"]
        self.usage_marker = s["usage_marker"]
        self.instruction_files = s["instruction_files"]
        self.files = s["files"]
        self.knowledge_file = paths["knowledge_block_file"]
        self.out_dir_name = paths["bpmngen_output_dir"]
        self.bpmn_file = paths["generated_bpmn_file"]
        if env is None:
            load_dotenv(project_path(paths["env_file"]))  # puts the BPMNGen account into the environment
            env = os.environ
        self.email = env.get(s["email_variable"])
        self.password = env.get(s["password_variable"])
        self.email_variable, self.password_variable = s["email_variable"], s["password_variable"]
        self.client = client or httpx.Client(base_url=self.url)
        self.logger = logger
        self.clock = clock

    def check_setup(self) -> None:
        """Stop before any call if BPMNGen's files, the server log or the account are missing."""
        if not self.server_dir.exists():
            raise FileNotFoundError(f"BPMNGen server folder not found at {self.server_dir} "
                                    f"(generator.bpmngen_server_dir in config.yaml)")
        missing = [f for f in self.instruction_files if not (self.server_dir / f).exists()]
        if missing:  # BPMNGen would silently use a fallback sentence instead (ai.ts readInstructionsFile)
            raise FileNotFoundError(f"BPMNGen instruction files not found: {missing}")
        if not self.server_log.exists():
            raise FileNotFoundError(f"BPMNGen server log not found at {self.server_log} "
                                    f"(bpmngen_server.server_log_file). Start the server with its console output "
                                    f"written to this file, e.g. cmd /c \"npm start > {self.server_log} 2>&1\"")
        if not self.email or not self.password:
            raise GeneratorSetupError(f"BPMNGen account missing: set {self.email_variable} and "
                                      f"{self.password_variable} in .env")

    def input_string(self, description: str, knowledge: str) -> str:
        """The text sent as inputString: the same layout as the Study 1 harness prompt."""
        return f"{description.strip()}\n\n{self.knowledge_label}\n{knowledge.strip()}"

    def request_body(self, description: str, knowledge: str) -> dict:
        return {"inputString": self.input_string(description, knowledge), "model": self.model,
                "mode": self.mode, "format": self.format, "stream": self.stream}

    def instruction_hashes(self) -> dict:
        """SHA-256 of BPMNGen's instruction files for this model class, format and mode (read only)."""
        return {f: sha256_file(self.server_dir / f) for f in self.instruction_files}

    def login(self) -> str:
        """A fresh session token (valid 15 minutes)."""
        try:
            response = self.client.post("/auth/login", json={"email": self.email, "password": self.password},
                                        timeout=self.login_timeout_seconds)
        except httpx.TransportError as e:
            raise LLMUnavailableError(f"BPMNGen server not reachable at {self.url}: {e}") from e
        token = response.json().get("sessionToken") if response.status_code == 200 else None
        if not token:
            raise GeneratorSetupError(f"BPMNGen login failed (HTTP {response.status_code}): {response.text[:300]}")
        return token

    def run(self, case_id: str, description_file: Path, knowledge_block: str, case_dir: Path) -> dict:
        """Generate the BPMN model of one case. Returns meta.json (timed_out = True if the server was too slow)."""
        case_dir.mkdir(parents=True, exist_ok=True)
        knowledge_file = case_dir / self.knowledge_file
        knowledge_file.write_text(knowledge_block.strip() + "\n", encoding="utf-8")
        out_dir = case_dir / self.out_dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        f = self.files
        description = description_file.read_text(encoding="utf-8")
        body = self.request_body(description, knowledge_block)
        (out_dir / f["request"]).write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        hashes = self.instruction_hashes()
        (out_dir / f["instruction_hashes"]).write_text(json.dumps(hashes, indent=2), encoding="utf-8")

        token = self.login()
        log_before = len(read_log_text(self.server_log))
        start = self.clock()
        try:
            response = self.client.post("/threads", json=body, headers={"Authorization": f"Bearer {token}"},
                                        timeout=self.timeout_seconds)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise LLMUnavailableError(f"BPMNGen server not reachable at {self.url}: {e}") from e
        except httpx.TimeoutException:
            # The model (or BPMNGen) took too long: a result of the model (failed generation), not retried.
            meta = {"timed_out": True, "seconds": self.timeout_seconds, "done_reason": None, "valid": None,
                    "http_status": None, "continuation_requested": None, "instruction_files_sha256": hashes}
            self._save_log_excerpt(out_dir, log_before)
            self._finish(case_id, out_dir, meta, body, "")
            return meta
        except httpx.TransportError as e:
            raise LLMUnavailableError(f"BPMNGen server connection failed: {e}") from e
        seconds = round(self.clock() - start, 3)
        log_text = self._save_log_excerpt(out_dir, log_before)
        (out_dir / f["reply"]).write_text(response.text, encoding="utf-8")   # exactly as received
        try:
            reply = response.json()
        except ValueError:
            reply = {}

        if response.status_code != 201:
            error = str(reply.get("error") or reply.get("errors") or response.text)
            meta = {"timed_out": False, "seconds": seconds, "http_status": response.status_code,
                    "server_error": error, "done_reason": None, "valid": None, "continuation_requested":
                    self.continuation(log_text), "instruction_files_sha256": hashes}
            self._finish(case_id, out_dir, meta, body, response.text)
            if response.status_code in SETUP_ERROR_CODES:
                raise GeneratorSetupError(f"BPMNGen server refused the request (HTTP {response.status_code}): "
                                          f"{error[:500]}")
            if UNAVAILABLE_PATTERN.search(error):
                raise LLMUnavailableError(f"model provider not usable through BPMNGen (HTTP "
                                          f"{response.status_code}): {error[:500]}")
            raise RuntimeError(f"BPMNGen server error (HTTP {response.status_code}): {error[:1000]}")

        debug_name, debug_html = self._copy_debug_file(reply.get("threadId"), out_dir)
        info = parse_debug_info(debug_html)
        if info is None:
            raise GeneratorSetupError(f"BPMNGen debug file of case {case_id} could not be read "
                                      f"({out_dir / f['debug']})")
        meta = self.meta_from(reply, info, log_text, seconds, hashes) | {"debug_file": debug_name}
        xml = reply.get("xml") or ""
        if xml:
            (out_dir / f["bpmn"]).write_text(xml, encoding="utf-8")
            shutil.copyfile(out_dir / f["bpmn"], case_dir / self.bpmn_file)
        if meta["raw_has_think_block"]:
            print(f"WARNING case {case_id}: the model produced thinking text ({meta['thinking_chars']} chars of "
                  f"reasoning, {meta['think_tags_in_answer']} think tag(s) in the answer; see {f['debug']})")
        if meta["continuation_requested"] is None:
            print(f"WARNING case {case_id}: continuation request unknown: the server log {self.server_log} has no "
                  f"'{self.usage_marker}' line for this case")
        self._finish(case_id, out_dir, meta, body, response.text, info)
        return meta

    def continuation(self, log_text: str) -> bool | None:
        """True / False: did BPMNGen send a continuation request? None: this log is not the server's output."""
        if self.usage_marker not in log_text:
            return None
        return self.continuation_marker in log_text

    def meta_from(self, reply: dict, info: dict, log_text: str, seconds: float, hashes: dict) -> dict:
        """The meta data of a successful call, with the same keys as the harness's meta.json where they apply.
        After a continuation, BPMNGen keeps the token counts of the FIRST request only and the finish reason of
        the continuation (openrouter.ts)."""
        ai_input, ai_output = info.get("ai_input") or {}, info.get("ai_output") or {}
        choice = (ai_output.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning = message.get("reasoning") or ""
        usage = ai_output.get("usage") or {}
        think_tags = content.count("<think>") + content.count("</think>")
        return {
            "server_model": reply.get("model"),               # BPMNGen's "<name> (<format>)"
            "thread_id": reply.get("threadId"),
            "http_status": 201,
            "ollama_model_reported": ai_output.get("model"),  # key shared with the harness meta: the model name the
            "model_reported": ai_output.get("model"),         # API reported (here OpenRouter, not Ollama)
            "upstream_provider": ai_output.get("provider"),   # which OpenRouter provider answered
            "temperature": ai_input.get("temperature"),
            "num_ctx": None, "think_param": None,             # not set by BPMNGen's OpenRouter class
            "prompt_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "done_reason": choice.get("finish_reason"),
            "fits_context": None,
            "cut_off_by_harness": False,
            "raw_has_think_block": bool(reasoning) or think_tags > 0,
            "think_tags_in_answer": think_tags,
            "thinking_chars": len(reasoning),
            "auto_repairs": None,                             # BPMNGen's server path has no repair count
            "valid": None,                                    # no bpmnlint verdict in the server path
            "seconds": seconds,
            "timed_out": False,
            "continuation_requested": self.continuation(log_text),
            "continuation_failed": self.continuation_failed_marker in log_text,
            "instruction_files_sha256": hashes,
        }

    def _copy_debug_file(self, thread_id: str | None, out_dir: Path) -> tuple[str, str]:
        """Copy the newest debug file of this thread into bpmngen/; return its original name and its text."""
        found = sorted(self.debug_dir.glob(f"debug_{thread_id}_*.html"), key=lambda p: p.stat().st_mtime) \
            if thread_id and self.debug_dir.exists() else []
        if not found:
            raise GeneratorSetupError(f"no BPMNGen debug file for thread {thread_id} in {self.debug_dir}. "
                                      f"BPMNGen writes them only with PRODUCTION=false in its .env")
        shutil.copyfile(found[-1], out_dir / self.files["debug"])
        return found[-1].name, found[-1].read_text(encoding="utf-8", errors="replace")

    def _save_log_excerpt(self, out_dir: Path, log_before: int) -> str:
        text = read_log_text(self.server_log)[log_before:]
        (out_dir / self.files["server_log"]).write_text(text, encoding="utf-8")
        return text

    def _finish(self, case_id: str, out_dir: Path, meta: dict, body: dict, raw_reply: str,
                info: dict | None = None) -> None:
        """Write meta.json and one log record: the exact messages BPMNGen sent to the model (from its debug file;
        the request body when there is none), the reply and the meta data."""
        (out_dir / self.files["meta"]).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        messages = (info or {}).get("ai_input", {}).get("messages")
        self.logger.log_call(
            case_id=case_id,
            component=type(self).__name__,
            model=meta.get("model_reported") or self.model,
            temperature=meta.get("temperature"),
            prompt=json.dumps(messages if messages is not None else body, ensure_ascii=False),
            raw_output=raw_reply,
            parsed_output=meta,
            valid_json=meta.get("http_status") == 201,
            retries=0,
            duration_seconds=meta.get("seconds"),
            finish_reason=meta.get("done_reason"),
        )
