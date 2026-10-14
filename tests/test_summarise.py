"""Tests for src/summarise.py."""

import pandas as pd
import pytest

from src.summarise import summarise_by_condition


def row(condition, valid, behavioral, computable, threshold=0.75):
    return {"condition": condition, "similarity_threshold": threshold, "valid": valid,
            "precision": 0.5, "recall": 0.5, "f1": 0.5,
            "behavioral_similarity": behavioral, "behavioral_computable": computable}


def test_non_computable_cases_reported_both_ways():
    table = pd.DataFrame([
        row("C1", True, 1.0, True),     # computable
        row("C1", True, None, False),   # valid, fewer than two matched tasks
        row("C1", False, 0.0, True),    # failed model: scored 0 by rule
    ])
    summary = summarise_by_condition(table).iloc[0]

    assert summary["n_cases"] == 3 and summary["n_valid"] == 2
    assert summary["behavioral_mean_excluding"] == pytest.approx(0.5)     # (1.0 + 0.0) / 2
    assert summary["behavioral_n_excluded"] == 1
    assert summary["behavioral_mean_as_zero"] == round(1 / 3, 4)          # (1.0 + 0 + 0.0) / 3, rounded


def test_all_non_computable_gives_empty_mean():
    summary = summarise_by_condition(pd.DataFrame([row("C1", True, None, False)])).iloc[0]
    assert summary["behavioral_n_excluded"] == 1
    assert pd.isna(summary["behavioral_mean_excluding"])
    assert summary["behavioral_mean_as_zero"] == 0


def test_group_by_threshold_and_condition():
    table = pd.DataFrame([row("C1", True, 1.0, True, 0.7), row("C1", True, 1.0, True, 0.8),
                          row("C2", True, 1.0, True, 0.7)])
    summary = summarise_by_condition(table, group_by=["similarity_threshold", "condition"])
    assert list(zip(summary["similarity_threshold"], summary["condition"])) == [(0.7, "C1"), (0.7, "C2"), (0.8, "C1")]
