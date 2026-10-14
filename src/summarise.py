"""Summarise evaluation rows per condition.

Behavioral similarity cannot be computed for a valid model with fewer than two
matched tasks (there is no pair to compare). Such cases are reported two ways,
so the choice is visible instead of hidden:
  behavioral_mean_excluding  average over computable cases only; behavioral_n_excluded says how many were left out
  behavioral_mean_as_zero    average over all cases, counting non-computable cases as 0

Failed or invalid models already have behavioral similarity 0 (they are scored 0
on every metric), so they are included in both averages.
"""

import pandas as pd

METRICS = ["precision", "recall", "f1"]


def summarise_by_condition(table: pd.DataFrame, group_by: list[str] | None = None) -> pd.DataFrame:
    """One row per condition (or per threshold and condition) with mean scores."""
    group_by = group_by or ["condition"]
    rows = []
    for keys, group in table.groupby(group_by, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        computable = group[group["behavioral_computable"]]
        row = dict(zip(group_by, keys))
        row |= {
            "n_cases": len(group),
            "n_valid": int(group["valid"].sum()),
            **{f"{m}_mean": round(group[m].mean(), 4) for m in METRICS},
            "behavioral_mean_excluding": round(computable["behavioral_similarity"].mean(), 4) if len(computable) else None,
            "behavioral_n_excluded": len(group) - len(computable),
            "behavioral_mean_as_zero": round(group["behavioral_similarity"].fillna(0).mean(), 4),
        }
        rows.append(row)
    return pd.DataFrame(rows)
