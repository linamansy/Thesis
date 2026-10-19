"""ResultsManifest: one row per file under results/, with its run, condition, case, repetition and SHA-256
(fix E3, 19 Oct 2026). READ ONLY: no existing file is opened for writing; only the manifest itself is created.

Columns: path (relative to results/), status (study = a run in statistics.runs, smoke, discarded or other),
run_id, repetition, condition, case_id, role (what the file is, see results/README.md), bytes, sha256.
The manifest and results/README.md are not listed. The command refuses to overwrite an existing manifest, so a
later study writes a new one (e.g. MANIFEST_<date>.csv, by changing paths.results_manifest).

Run from the project root:  .venv\\Scripts\\python.exe -m src.results_manifest
"""

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from src.config import load_config, project_path

LOG_NAME = re.compile(r"^(C[123])_(.+?)(?:_part(\d+))?\.jsonl$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResultsManifest:
    def __init__(self, config: dict, results_dir: Path):
        self.config = config
        self.root = Path(results_dir)
        self.study = set(config["statistics"]["runs"])
        self.smoke_prefix = config["evaluation"]["smoke_run_prefix"]
        self.skip = {Path(config["paths"]["results_manifest"]).name, Path(config["paths"]["results_readme"]).name}
        self.repetitions = {}
        for info in (self.root / "runs").glob("*/run_info.json"):
            self.repetitions[info.parent.name] = json.loads(info.read_text(encoding="utf-8")).get("repetition")

    def status(self, run_id: str | None, parts: tuple[str, ...]) -> str:
        if parts[0] == "_discarded":
            return "discarded"
        if run_id in self.study:
            return "study"
        if run_id and run_id.startswith(self.smoke_prefix):
            return "smoke"
        return "other"

    def describe(self, relative: Path) -> dict:
        parts = relative.parts
        run_id = condition = case_id = None
        role = relative.name
        if parts[0] == "runs" and len(parts) >= 3:
            run_id = parts[1]
            if parts[2] == "run_info.json":
                role = "run_info"
            else:
                condition = parts[2]
                if len(parts) >= 5 and parts[3] == self.config["paths"]["mediation_dir"]:
                    role = "mediation_summary" if parts[4] == self.config["paths"]["mediation_summary_file"] \
                        else "mediation_case"
                    case_id = None if role == "mediation_summary" else Path(parts[4]).stem
                elif len(parts) >= 5:
                    case_id = parts[3]
                    role = "/".join(parts[4:])          # e.g. generated.bpmn, bpmngen/meta.json
        elif parts[0] == "logs":
            match = LOG_NAME.match(relative.name)
            if match:
                condition, run_id = match.group(1), match.group(2)
                role = "llm_log" if not match.group(3) else f"llm_log_part{match.group(3)}"
            elif relative.name.startswith("SILVER_"):
                role = "silver_log"
            else:
                role = "console_log"
        elif parts[0] == "_discarded":
            run_id = parts[1] if len(parts) > 1 else None
            role = "discarded/" + "/".join(parts[2:])
        else:
            role = "/".join(parts)
        return {"path": relative.as_posix(), "status": self.status(run_id, parts), "run_id": run_id,
                "repetition": self.repetitions.get(run_id) if parts[0] != "_discarded" else None,
                "condition": condition, "case_id": case_id, "role": role}

    def rows(self) -> list[dict]:
        rows = []
        for path in sorted(p for p in self.root.rglob("*") if p.is_file()):
            relative = path.relative_to(self.root)
            if len(relative.parts) == 1 and relative.name in self.skip:
                continue
            rows.append({**self.describe(relative), "bytes": path.stat().st_size, "sha256": sha256(path)})
        return rows


def main() -> None:
    config = load_config()
    output = project_path(config["paths"]["results_manifest"])
    if output.exists():
        raise SystemExit(f"Not started: {output} already exists; outputs are never overwritten.")
    manifest = ResultsManifest(config, output.parent)
    table = pd.DataFrame(manifest.rows())
    table["repetition"] = table["repetition"].astype("Int64")   # whole numbers, empty where there is no run
    table.to_csv(output, index=False)
    print(table.groupby("status").size().to_string())
    print(f"{len(table)} files listed. Saved {output}")


if __name__ == "__main__":
    main()
