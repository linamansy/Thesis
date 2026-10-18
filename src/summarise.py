"""Summarise evaluation rows: per run and condition, then across repetitions.

Step 1, summarise_by_condition(): one row per group (e.g. per run and condition) with mean scores.
Behavioral similarity cannot be computed for a valid model with fewer than two
matched tasks (there is no pair to compare). Such cases are reported two ways,
so the choice is visible instead of hidden:
  behavioral_mean_excluding  average over computable cases only; behavioral_n_excluded says how many were left out
  behavioral_mean_as_zero    average over all cases, counting non-computable cases as 0
Failed or invalid models already have behavioral similarity 0 (they are scored 0
on every metric), so they are included in both averages. Exception: invalid models whose only problem was
the diagram (bpmndi) section are scored without it (src/di_rescue.py); n_di_stripped counts them, and
n_bpmnlint_valid counts the models BPMNGen's own check accepted (n_valid stays the strict count).

Silver legal reference (AI-made, provisional): mean precision_adjusted (correct legal steps are not errors),
requirement coverage (mean over the cases that have required steps), justified extra tasks and unjustified
knowledge additions.
Also per group: mean number of extra (unsupported) tasks and of knowledge-traceable extra tasks,
and how many cases hit the context limit or were auto-repaired by BPMNGen (diagnostics, reported
per condition so that a difference between conditions is visible).

Step 2, summarise_repetitions(): one row per condition (and provider and model, so mock and real
runs are never mixed) with, for every score, the mean and the standard deviation (SD) of the
per-repetition means. The SD is the sample SD (n - 1); with a single repetition it is empty.
"""

import pandas as pd

# Failure types, in the order they are checked (each case gets the first that applies; see
# failure_type() in src/evaluate.py). "none" (a valid model) is not a failure and is not counted here.
FAILURE_TYPES = ["timed_out", "context_limit_hit", "thinking_detected", "missing_namespace_rescued",
                 "invalid_xml_other"]

METRICS = ["precision", "recall", "f1"]
RUN_KEYS = ["provider", "model", "condition", "run_id", "repetition"]
CONDITION_KEYS = ["provider", "model", "condition"]

# Columns of the per-run summary -> name used in the across-repetitions summary.
REPETITION_COLUMNS = {
    "n_valid": "n_valid",
    "n_bpmnlint_valid": "n_bpmnlint_valid",
    "n_di_stripped": "n_di_stripped",
    "precision_mean": "precision",
    "recall_mean": "recall",
    "f1_mean": "f1",
    "behavioral_mean_excluding": "behavioral_excluding",
    "behavioral_n_excluded": "behavioral_n_excluded",
    "behavioral_mean_as_zero": "behavioral_as_zero",
    "extra_tasks_mean": "extra_tasks",
    "extra_knowledge_traceable_mean": "extra_knowledge_traceable",
    "precision_adjusted_mean": "precision_adjusted",
    "requirement_coverage_mean": "requirement_coverage",
    "extra_justified_mean": "extra_justified",
    "unjustified_knowledge_additions_mean": "unjustified_knowledge_additions",
    "n_context_limit_hit": "n_context_limit_hit",
    "n_timed_out": "n_timed_out",
    "n_thinking_detected": "n_thinking_detected",
    **{f"n_fail_{t}": f"n_fail_{t}" for t in FAILURE_TYPES},
    "n_auto_repaired": "n_auto_repaired",
}


def mean_or_none(group: pd.DataFrame, column: str):
    """Mean of a column, or None if the column is missing (older evaluation tables) or empty."""
    if column not in group:
        return None
    numbers = pd.to_numeric(group[column], errors="coerce")
    return round(numbers.mean(), 4) if numbers.count() else None


def count_true(group: pd.DataFrame, column: str) -> int:
    return int(group[column].fillna(False).astype(bool).sum()) if column in group else 0


def count_failure(group: pd.DataFrame, kind: str) -> int:
    """Cases of one failure type (column failure_type; 0 for older evaluation tables without it)."""
    return int((group["failure_type"] == kind).sum()) if "failure_type" in group else 0


def count_auto_repaired(group: pd.DataFrame) -> int:
    """Cases where BPMNGen's cleanup added flows or a task that the model did not produce."""
    if "auto_flows_added" not in group:
        return 0
    flows = pd.to_numeric(group["auto_flows_added"], errors="coerce").fillna(0)
    links = pd.to_numeric(group["auto_links_added"], errors="coerce").fillna(0)
    first = group["first_task_inserted"].fillna(False).astype(bool)
    return int(((flows > 0) | (links > 0) | first).sum())


def summarise_by_condition(table: pd.DataFrame, group_by: list[str] | None = None) -> pd.DataFrame:
    """One row per condition (or per any other grouping) with mean scores."""
    group_by = group_by or ["condition"]
    if table.empty:
        return pd.DataFrame()
    rows = []
    for keys, group in table.groupby(group_by, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        computable = group[group["behavioral_computable"]]
        behavioral = pd.to_numeric(group["behavioral_similarity"])
        row = dict(zip(group_by, keys))
        row |= {
            "n_cases": len(group),
            "n_valid": int(group["valid"].sum()),                  # strict validator (main metric)
            "n_bpmnlint_valid": count_true(group, "bpmnlint_valid"),  # BPMNGen's own verdict
            "n_di_stripped": count_true(group, "di_stripped"),      # scored without the diagram section
            **{f"{m}_mean": round(group[m].mean(), 4) for m in METRICS},
            "behavioral_mean_excluding": (round(pd.to_numeric(computable["behavioral_similarity"]).mean(), 4)
                                          if len(computable) else None),
            "behavioral_n_excluded": len(group) - len(computable),
            "behavioral_mean_as_zero": round(behavioral.fillna(0).mean(), 4),
            "extra_tasks_mean": mean_or_none(group, "n_extra_tasks"),
            "extra_knowledge_traceable_mean": mean_or_none(group, "n_extra_knowledge_traceable"),
            "precision_adjusted_mean": mean_or_none(group, "precision_adjusted"),
            "requirement_coverage_mean": mean_or_none(group, "requirement_coverage"),
            "extra_justified_mean": mean_or_none(group, "n_extra_justified"),
            "unjustified_knowledge_additions_mean": mean_or_none(group, "n_unjustified_knowledge_additions"),
            "n_context_limit_hit": count_true(group, "context_limit_hit"),  # cut off: failed generation
            "n_timed_out": count_true(group, "timed_out"),                  # harness timeout: failed generation
            "n_thinking_detected": count_true(group, "thinking_detected"),  # thinking despite think:false
            # failure types per condition: each case counts once, under its first failure type (evaluate.py)
            **{f"n_fail_{t}": count_failure(group, t) for t in FAILURE_TYPES},
            "n_auto_repaired": count_auto_repaired(group),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def summarise_runs(table: pd.DataFrame, extra_keys: list[str] | None = None) -> pd.DataFrame:
    """Step 1: one row per run and condition."""
    return summarise_by_condition(table, group_by=(extra_keys or []) + RUN_KEYS)


def summarise_repetitions(run_summary: pd.DataFrame, extra_keys: list[str] | None = None) -> pd.DataFrame:
    """Step 2: per condition, the mean and SD over repetitions of each per-run score."""
    keys = (extra_keys or []) + CONDITION_KEYS
    if run_summary.empty:
        return pd.DataFrame()
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
