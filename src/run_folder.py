"""RunFolder: one folder per experiment run; finished cases are never overwritten.

Layout:
  results/runs/<run_id>/run_info.json                   repetition, provider, model, temperature, parts run
  results/runs/<run_id>/<condition>/<case_id>/...       generated.json, generated.bpmn, validation.json
  results/runs/<run_id>/C3/mediation/...                C3 mediation outputs
The run id defaults to "<provider>_rep<repetition>", e.g. "gemini_rep1", so mock and real runs never
share a folder. The conditions C1, C2 and C3 of one repetition go into the same run folder.

Finished case = its validation.json exists (it is written last, after the model files).

Resuming: a run can stop halfway (e.g. the daily free-tier limit). Running the same command again
(same condition and repetition) starts a new PART: finished cases are skipped and never rerun,
unfinished cases are run, and the LLM calls go to a new log file (<condition>_<run_id>_part2.jsonl, ...).
A condition whose cases are all finished is complete and is never started again.

Other protections:
  - run_info.json must agree with the current repetition, provider, model and temperature;
    a run folder can never mix runs made with different settings
  - with the default run ids, repetition n can only start when all conditions of repetition n-1
    are complete (all three conditions of a repetition are finished before the next one starts)
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
        self.config = config
        self.run_id = run_id
        self.repetition = repetition
        self.case_ids = config["cases"]["ids"]
        self.validation_file = paths["validation_file"]
        self.path = project_path(paths["runs"]) / run_id
        self.info_path = self.path / paths["run_info_file"]
        llm = config["llm"]
        # A mock run does not use the configured model, so it is recorded as the mock's own name.
        model = MockLLM.MODEL_NAME if llm["provider"] == "mock" else llm["model"]
        self.settings = {"run_id": run_id, "repetition": repetition, "provider": llm["provider"],
                         "model": model, "temperature": llm["temperature"]}

    # ---------- state of the run ----------

    def condition_dir(self, condition: str) -> Path:
        return self.path / condition

    def read_info(self) -> dict | None:
        if not self.info_path.exists():
            return None
        return json.loads(self.info_path.read_text(encoding="utf-8"))

    def finished_cases(self, condition: str) -> list[str]:
        """Cases of this condition that already have their validation.json (in config order)."""
        return [c for c in self.case_ids
                if (self.condition_dir(condition) / c / self.validation_file).exists()]

    def is_complete(self, condition: str) -> bool:
        return len(self.finished_cases(condition)) == len(self.case_ids)

    def next_part(self, condition: str) -> int:
        info = self.read_info() or {"conditions": {}}
        return len(info["conditions"].get(condition, {}).get("parts", [])) + 1

    # ---------- checks before starting ----------

    def check_can_start(self, condition: str) -> None:
        """Raise an error if this condition must not be (re)started now."""
        if self.is_complete(condition):
            raise FileExistsError(f"Condition {condition} of run {self.run_id!r} is already complete "
                                  f"({len(self.case_ids)} finished cases). Nothing is rerun or overwritten.")
        info = self.read_info()
        if info is not None:
            different = {k: (info.get(k), v) for k, v in self.settings.items() if info.get(k) != v}
            if different:
                raise ValueError(f"Run folder {self.path} was made with other settings "
                                 f"(saved vs now): {different}. Choose a new --run-id.")

    def check_previous_repetition_complete(self, conditions: list[str]) -> None:
        """With default run ids: repetition n needs every condition of repetition n-1 to be complete."""
        if self.repetition == 1:
            return
        previous = RunFolder(self.config, default_run_id(self.config, self.repetition - 1), self.repetition - 1)
        unfinished = [c for c in conditions if not previous.is_complete(c)]
        if unfinished:
            raise ValueError(f"Repetition {self.repetition - 1} is not complete yet (unfinished: "
                             f"{', '.join(unfinished)}). Finish all conditions of a repetition before "
                             f"starting the next one.")

    # ---------- recording parts ----------

    def start_part(self, condition: str, part: int, log_path: Path) -> list[str]:
        """Record the start of a (new) part. Returns the cases that will be run in this part."""
        self.check_can_start(condition)
        info = self.read_info() or {**self.settings, "created_at": now(), "conditions": {}}
        entry = info["conditions"].setdefault(condition, {"parts": [], "complete": False})
        to_run = [c for c in self.case_ids if c not in self.finished_cases(condition)]
        entry["parts"].append({"part": part, "started_at": now(), "finished_at": None,
                               "log_file": str(log_path), "cases_to_run": to_run, "interrupted": None})
        self.condition_dir(condition).mkdir(parents=True, exist_ok=True)
        self._write(info)
        return to_run

    def end_part(self, condition: str, records: list[dict], interrupted: str | None = None) -> None:
        """Record the end of the current part and, once all cases are finished, the totals."""
        info = self.read_info()
        entry = info["conditions"][condition]
        entry["parts"][-1].update({"finished_at": now(), "interrupted": interrupted})
        entry["complete"] = self.is_complete(condition)
        if entry["complete"]:
            entry.update({
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
