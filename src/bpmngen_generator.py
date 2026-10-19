"""BPMNGenGenerator: the fixed BPMN generator for C1, C2 and C3 (BPMNGen with qwen3:8b on Ollama).

BPMNGen is private code from Ulm University. It is NOT copied into this project and NOT changed.
This class starts bpmngen_harness/run_bpmngen.ts (TypeScript, see its README) as a separate
process, once per case. The harness imports BPMNGen's own OpenSourceLLM class and runs the same
steps as BPMNGen's createBPMN(): fixed system prompt, one Ollama call, BPMNGen's XML cleanup.

What changes between conditions: ONLY the knowledge block. It is written to knowledge_block.txt
and the harness appends it to the description under ONE neutral label (config.yaml,
generator.knowledge_label), in the same place for C1, C2 and C3:
    <description>

    <knowledge_label>
    <knowledge block>          C1: "No domain knowledge provided."  C2: passages  C3: mediated block

Thinking (decided 18 Oct 2026): BPMNGen asks for no thinking with "/no_think" in its prompt, but newer Ollama
versions let qwen3 think anyway (in a separate field BPMNGen never reads). The harness therefore adds Ollama's
own switch think:false to BPMNGen's request (config.yaml generator.think_param); no BPMNGen file is changed.
Any thinking text that still appears is saved (bpmngen/raw_thinking.txt) and flagged.

Outputs of one case (results/runs/<run_id>/<condition>/<case_id>/):
    knowledge_block.txt        the exact knowledge text given to the generator
    bpmngen/                   everything the harness wrote: ollama_request.json (exact request),
                               raw_model_output.txt, raw_thinking.txt, bpmngen_cleaned_output.txt, generated.bpmn,
                               validation.json (BPMNGen's own bpmnlint check), meta.json
    generated.bpmn             copy of bpmngen/generated.bpmn, the file that is evaluated
The call is also logged as one RunLogger record (component "BPMNGenGenerator"), with the model digest.

Results and errors (decided 18 Oct 2026):
  - Answer cut off (the harness stops it when it passes the context window, or Ollama reports a length
    stop) -> a FAILED generation with context_limit_hit = True. It is a model result: scored, never retried.
  - Harness timeout -> the whole process tree (npx and its node child) is killed; a FAILED generation
    with timed_out = True. Also a result: scored, never retried.
  - Ollama not reachable / HTTP error -> LLMUnavailableError: the run stops and the case stays unfinished
    (resumable), the same rule as for the API clients.
  - Any other harness failure -> RuntimeError: recorded by the runner as a failed generation.
"""

import json
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable

import httpx

from src.config import project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

# Text in the harness error output that means "Ollama could not be used" (not a model result).
UNAVAILABLE_MARKERS = ("ECONNREFUSED", "fetch failed", "Ollama error", "ENOTFOUND", "ETIMEDOUT")


