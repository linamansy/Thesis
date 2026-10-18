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


@pytest.mark.parametrize("validation, di_stripped, expected", [
    ({"generation_succeeded": True, "valid": True}, False, "none"),
    ({"generation_succeeded": True, "valid": False}, True, "missing_namespace_rescued"),
    ({"generation_succeeded": True, "valid": False}, False, "invalid_xml_other"),          # e.g. b3pmn typo
    ({"generation_succeeded": False, "valid": False}, False, "invalid_xml_other"),         # e.g. harness error
    # stray </think>: a genuine model failure, even if the file were otherwise rescued or valid
    ({"generation_succeeded": True, "valid": False, "thinking_detected": True}, True, "thinking_detected"),
    ({"generation_succeeded": True, "valid": True, "thinking_detected": True}, False, "thinking_detected"),
    ({"generation_succeeded": False, "valid": False, "context_limit_hit": True}, False, "context_limit_hit"),
    ({"generation_succeeded": False, "valid": False, "timed_out": True, "thinking_detected": True}, False,
     "timed_out"),
])
def test_failure_type_is_the_first_that_applies(validation, di_stripped, expected):
    from src.evaluate import failure_type
    assert failure_type(validation, di_stripped) == expected


def test_failure_types_are_counted_per_condition():
    kinds = ["none", "invalid_xml_other", "missing_namespace_rescued", "thinking_detected", "thinking_detected"]
    table = pd.DataFrame([row("C3", kind == "none", 0.0, True) | {"failure_type": kind} for kind in kinds]
                         + [row("C1", True, 1.0, True) | {"failure_type": "none"}])
    summary = summarise_by_condition(table).set_index("condition")

    c3 = summary.loc["C3"]
    assert (c3["n_fail_invalid_xml_other"], c3["n_fail_missing_namespace_rescued"],
            c3["n_fail_thinking_detected"], c3["n_fail_context_limit_hit"], c3["n_fail_timed_out"]) == (1, 1, 2, 0, 0)
    assert summary.loc["C1", [c for c in summary.columns if c.startswith("n_fail_")]].sum() == 0


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
