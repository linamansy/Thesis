"""Tests for src/statistics.py on SYNTHETIC data only (no real results are read), with known answers."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.config import load_config
from src.statistics import (Analysis, bootstrap_median_ci, case_means, friedman_test, holm, load_table,
                            rank_biserial, run_analysis, spearman, wilcoxon_test)

CONFIG = load_config()
CONDITIONS = ["C1", "C2", "C3"]
DECIMALS = CONFIG["statistics"]["round_decimals"]
CASES = [f"{i:02d}" for i in range(1, 14)]


def synthetic_table(c3_gain=0.1, behavioral_gain=0.05):
    """13 cases x 3 conditions x 3 repetitions. Case i has base F1 0.2 + 0.03 i (distinct differences
    are not needed: C3 = C1 + c3_gain exactly, C2 = C1 - 0.05). Complexity grows with the case number."""
    rows = []
    for i, case in enumerate(CASES):
        base = 0.2 + 0.03 * i
        f1 = {"C1": base, "C2": base - 0.05, "C3": base + c3_gain}
        behavioral = {"C1": 0.5, "C2": 0.5, "C3": 0.5 + behavioral_gain * (i + 1) / 13}
        for rep in (1, 2, 3):
            for condition in CONDITIONS:
                rows.append({"run_id": f"ollama_rep{rep}", "smoke_test": False, "similarity_threshold": 0.75,
                             "repetition": rep, "condition": condition, "case_id": case,
                             "f1": f1[condition], "behavioral_similarity": behavioral[condition],
                             "precision": f1[condition], "recall": f1[condition], "valid": True,
                             "di_stripped": False, "failure_type": "none", "precision_adjusted": np.nan,
                             "requirement_coverage": np.nan, "n_extra_tasks": 1,
                             "n_extra_knowledge_traceable": 0 if condition == "C1" else 1,
                             "n_unjustified_knowledge_additions": {"C1": 0, "C2": 2, "C3": 1}[condition],
                             "ref_flow_nodes": 10 + i, "ref_cfc": 2 * i})
    return pd.DataFrame(rows)


# ---------- building blocks: known answers ----------

def test_holm_known_answer():
    # sorted p: 0.005*4 = 0.02, 0.01*3 = 0.03, 0.03*2 = 0.06, 0.04*1 = 0.04 -> raised to 0.06 (monotone)
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert holm([0.5, np.nan]) == pytest.approx([1.0, 1.0])     # a missing p counts as 1


def test_rank_biserial_known_answers():
    assert rank_biserial(pd.Series([1, 2, 3])) == 1.0
    assert rank_biserial(pd.Series([-1, -2])) == -1.0
    assert rank_biserial(pd.Series([1, -2, 3])) == pytest.approx((1 + 3 - 2) / 6)
    assert rank_biserial(pd.Series([0, 1, -2, 3])) == pytest.approx(1 / 3)   # zeros dropped
    assert np.isnan(rank_biserial(pd.Series([0, 0])))


def test_wilcoxon_exact_known_answer():
    # 13 distinct positive differences: exact two-sided p = 2 / 2^13
    result = wilcoxon_test(pd.Series(np.arange(1, 14) / 100))
    assert result["p"] == pytest.approx(2 / 2 ** 13) and result["n"] == 13 and result["n_nonzero"] == 13


def test_floating_point_noise_is_not_a_difference():
    # 0.3 - 0.2 and 0.4 - 0.3 differ in floating point (1e-17), but they are the same difference
    means = pd.DataFrame({"C1": [0.2, 0.3], "C3": [0.3, 0.4]})
    from src.statistics import paired_differences
    assert paired_differences(means, "C3", "C1", DECIMALS).nunique() == 1
    same = pd.DataFrame({"C1": [0.1 + 0.2], "C3": [0.3]})                # 0.30000000000000004 vs 0.3
    assert paired_differences(same, "C3", "C1", DECIMALS).iloc[0] == 0


def test_wilcoxon_all_zero_is_not_testable():
    result = wilcoxon_test(pd.Series([0.0] * 13))
    assert np.isnan(result["p"]) and "all paired differences are zero" in result["note"]


def test_bootstrap_ci():
    assert bootstrap_median_ci(pd.Series([0.2] * 13), 1000, 42) == pytest.approx((0.2, 0.2, 0.2))
    d = pd.Series(np.linspace(-0.1, 0.3, 13))
    first, second = bootstrap_median_ci(d, 2000, 42), bootstrap_median_ci(d, 2000, 42)
    assert first == second                                       # fixed seed: reproducible
    median, low, high = first
    assert median == pytest.approx(0.1) and low <= median <= high and low >= -0.1 and high <= 0.3


def test_case_means_average_repetitions_and_skip_missing():
    table = pd.DataFrame({"case_id": ["01"] * 3, "condition": ["C1"] * 3, "behavioral_similarity": [0.2, 0.4, None]})
    assert case_means(table, "behavioral_similarity", CONDITIONS, DECIMALS).loc["01", "C1"] == pytest.approx(0.3)


def test_friedman_matches_scipy_and_handles_no_differences():
    means = pd.DataFrame({"C1": [1, 2, 3, 4], "C2": [2, 3, 1, 5], "C3": [3, 4, 5, 6]})
    expected = stats.friedmanchisquare(means["C1"], means["C2"], means["C3"])
    assert friedman_test(means, CONDITIONS)["p"] == pytest.approx(expected.pvalue)
    same = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in CONDITIONS})
    assert "not testable" in friedman_test(same, CONDITIONS)["note"]


def test_spearman_known_answers():
    x = pd.Series([1, 2, 3, 4, 5])
    assert spearman(x, x * 2)["rho"] == pytest.approx(1.0)
    assert spearman(x, -x)["rho"] == pytest.approx(-1.0)
    assert "not computable" in spearman(x, pd.Series([1] * 5))["note"]


# ---------- the whole analysis on synthetic data ----------

def settings():
    return CONFIG["statistics"]


def test_planned_tests_known_answer():
    result = Analysis(synthetic_table(), settings(), CONDITIONS).planned_tests(synthetic_table())
    f1 = result[result["metric"] == "f1"].set_index("comparison")

    # C3 = C1 + 0.1 in every case: median difference 0.1, CI [0.1, 0.1], rank-biserial 1
    assert f1.loc["C3 vs C1", "median_difference"] == pytest.approx(0.1)
    assert f1.loc["C3 vs C1", ["ci95_low", "ci95_high"]].tolist() == pytest.approx([0.1, 0.1])
    assert f1.loc["C3 vs C1", "rank_biserial"] == 1.0
    assert f1.loc["C3 vs C2", "median_difference"] == pytest.approx(0.15)
    assert f1.loc["C2 vs C1", "role"] == "descriptive" and np.isnan(f1.loc["C2 vs C1"].get("p", np.nan))

    # Holm over exactly the 4 planned tests (2 metrics x 2 comparisons); Friedman is not corrected
    planned = result[result["role"] == "planned"]
    assert len(planned) == 4 and planned["p_holm"].notna().all()
    assert result[result["role"] == "friedman"]["p_holm"].isna().all()
    # behavioral: C3 - C1 = 0.05 (i+1)/13, 13 distinct positive differences -> exact p = 2/2^13
    behavioral = result[(result["metric"] == "behavioral_similarity") & (result["comparison"] == "C3 vs C1")].iloc[0]
    assert behavioral["p"] == pytest.approx(2 / 2 ** 13) and behavioral["significant_holm"]


def test_overapplication_is_c3_minus_c2():
    row = Analysis(synthetic_table(), settings(), CONDITIONS).overapplication().iloc[0]
    assert row["metric"] == "n_unjustified_knowledge_additions" and row["comparison"] == "C3 vs C2"
    assert row["median_difference"] == -1 and row["rank_biserial"] == -1.0


def test_rq2_spearman_on_complexity():
    table = synthetic_table()
    spearman_table, cases = Analysis(table, settings(), CONDITIONS).rq2()
    assert len(cases) == 13 and {"ref_flow_nodes", "ref_cfc"} <= set(cases.columns)
    # behavioral C3-C1 grows with the case number, and so does complexity: rho = 1
    row = spearman_table[(spearman_table["complexity"] == "ref_flow_nodes")
                         & (spearman_table["effect"] == "behavioral_similarity: C3-C1")].iloc[0]
    assert row["rho"] == pytest.approx(1.0) and row["n"] == 13
    # F1 C3-C1 is the same (0.1) in every case: no variation, so no correlation
    f1_row = spearman_table[spearman_table["effect"] == "f1: C3-C1"].iloc[0]
    assert np.isnan(f1_row["rho"])


def test_secondary_analysis_uses_valid_or_rescued_only_and_failure_types():
    table = synthetic_table()
    # case 01, C3: one repetition invalid (scored 0), one rescued (di_stripped, scored normally)
    invalid = (table["case_id"] == "01") & (table["condition"] == "C3") & (table["repetition"] == 1)
    rescued = (table["case_id"] == "01") & (table["condition"] == "C3") & (table["repetition"] == 2)
    table.loc[invalid, ["valid", "f1", "failure_type"]] = [False, 0.0, "thinking_detected"]
    table.loc[rescued, ["valid", "di_stripped", "failure_type"]] = [False, True, "missing_namespace_rescued"]
    analysis = Analysis(table, settings(), CONDITIONS)

    main = case_means(table, "f1", CONDITIONS, DECIMALS).loc["01", "C3"]
    assert main == pytest.approx((0 + 0.3 + 0.3) / 3)            # main analysis: invalid counts as 0
    secondary = analysis.valid_or_rescued()
    f1 = secondary[(secondary["metric"] == "f1") & (secondary["comparison"] == "C3 vs C1")].iloc[0]
    assert f1["median_difference"] == pytest.approx(0.1)          # the invalid repetition is left out

    failures = analysis.failure_types().set_index("condition")
    assert failures.loc["C3", ["n_generations", "n_valid", "thinking_detected", "missing_namespace_rescued"]].tolist() \
        == [39, 37, 1, 1]
    assert failures.loc["C1", ["invalid_xml_other", "context_limit_hit", "timed_out"]].sum() == 0


def test_run_analysis_writes_all_tables(tmp_path):
    tables = run_analysis(synthetic_table(), CONFIG, tmp_path)
    assert set(tables) == {p.name for p in tmp_path.glob("*.csv")} and len(tables) == 7


def test_load_table_keeps_only_the_analysed_runs(tmp_path):
    table = synthetic_table()
    extra = table.iloc[:5].assign(run_id="smoke_nothink", smoke_test=True)
    sweep = table.iloc[:5].assign(similarity_threshold=0.8)
    csv = tmp_path / "evaluation.csv"
    pd.concat([table, extra, sweep]).to_csv(csv, index=False)
    config = dict(CONFIG, paths=dict(CONFIG["paths"], evaluation=str(csv)))
    assert len(load_table(config)) == 117
    pd.concat([table.iloc[:-1]]).to_csv(csv, index=False)          # one row missing -> refuse
    with pytest.raises(SystemExit, match="expected 117"):
        load_table(config)
