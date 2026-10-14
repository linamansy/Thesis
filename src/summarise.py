"""Summarise evaluation rows: per run and condition, then across repetitions.

Step 1, summarise_by_condition(): one row per group (e.g. per run and condition) with mean scores.
Behavioral similarity cannot be computed for a valid model with fewer than two
matched tasks (there is no pair to compare). Such cases are reported two ways,
so the choice is visible instead of hidden:
  behavioral_mean_excluding  average over computable cases only; behavioral_n_excluded says how many were left out
  behavioral_mean_as_zero    average over all cases, counting non-computable cases as 0
Failed or invalid models already have behavioral similarity 0 (they are scored 0
on every metric), so they are included in both averages.

Step 2, summarise_repetitions(): one row per condition (and provider and model, so mock and real
runs are never mixed) with, for every score, the mean and the standard deviation (SD) of the
per-repetition means. The SD is the sample SD (n - 1); with a single repetition it is empty.
"""

import pandas as pd

METRICS = ["precision", "recall", "f1"]
RUN_KEYS = ["provider", "model", "condition", "run_id", "repetition"]
CONDITION_KEYS = ["provider", "model", "condition"]

# Columns of the per-run summary -> name used in the across-repetitions summary.
REPETITION_COLUMNS = {
    "n_valid": "n_valid",
    "precision_mean": "precision",
    "recall_mean": "recall",
    "f1_mean": "f1",
    "behavioral_mean_excluding": "behavioral_excluding",
    "behavioral_n_excluded": "behavioral_n_excluded",
    "behavioral_mean_as_zero": "behavioral_as_zero",
}


def summarise_by_condition(table: pd.DataFrame, group_by: list[str] | None = None) -> pd.DataFrame:
    """One row per condition (or per any other grouping) with mean scores."""
    group_by = group_by or ["condition"]
    rows = []
    for keys, group in table.groupby(group_by, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        computable = group[group["behavioral_computable"]]
        behavioral = pd.to_numeric(group["behavioral_similarity"])
        row = dict(zip(group_by, keys))
        row |= {
            "n_cases": len(group),
            "n_valid": int(group["valid"].sum()),
            **{f"{m}_mean": round(group[m].mean(), 4) for m in METRICS},
            "behavioral_mean_excluding": (round(pd.to_numeric(computable["behavioral_similarity"]).mean(), 4)
                                          if len(computable) else None),
            "behavioral_n_excluded": len(group) - len(computable),
            "behavioral_mean_as_zero": round(behavioral.fillna(0).mean(), 4),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def summarise_runs(table: pd.DataFrame, extra_keys: list[str] | None = None) -> pd.DataFrame:
    """Step 1: one row per run and condition."""
    return summarise_by_condition(table, group_by=(extra_keys or []) + RUN_KEYS)


def summarise_repetitions(run_summary: pd.DataFrame, extra_keys: list[str] | None = None) -> pd.DataFrame:
    """Step 2: per condition, the mean and SD over repetitions of each per-run score."""
    keys = (extra_keys or []) + CONDITION_KEYS
    rows = []
    for values, group in run_summary.groupby(keys, sort=True):
        values = values if isinstance(values, tuple) else (values,)
        row = dict(zip(keys, values))
        row["n_repetitions"] = len(group)
        row["repetitions"] = ",".join(str(r) for r in sorted(group["repetition"]))
        for column, name in REPETITION_COLUMNS.items():
            numbers = pd.to_numeric(group[column])
            row[f"{name}_mean"] = round(numbers.mean(), 4)
            row[f"{name}_sd"] = round(numbers.std(ddof=1), 4) if numbers.count() > 1 else None
        rows.append(row)
    return pd.DataFrame(rows)
