"""RunLogger: writes one JSON record per LLM call to a JSON Lines file.

File: results/logs/<condition>_<run_id>.jsonl
Each line is one complete JSON object, so the file can be read line by line
and every LLM input and output of a run can be inspected later.

One log file belongs to exactly one run (part): if the file already exists, RunLogger
refuses to start, so records of two runs can never be mixed in one file. A run that is
resumed (see src/run_folder.py) writes each further part to a new file:
  <condition>_<run_id>.jsonl, <condition>_<run_id>_part2.jsonl, <condition>_<run_id>_part3.jsonl, ...
"""

import json
from datetime import datetime, timezone
from pathlib import Path


class RunLogger:
    """Collects the log records of one experiment run (one condition, one run ID)."""

    def __init__(self, log_dir: Path, condition: str, run_id: str | None = None, part: int = 1):
        self.condition = condition
        # Default run ID: the start time, e.g. "20261014T153000Z".
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.part = part
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if part == 1 else f"_part{part}"
        self.log_path = self.log_dir / f"{condition}_{self.run_id}{suffix}.jsonl"
        if self.log_path.exists():
            raise FileExistsError(f"Log file {self.log_path} already exists: condition {condition} was already "
                                  f"run with run id {self.run_id!r}. Choose a new run id.")

    def log_call(self, *, case_id: str, component: str, model: str, temperature: float,
                 prompt: str, raw_output: str, parsed_output: dict | None,
                 valid_json: bool, retries: int, duration_seconds: float,
                 finish_reason: str | None = None) -> dict:
        """Append one record to the log file and return it.

        finish_reason: why the model stopped, as reported by the API (e.g. "STOP", or "MAX_TOKENS" when
        the answer was cut off at max_tokens); None for providers that do not report it (MockLLM).
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "condition": self.condition,
            "case_id": case_id,
            "component": component,
            "model": model,
            "temperature": temperature,
            "prompt": prompt,
            "raw_output": raw_output,
            "parsed_output": parsed_output,
            "valid_json": valid_json,
            "retries": retries,
            "duration_seconds": duration_seconds,
            "finish_reason": finish_reason,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
