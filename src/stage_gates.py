"""Stage gates: a stage may only start when the previous stage is finished and frozen (fix E2, 19 Oct 2026).

  evaluation gate  (python -m src.evaluate)
    - the silver reference (paths.silver_reference) has labels and expected requirements (required_steps) for
      EVERY case in config.yaml, a label for every frozen passage of the case, and no "annotation_failed"
    - it was built on the current frozen retrieval (its stored SHA-256 equals the file's)
    - it is committed in git, with no uncommitted changes
    - every run in statistics.runs exists and ALL its conditions are complete (every case finished)
  statistics gate  (python -m src.statistics)
    - paths.evaluation exists and holds exactly the run ids in statistics.runs, each with every condition x case
Each check returns a list of problems; an empty list means the gate is open. The commands stop with the list.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd

from src.config import load_config, project_path
from src.run_folder import RunFolder

SILVER_LABELS = {"applicable", "not_applicable", "indeterminate", "irrelevant"}


def git_committed(path: Path) -> str | None:
    """None if the file is tracked by git and has no uncommitted changes; else the reason."""
    path = Path(path)
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path.name], cwd=path.parent,
                                 capture_output=True, text=True)
        status = subprocess.run(["git", "status", "--porcelain", "--", path.name], cwd=path.parent,
                                capture_output=True, text=True)
    except FileNotFoundError:
        return "git is not available, so the commit cannot be checked"
    if tracked.returncode != 0:
        return f"{path.name} is not committed (not tracked by git)"
    if status.stdout.strip():
        return f"{path.name} has uncommitted changes"
    return None


def silver_problems(config: dict) -> list[str]:
    paths = config["paths"]
    silver_path = project_path(paths["silver_reference"])
    if not silver_path.exists():
        return [f"no silver reference at {silver_path} (run python -m src.build_silver_reference)"]
    data = json.loads(silver_path.read_text(encoding="utf-8"))
    frozen_path = project_path(paths["frozen_retrieval"])
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))["cases"]
    problems = []
    if data.get("frozen_retrieval_sha256") != hashlib.sha256(frozen_path.read_bytes()).hexdigest():
        problems.append("the silver reference was not built on the current frozen retrieval")
    for case_id in config["cases"]["ids"]:
        case = data.get("cases", {}).get(case_id)
        if case is None:
            problems.append(f"silver: case {case_id} has no labels")
            continue
        labels = {p["passage_id"]: p["label"] for p in case.get("passages", [])}
        missing = [p["passage_id"] for p in frozen[case_id]["passages"] if p["passage_id"] not in labels]
        bad = sorted({label for label in labels.values() if label not in SILVER_LABELS})
        if missing:
            problems.append(f"silver: case {case_id} has no label for passage(s) {missing}")
        if bad:
            problems.append(f"silver: case {case_id} has unusable label(s) {bad}")
        if not isinstance(case.get("required_steps"), list):
            problems.append(f"silver: case {case_id} has no expected requirements (required_steps)")
    reason = git_committed(silver_path)
    if reason:
        problems.append(f"silver: {reason}")
    return problems


def run_problems(config: dict) -> list[str]:
    runs = {r["run_id"]: r for r in RunFolder.find_runs(config)}
    problems = []
    for run_id in config["statistics"]["runs"]:
        if run_id not in runs:
            problems.append(f"run {run_id} does not exist")
            continue
        repetition = runs[run_id].get("repetition")
        folder = RunFolder(config, run_id, repetition)
        unfinished = [c for c in config["conditions"] if not folder.is_complete(c)]
        if unfinished:
            problems.append(f"run {run_id}: condition(s) {unfinished} not complete")
    return problems


def evaluation_gate(config: dict) -> list[str]:
    return silver_problems(config) + run_problems(config)


def statistics_gate(config: dict) -> list[str]:
    path = project_path(config["paths"]["evaluation"])
    if not path.exists():
        return [f"no evaluation at {path} (run python -m src.evaluate first)"]
    table = pd.read_csv(path, dtype={"case_id": str})
    study = config["statistics"]["runs"]
    found = sorted(table["run_id"].unique()) if "run_id" in table else []
    problems = []
    if sorted(study) != found:
        problems.append(f"evaluation.csv holds runs {found}, but statistics.runs is {sorted(study)}")
    expected = {(c, case) for c in config["conditions"] for case in config["cases"]["ids"]}
    for run_id in study:
        rows = table[table["run_id"] == run_id] if "run_id" in table else table.iloc[0:0]
        have = set(zip(rows["condition"], rows["case_id"])) if len(rows) else set()
        if have != expected:
            problems.append(f"evaluation.csv: run {run_id} has {len(have)} of {len(expected)} condition x case rows")
    return problems


def stop_if_closed(problems: list[str], stage: str) -> None:
    if problems:
        raise SystemExit(f"Not started: the {stage} gate is closed:\n  - " + "\n  - ".join(problems))


if __name__ == "__main__":
    config = load_config()
    for name, gate in (("evaluation", evaluation_gate), ("statistics", statistics_gate)):
        problems = gate(config)
        print(f"{name} gate: {'OPEN' if not problems else 'CLOSED'}")
        for problem in problems:
            print(f"  - {problem}")
