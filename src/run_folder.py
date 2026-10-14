"""RunFolder: one folder per experiment run, which is never overwritten.

Layout:
  results/runs/<run_id>/run_info.json                   repetition, provider, model, temperature, conditions run
  results/runs/<run_id>/<condition>/<case_id>/...       generated.json, generated.bpmn, validation.json
  results/runs/<run_id>/C3/mediation/...                C3 mediation outputs
The run id defaults to "<provider>_rep<repetition>", e.g. "anthropic_rep1", so mock runs and real
runs never share a folder. The conditions C1, C2 and C3 of one repetition go into the same run folder.

Protection against overwriting:
  - a condition folder that already exists is never written into again
  - run_info.json must agree with the current repetition, provider, model and temperature;
    a run folder can never mix runs made with different settings
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import project_path
from src.llm.mock_llm import MockLLM


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_run_id(config: dict, repetition: int) -> str:
    return f"{config['llm']['provider']}_rep{repetition}"


class RunFolder:
    """The folder of one run (one repetition)."""

    def __init__(self, config: dict, run_id: str, repetition: int):
        n_repetitions = config["experiment"]["repetitions"]
        if not 1 <= repetition <= n_repetitions:
            raise ValueError(f"repetition must be between 1 and {n_repetitions} (experiment.repetitions)")
        paths = config["paths"]
        self.run_id = run_id
        self.repetition = repetition
        self.path = project_path(paths["runs"]) / run_id
        self.info_path = self.path / paths["run_info_file"]
        llm = config["llm"]
        # A mock run does not use the configured model, so it is recorded as the mock's own name.
        model = MockLLM.MODEL_NAME if llm["provider"] == "mock" else llm["model"]
        self.settings = {"run_id": run_id, "repetition": repetition, "provider": llm["provider"],
                         "model": model, "temperature": llm["temperature"]}

    def condition_dir(self, condition: str) -> Path:
        return self.path / condition

    def read_info(self) -> dict | None:
        if not self.info_path.exists():
            return None
        return json.loads(self.info_path.read_text(encoding="utf-8"))

    def check_can_start(self, condition: str) -> None:
        """Raise an error if starting this condition would overwrite or mix runs."""
        if self.condition_dir(condition).exists():
            raise FileExistsError(f"{self.condition_dir(condition)} already exists: condition {condition} was already "
                                  f"run in run {self.run_id!r}. Nothing is overwritten; choose a new --run-id.")
        info = self.read_info()
        if info is not None:
            different = {k: (info.get(k), v) for k, v in self.settings.items() if info.get(k) != v}
            if different:
                raise ValueError(f"Run folder {self.path} was made with other settings "
                                 f"(saved vs now): {different}. Choose a new --run-id.")

    def start(self, condition: str, log_path: Path) -> None:
        """Create the condition folder and record the start in run_info.json."""
        self.check_can_start(condition)
        info = self.read_info() or {**self.settings, "created_at": now(), "conditions": {}}
        info["conditions"][condition] = {"started_at": now(), "finished_at": None, "log_file": str(log_path)}
        self.condition_dir(condition).mkdir(parents=True)
        self._write(info)

    def finish(self, condition: str, records: list[dict]) -> None:
        """Record the end of a condition: time, number of cases and valid models."""
        info = self.read_info()
        info["conditions"][condition].update({
            "finished_at": now(),
            "n_cases": len(records),
            "n_generated": sum(r["generation_succeeded"] for r in records),
            "n_valid": sum(r["valid"] for r in records),
        })
        self._write(info)

    def _write(self, info: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        self.info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")

    @staticmethod
    def find_runs(config: dict) -> list[dict]:
        """run_info.json of every run in results/runs/, with its folder added as "path". Sorted by run id."""
        runs_dir = project_path(config["paths"]["runs"])
        runs = []
        for info_path in sorted(runs_dir.glob(f"*/{config['paths']['run_info_file']}")):
            info = json.loads(info_path.read_text(encoding="utf-8"))
            runs.append({**info, "path": info_path.parent})
        return runs