def kill_process_tree(pid: int) -> None:
    """Kill a process AND every process it started. On Windows, killing npx alone leaves its node child
    running (it kept generating for an hour on 18 Oct 2026), so taskkill /T kills the whole tree."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)  # the process was started in its own session (= group)
        except ProcessLookupError:
            pass


def run_with_tree_kill(command: list[str], cwd: str, timeout: float) -> subprocess.CompletedProcess:
    """Like subprocess.run(capture_output=True, text=True), but a timeout kills the whole process tree
    and then raises subprocess.TimeoutExpired."""
    windows = os.name == "nt"
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", start_new_session=not windows,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows else 0)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_process_tree(process.pid)
        try:
            process.communicate(timeout=30)  # the pipes close once the whole tree is gone
        except subprocess.TimeoutExpired:
            pass
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def resolve(path_text: str) -> Path:
    """Absolute paths stay as they are; relative paths are relative to the project root."""
    path = Path(path_text)
    return path if path.is_absolute() else project_path(path_text)


class BPMNGenGenerator:
    """Runs BPMNGen (via the harness) for one case and returns the harness meta data."""

    def __init__(self, config: dict, logger: RunLogger, runner: Callable = run_with_tree_kill,
                 model_digest: str | None = None):
        """runner can be replaced in tests (no Node.js, no Ollama).
        model_digest: the exact Ollama model file of the generator, checked against config.yaml when the run
        starts (run_experiment.ollama_settings, stored in run_info.json as generator_digest); written into every
        log record, like the agents' digest."""
        g = config["generator"]
        self.server_dir = resolve(g["bpmngen_server_dir"])
        self.harness = resolve(g["harness"])
        self.model = g["model"]
        self.base_url = g["ollama_base_url"]
        self.knowledge_label = g["knowledge_label"]
        self.timeout_seconds = g["timeout_seconds"]
        self.think_param = g.get("think_param")  # False: Ollama's think:false is added to BPMNGen's request
        self.npx = g.get("npx_command") or shutil.which("npx") or "npx"
        self.logger = logger
        self.runner = runner
        self.model_digest = model_digest

    def command(self, description_file: Path, knowledge_file: Path, out_dir: Path) -> list[str]:
        command = [self.npx, "ts-node", "--cwdMode", "--transpile-only", str(self.harness),
                   "--description", str(description_file), "--knowledge", str(knowledge_file),
                   "--out", str(out_dir), "--base-url", self.base_url, "--model", self.model,
                   "--label", self.knowledge_label]
        if self.think_param is not None:
            command += ["--think", "true" if self.think_param else "false"]
        return command

    def check_setup(self) -> None:
        """Stop before any call if BPMNGen or the harness cannot be found."""
        if not (self.server_dir / "tools" / "ai" / "opensource.ts").exists():
            raise FileNotFoundError(f"BPMNGen server folder not found at {self.server_dir} "
                                    f"(generator.bpmngen_server_dir in config.yaml)")
        if not (self.server_dir / "node_modules").exists():
            raise FileNotFoundError(f"BPMNGen dependencies missing: run 'npm install' in {self.server_dir}")
        if not self.harness.exists():
            raise FileNotFoundError(f"Harness not found at {self.harness}")

    def run(self, case_id: str, description_file: Path, knowledge_block: str, case_dir: Path) -> dict:
        """Generate the BPMN model of one case. Returns meta.json of the harness (with timed_out = True
        and no model if the harness timed out)."""
        case_dir.mkdir(parents=True, exist_ok=True)
        knowledge_file = case_dir / "knowledge_block.txt"
        knowledge_file.write_text(knowledge_block.strip() + "\n", encoding="utf-8")
        out_dir = case_dir / "bpmngen"
        command = self.command(description_file, knowledge_file, out_dir)

        try:
            result = self.runner(command, cwd=str(self.server_dir), timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            # The model kept generating too long: a result of the model (failed generation), not an
            # Ollama problem. The process tree is already killed (run_with_tree_kill).
            meta = {"timed_out": True, "seconds": self.timeout_seconds, "done_reason": None,
                    "think_param": self.think_param, "valid": False}
            self._log(case_id, meta, request=None, raw_output="", thinking="")
            return meta

        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            if any(marker in output for marker in UNAVAILABLE_MARKERS):
                raise LLMUnavailableError(f"Ollama not usable for BPMNGen ({self.base_url}): {output[-500:]}")
            raise RuntimeError(f"BPMNGen harness failed (exit code {result.returncode}): {output[-1000:]}")

        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        request = json.loads((out_dir / "ollama_request.json").read_text(encoding="utf-8"))
        raw_output = (out_dir / "raw_model_output.txt").read_text(encoding="utf-8")
        thinking_path = out_dir / "raw_thinking.txt"
        thinking = thinking_path.read_text(encoding="utf-8") if thinking_path.exists() else ""
        if (out_dir / "generated.bpmn").exists() and not meta.get("cut_off_by_harness"):
            shutil.copyfile(out_dir / "generated.bpmn", case_dir / "generated.bpmn")
        if meta.get("raw_has_think_block"):
            print(f"WARNING case {case_id}: the model produced thinking text despite think={self.think_param} "
                  f"({len(thinking)} chars in the thinking field, saved in {thinking_path}; "
                  f"{meta.get('think_tags_in_answer') or 0} think tag(s) in the answer)")
        self._log(case_id, meta, request, raw_output, thinking)
        return meta

    def _log(self, case_id: str, meta: dict, request: dict | None, raw_output: str, thinking: str) -> None:
        """One log record per case: the exact messages, the answer, the thinking text (if any) and the meta data."""
        self.logger.log_call(
            case_id=case_id,
            component=type(self).__name__,
            model=meta.get("ollama_model_reported") or self.model,
            temperature=meta.get("temperature"),
            prompt=json.dumps(request.get("messages") if request else None, ensure_ascii=False),
            raw_output=raw_output,
            parsed_output={**meta, "thinking_detected": bool(meta.get("raw_has_think_block")),
                           "raw_thinking": thinking},
            valid_json=bool(meta.get("valid")),
            retries=0,
            duration_seconds=meta.get("seconds"),
            finish_reason=meta.get("done_reason"),
            model_digest=self.model_digest,
        )


def context_limit_hit(meta: dict) -> bool:
    """True when the model was cut off: the answer did not end normally or the window was full."""
    return meta.get("done_reason") != "stop" or meta.get("fits_context") is False


def installed_ollama_digest(base_url: str, model: str, client: httpx.Client | None = None) -> str | None:
    """The digest (exact file) of an installed Ollama model, from GET /api/tags; None if not installed.

    Used for the GENERATOR's model, which BPMNGen calls itself (the agents' OllamaLLM checks its own).
    """
    client = client or httpx.Client(timeout=30)
    try:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
    except httpx.TransportError as e:
        raise LLMUnavailableError(f"Ollama not reachable at {base_url}: {e}") from e
    for entry in response.json().get("models", []):
        if model in (entry.get("name"), entry.get("model")):
            return entry.get("digest")
    return None
