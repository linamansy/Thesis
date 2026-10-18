"""RQ3 (applicability): how often does C3's mediation label agree with the SILVER reference label?

For every run that has C3 mediation files (results/runs/<run_id>/C3/mediation/<case_id>.json), each
(case, passage) label of C3 is compared with the label of data/silver/silver_reference.json:
    C3 "Applicable"      <-> silver "applicable"
    C3 "Not applicable"  <-> silver "not_applicable"
    C3 "Indeterminate"   <-> silver "indeterminate"
    C3 "Irrelevant"      <-> silver "irrelevant"
    C3 "Mediation failed" / silver "annotation_failed" are counted, but left out of accuracy and kappa.
Reported per run: number of pairs, accuracy, Cohen's kappa (agreement corrected for chance), and the
confusion matrix (rows = silver, columns = C3).
Smoke runs (run id starting with evaluation.smoke_run_prefix, "smoke") are left out, as the analysis plan
(docs/ANALYSIS_PLAN.md, section 5) requires.

IMPORTANT: the silver labels are AI-made (openai/gpt-oss-120b) and were not checked by a human, so this
measures AGREEMENT WITH A STRONGER MODEL, not correctness. Report it that way.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.rq3_agreement
Output: results/rq3_agreement.csv and results/rq3_confusion.json
"""

import json
from collections import Counter

import pandas as pd

from src.config import load_config, project_path
from src.run_folder import RunFolder

C3_TO_SILVER = {"Applicable": "applicable", "Not applicable": "not_applicable",
                "Indeterminate": "indeterminate", "Irrelevant": "irrelevant"}
LABELS = ["applicable", "not_applicable", "indeterminate", "irrelevant"]


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for (silver, c3) label pairs; None if undefined (no pairs, or chance agreement is 1)."""
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(a == b for a, b in pairs) / n
    silver, c3 = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(silver[label] * c3[label] for label in set(silver) | set(c3)) / n ** 2
    return None if expected == 1 else (observed - expected) / (1 - expected)


def label_pairs(mediation_dir, silver_cases: dict) -> tuple[list[tuple[str, str]], int]:
    """(silver label, C3 label) for every passage, and how many pairs were skipped (failed on either side)."""
    pairs, skipped = [], 0
    for path in sorted(mediation_dir.glob("*.json")):
        if path.name == "run_summary.json" or path.stem not in silver_cases:
            continue
        silver = {p["passage_id"]: p["label"] for p in silver_cases[path.stem]["passages"]}
        for record in json.loads(path.read_text(encoding="utf-8"))["passages"]:
            c3 = C3_TO_SILVER.get(record["label"])
            s = silver.get(record["passage_id"])
            if c3 is None or s not in LABELS:
                skipped += 1
                continue
            pairs.append((s, c3))
    return pairs, skipped


def agreement(pairs: list[tuple[str, str]]) -> dict:
    n = len(pairs)
    kappa = cohen_kappa(pairs)
    return {"n_pairs": n,
            "accuracy": round(sum(a == b for a, b in pairs) / n, 4) if n else None,
            "cohen_kappa": None if kappa is None else round(kappa, 4),
            "confusion": {s: {c: sum(1 for a, b in pairs if a == s and b == c) for c in LABELS} for s in LABELS}}


def analysed_runs(runs: list[dict], smoke_prefix: str) -> list[dict]:
    """The runs RQ3 reports on: every run except smoke (test) runs."""
    return [run for run in runs if not run["run_id"].startswith(smoke_prefix)]


def main() -> None:
    config = load_config()
    silver_path = project_path(config["paths"]["silver_reference"])
    if not silver_path.exists():
        raise SystemExit("No silver reference yet: run python -m src.build_silver_reference first")
    silver_cases = json.loads(silver_path.read_text(encoding="utf-8"))["cases"]
    rows, confusion = [], {}
    for run in analysed_runs(RunFolder.find_runs(config), config["evaluation"]["smoke_run_prefix"]):
        mediation_dir = run["path"] / "C3" / config["paths"]["mediation_dir"]
        if not mediation_dir.exists():
            continue
        pairs, skipped = label_pairs(mediation_dir, silver_cases)
        result = agreement(pairs)
        confusion[run["run_id"]] = result.pop("confusion")
        rows.append({"run_id": run["run_id"], "repetition": run.get("repetition"), **result, "n_skipped": skipped})
    table = pd.DataFrame(rows)
    table.to_csv(project_path("results/rq3_agreement.csv"), index=False)
    project_path("results/rq3_confusion.json").write_text(json.dumps(confusion, indent=2), encoding="utf-8")
    print(table.to_string(index=False) if not table.empty else "No C3 mediation files found.")
    print("Agreement with the SILVER (AI-made, not human-checked) reference; rows of the confusion matrix = silver.")


if __name__ == "__main__":
    main()
