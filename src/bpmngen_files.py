"""BPMNGenFiles: SHA-256 hashes of the BPMNGen files the harness loads, so a run can prove which BPMNGen code
produced it (audit 19 Oct 2026, finding 1).

BPMNGen is private Ulm code. Its files are only READ to hash them: never changed, copied or quoted.

Which files are hashed (all paths relative to the BPMNGen server folder, generator.bpmngen_server_dir):
  1. the files named in config.yaml generator.bpmngen_hashed_files (opensource.ts, ai.ts, xml-validator.ts,
     environment.ts); each one must exist
  2. every other BPMNGen file the harness really loads. The harness is started once with --list-files: it loads
     BPMNGen exactly as for a generation, builds a prompt (no Ollama call) and prints the BPMNGen files Node
     loaded (its module cache) or read (fs.readFileSync), without node_modules. So no file has to be guessed.
     This also finds BPMNGen's prompt files (read while the prompt is built).
  Not hashed: generator.bpmngen_hash_exclude (BPMNGen's .env with its API keys).
The result, {relative path: sha256}, is stored in run_info.json as "bpmngen_file_hashes" when a run starts.

Two checks use it:
  - inside one run: RunFolder refuses a later part whose hashes differ (like every other run setting)
  - between the runs of one study (config.yaml statistics.runs, e.g. ollama_rep1..3): check_same_study()
    stops a run whose hashes differ from those stored by another run of the study
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from src.bpmngen_generator import resolve, run_with_tree_kill

HASHES_KEY = "bpmngen_file_hashes"   # key in run_info.json


def sha256_of(path: Path) -> str:
    """SHA-256 of a file's bytes (the file is only read)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BPMNGenFiles:
    """Finds and hashes the BPMNGen files the harness loads."""

    def __init__(self, config: dict, runner: Callable = run_with_tree_kill):
        """runner can be replaced in tests (no Node.js, no BPMNGen)."""
        g = config["generator"]
        self.server_dir = resolve(g["bpmngen_server_dir"])
        self.harness = resolve(g["harness"])
        self.named_files = list(g["bpmngen_hashed_files"])
        self.excluded = set(g.get("bpmngen_hash_exclude") or [])
        self.timeout_seconds = g["timeout_seconds"]
        self.npx = g.get("npx_command") or shutil.which("npx") or "npx"
        self.runner = runner

    def command(self) -> list[str]:
        return [self.npx, "ts-node", "--cwdMode", "--transpile-only", str(self.harness), "--list-files"]

    def loaded_files(self) -> list[str]:
        """The BPMNGen files (relative paths) the harness loads, as reported by the harness itself."""
        try:
            result = self.runner(self.command(), cwd=str(self.server_dir), timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"listing the BPMNGen files timed out after {self.timeout_seconds} s") from e
        if result.returncode != 0:
            output = (result.stderr or "") + (result.stdout or "")
            raise RuntimeError(f"listing the BPMNGen files failed (exit code {result.returncode}): {output[-1000:]}")
        # the harness prints one JSON line {"bpmngen_files": [...]}; BPMNGen itself may print other lines
        for line in reversed((result.stdout or "").splitlines()):
            if line.startswith('{"bpmngen_files"'):
                return json.loads(line)["bpmngen_files"]
        raise RuntimeError(f"the harness did not report its BPMNGen files: {(result.stdout or '')[-500:]}")

    def hashes(self) -> dict[str, str]:
        """{relative path: sha256} for the named files and every file the harness loads (except the excluded
        ones), sorted by path. Raises FileNotFoundError if a file is missing."""
        paths = (set(self.named_files) | set(self.loaded_files())) - self.excluded
        hashes = {}
        for relative in sorted(paths):
            path = self.server_dir / relative
            if not path.is_file():
                raise FileNotFoundError(f"BPMNGen file {relative} not found in {self.server_dir} "
                                        f"(generator.bpmngen_hashed_files / harness --list-files)")
            hashes[relative] = sha256_of(path)
        return hashes


def check_same_study(run_id: str, hashes: dict[str, str], runs: list[dict], study_runs: list[str]) -> None:
    """Stop (ValueError) if another run of the same study recorded different BPMNGen file hashes.

    runs: run_info of every run (RunFolder.find_runs). study_runs: the run ids of the study (statistics.runs).
    Only applies when run_id belongs to the study. Runs without stored hashes (made before 19 Oct 2026) and the
    run itself (its own parts are checked by RunFolder) are skipped.
    """
    if run_id not in study_runs:
        return
    for run in runs:
        saved = run.get(HASHES_KEY)
        if run["run_id"] == run_id or run["run_id"] not in study_runs or saved is None:
            continue
        if saved != hashes:
            changed = sorted(p for p in set(saved) | set(hashes) if saved.get(p) != hashes.get(p))
            raise ValueError(f"BPMNGen differs from run {run['run_id']!r} of the same study "
                             f"({', '.join(changed)}). All runs of a study must use identical BPMNGen files; "
                             f"restore that BPMNGen version before starting {run_id!r}.")
