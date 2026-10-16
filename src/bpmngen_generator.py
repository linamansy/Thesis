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

Outputs of one case (results/runs/<run_id>/<condition>/<case_id>/):
    knowledge_block.txt        the exact knowledge text given to the generator
    bpmngen/                   everything the harness wrote: ollama_request.json (exact prompt),
                               raw_model_output.txt, bpmngen_cleaned_output.txt, generated.bpmn,
                               validation.json (BPMNGen's own bpmnlint check), meta.json
    generated.bpmn             copy of bpmngen/generated.bpmn, the file that is evaluated
The call is also logged as one RunLogger record (component "BPMNGenGenerator").

Errors:
  - Ollama not reachable / HTTP error / harness timeout -> LLMUnavailableError: the run stops and
    the case stays unfinished (resumable), the same rule as for the API clients.
  - Any other harness failure -> RuntimeError: recorded by the runner as a failed generation.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from src.config import project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

# Text in the harness error output that means "Ollama could not be used" (not a model result).
UNAVAILABLE_MARKERS = ("ECONNREFUSED", "fetch failed", "Ollama error", "ENOTFOUND", "ETIMEDOUT")


def resolve(path_text: str) -> Path:
    """Absolute paths stay as they are; relative paths are relative to the project root."""
    path = Path(path_text)
    return path if path.is_absolute() else project_path(path_text)


class BPMNGenGenerator:
    """Runs BPMNGen (via the harness) for one case and returns the harness meta data."""

    def __init__(self, config: dict, logger: RunLogger, runner: Callable = subprocess.run):
        """runner can be replaced in tests (no Node.js, no Ollama)."""
        g = config["generator"]
        self.server_dir = resolve(g["bpmngen_server_dir"])
        self.harness = resolve(g["harness"])
        self.model = g["model"]
        self.base_url = g["ollama_base_url"]
        self.knowledge_label = g["knowledge_label"]
        self.timeout_seconds = g["timeout_seconds"]
        self.npx = g.get("npx_command") or shutil.which("npx") or "npx"
        self.logger = logger
        self.runner = runner

    def command(self, description_file: Path, knowledge_file: Path, out_dir: Path) -> list[str]:
        return [self.npx, "ts-node", "--cwdMode", "--transpile-only", str(self.harness),
                "--description", str(description_file), "--knowledge", str(knowledge_file),
                "--out", str(out_dir), "--base-url", self.base_url, "--model", self.model,
                "--label", self.knowledge_label]

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
        """Generate the BPMN model of one case. Returns meta.json of the harness."""
        case_dir.mkdir(parents=True, exist_ok=True)
        knowledge_file = case_dir / "knowledge_block.txt"
        knowledge_file.write_text(knowledge_block.strip() + "\n", encoding="utf-8")
        out_dir = case_dir / "bpmngen"

        try:
            result = self.runner(self.command(description_file, knowledge_file, out_dir),
                                 cwd=str(self.server_dir), capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as e:
            raise LLMUnavailableError(f"BPMNGen harness timed out after {self.timeout_seconds} s") from e

        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            if any(marker in output for marker in UNAVAILABLE_MARKERS):
                raise LLMUnavailableError(f"Ollama not usable for BPMNGen ({self.base_url}): {output[-500:]}")
            raise RuntimeError(f"BPMNGen harness failed (exit code {result.returncode}): {output[-1000:]}")

        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        request = json.loads((out_dir / "ollama_request.json").read_text(encoding="utf-8"))
        raw_output = (out_dir / "raw_model_output.txt").read_text(encoding="utf-8")
        shutil.copyfile(out_dir / "generated.bpmn", case_dir / "generated.bpmn")

        self.logger.log_call(
            case_id=case_id,
            component=type(self).__name__,
            model=meta.get("ollama_model_reported") or self.model,
            temperature=meta.get("temperature"),
            prompt=json.dumps(request.get("messages") if request else None, ensure_ascii=False),
            raw_output=raw_output,
            parsed_output=meta,
            valid_json=bool(meta.get("valid")),
            retries=0,
            duration_seconds=meta.get("seconds"),
            finish_reason=meta.get("done_reason"),
        )
        return meta


def context_limit_hit(meta: dict) -> bool:
    """True when the model was cut off: the answer did not end normally or the window was full."""
    return meta.get("done_reason") != "stop" or meta.get("fits_context") is False
