"""Study 2 manifest: one row per Study 2 file under results/, with its SHA-256 (results/MANIFEST_study2.csv).

Study 1's results/MANIFEST.csv (fix E3) is never changed (decided by Lina 24 Oct 2026). This file lists only the
files matching config.yaml study2_gdpr.manifest_patterns (paths relative to results/, e.g. the GDPR silver log,
the smoke run smoke_gdpr_dev and its evaluation). Same columns as Study 1's manifest (src/results_manifest.py, whose
ResultsManifest describes each file), READ ONLY for every listed file.

Unlike Study 1's manifest, this one is rewritten on every call, because Study 2 is still adding files; each call
lists what exists at that moment (the commit history keeps the earlier versions).

Run from the project root:  .venv\\Scripts\\python.exe -m src.results_manifest_study2
"""

from pathlib import Path

import pandas as pd

from src.config import load_config, project_path
from src.results_manifest import ResultsManifest, sha256


def study2_files(results_dir: Path, patterns: list[str], skip: set[str]) -> list[Path]:
    """Files under results/ that match one of the patterns, sorted, without the manifests themselves."""
    files = {p for pattern in patterns for p in results_dir.glob(pattern) if p.is_file()}
    return sorted(p for p in files if p.name not in skip)


def build_manifest(config: dict) -> pd.DataFrame:
    output = project_path(config["paths"]["results_manifest_study2"])
    results_dir = output.parent
    describer = ResultsManifest(config, results_dir)
    skip = {output.name, Path(config["paths"]["results_manifest"]).name}
    rows = [{**describer.describe(path.relative_to(results_dir)), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in study2_files(results_dir, config["study2_gdpr"]["manifest_patterns"], skip)]
    table = pd.DataFrame(rows, columns=["path", "status", "run_id", "repetition", "condition", "case_id", "role",
                                        "bytes", "sha256"])
    table["repetition"] = table["repetition"].astype("Int64")
    return table


def main() -> None:
    config = load_config()
    output = project_path(config["paths"]["results_manifest_study2"])
    table = build_manifest(config)
    table.to_csv(output, index=False)
    print(table.groupby("status").size().to_string() if len(table) else "no Study 2 files")
    print(f"{len(table)} files listed. Saved {output}")


if __name__ == "__main__":
    main()
