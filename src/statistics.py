"""Statistical analysis, exactly as fixed in docs/ANALYSIS_PLAN.md (sections 1-5), BEFORE any evaluation.

Input:  results/evaluation.csv (written by python -m src.evaluate), only the runs in config.yaml
        statistics.runs (ollama_rep1..3), at the main similarity threshold. Smoke runs are never used.
Output: CSV tables in results/statistics/ (see main()).

Steps (the section numbers refer to the analysis plan):
  1  Unit of analysis: the 3 repetitions are averaged per case and condition -> 13 paired values per condition.
  2  RQ1, primary metrics F1 and behavioural similarity:
       - Friedman test across C1/C2/C3 (reported, not corrected)
       - Wilcoxon signed-rank (two-sided) for the planned comparisons C3 vs C1 and C3 vs C2
       - Holm correction over these 4 Wilcoxon tests (2 metrics x 2 comparisons), alpha 0.05
       - effect sizes: median paired difference (C3 minus the other condition) with a bootstrap 95% CI
         (percentile method, fixed seed) and the matched-pairs rank-biserial correlation
       - C2 vs C1: effect sizes only (descriptive, no test)
     Secondary metrics: descriptive per condition (mean, median, quartiles of the case means).
     Over-application: n_unjustified_knowledge_additions, C3 vs C2, Wilcoxon (always reported, not corrected).
  3  RQ2 (exploratory): Spearman correlation between the complexity of the reference model (flow nodes,
     Cardoso's CFC) and the per-case effect (C3-C1, C3-C2) on the primary metrics. No correction.
  5  Data handling: invalid outputs that cannot be rescued are already scored 0 in evaluation.csv (main
     analysis). Secondary analysis: the same tests on valid or rescued (di_stripped) generations only.
     Failure-type table per condition.

Implementation choices made before any results were seen (not fixed by the plan, stated here):
  - Wilcoxon: scipy's default zero handling ("wilcox": zero differences are dropped) and method ("auto":
    exact for small samples without ties). If all paired differences are zero there is nothing to test:
    the row says "not testable" and the test counts as p = 1 in the Holm correction (conservative).
  - Behavioural similarity cannot be computed for a valid model with fewer than two matched tasks
    (empty in evaluation.csv). It is treated as missing, not as 0: the case mean uses the repetitions that
    have a value, and a case without any value in a condition is left out of that comparison (n is reported).
  - Case means and paired differences are rounded to 10 decimals, so floating-point noise cannot turn an
    exact zero or tie into a tiny difference (evaluation.csv itself has 4 decimals).
  - Rank-biserial correlation: (sum of ranks of positive differences - sum of ranks of negative differences)
    / sum of all ranks, zero differences dropped (the same differences the Wilcoxon test uses).

Run from the project root:  .venv\\Scripts\\python.exe -m src.statistics
"""

import numpy as np
import pandas as pd
from scipy import stats

from src.config import load_config, project_path

FAILURE_TYPES = ["invalid_xml_other", "missing_namespace_rescued", "thinking_detected", "context_limit_hit",
                 "timed_out"]


# ---------- building blocks (each tested with known answers) ----------

DECIMALS = 10  # floating-point noise (e.g. 0.3 - 0.2 = 0.09999999999999998) must not create fake ranks or
               # fake non-zero differences; evaluation.csv has 4 decimals, so 10 loses nothing


def case_means(table: pd.DataFrame, metric: str, conditions: list[str]) -> pd.DataFrame:
    """One value per case and condition: the mean over the repetitions (missing values are skipped)."""
    values = pd.to_numeric(table[metric], errors="coerce")
    means = table.assign(_value=values).groupby(["case_id", "condition"])["_value"].mean().unstack("condition")
    return means.reindex(columns=conditions).round(DECIMALS)


def paired_differences(means: pd.DataFrame, first: str, second: str) -> pd.Series:
    """first minus second, for the cases that have a value in both conditions."""
    return (means[first] - means[second]).dropna().round(DECIMALS)


def wilcoxon_test(differences: pd.Series) -> dict:
    """Two-sided Wilcoxon signed-rank test of the paired differences."""
    d = np.asarray(differences, dtype=float)
    result = {"n": len(d), "n_nonzero": int(np.count_nonzero(d)), "statistic": np.nan, "p": np.nan, "note": ""}
    if result["n_nonzero"] == 0:
        result["note"] = "not testable: all paired differences are zero" if len(d) else "not testable: no pairs"
        return result
    test = stats.wilcoxon(d, zero_method="wilcox", alternative="two-sided")
    result.update(statistic=float(test.statistic), p=float(test.pvalue))
    return result


def rank_biserial(differences: pd.Series) -> float:
    """Matched-pairs rank-biserial correlation (+1: all differences positive, -1: all negative)."""
    d = np.asarray(differences, dtype=float)
    d = d[d != 0]
    if len(d) == 0:
        return np.nan
    ranks = stats.rankdata(np.abs(d))
    return float((ranks[d > 0].sum() - ranks[d < 0].sum()) / ranks.sum())


def bootstrap_median_ci(differences: pd.Series, resamples: int, seed: int, level: float = 0.95) -> tuple:
    """Median of the paired differences and its bootstrap percentile CI (cases resampled with replacement)."""
    d = np.asarray(differences, dtype=float)
    if len(d) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    medians = np.median(d[rng.integers(0, len(d), size=(resamples, len(d)))], axis=1)
    tail = (1 - level) / 2 * 100
    return float(np.median(d)), float(np.percentile(medians, tail)), float(np.percentile(medians, 100 - tail))


def holm(p_values: list[float]) -> list[float]:
    """Holm step-down adjusted p-values. A missing p (test not possible) counts as 1."""
    p = np.array([1.0 if np.isnan(x) else x for x in p_values])
    order = np.argsort(p)
    adjusted = np.empty(len(p))
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (len(p) - rank) * p[index]))
        adjusted[index] = running
    return adjusted.tolist()


def friedman_test(means: pd.DataFrame, conditions: list[str]) -> dict:
    """Friedman test across the conditions, on the cases that have a value in all of them."""
    complete = means[conditions].dropna()
    result = {"n": len(complete), "statistic": np.nan, "p": np.nan, "note": ""}
    if len(complete) < 2 or (complete.nunique(axis=1) == 1).all():
        result["note"] = "not testable: fewer than 2 cases or no differences between conditions"
        return result
    test = stats.friedmanchisquare(*[complete[c] for c in conditions])
    result.update(statistic=float(test.statistic), p=float(test.pvalue))
    return result


def spearman(x: pd.Series, y: pd.Series) -> dict:
    """Spearman correlation on the cases that have both values."""
    both = pd.concat([x, y], axis=1).dropna()
    if len(both) < 3 or both.iloc[:, 0].nunique() < 2 or both.iloc[:, 1].nunique() < 2:
        return {"n": len(both), "rho": np.nan, "p": np.nan, "note": "not computable (too few cases or no variation)"}
    test = stats.spearmanr(both.iloc[:, 0], both.iloc[:, 1])
    return {"n": len(both), "rho": float(test.statistic), "p": float(test.pvalue), "note": ""}


# ---------- the analysis ----------

class Analysis:
    """All tables of the analysis plan for one evaluation table."""

    def __init__(self, table: pd.DataFrame, settings: dict, conditions: list[str]):
        self.table = table
        self.s = settings
        self.conditions = conditions

    def comparison_row(self, means: pd.DataFrame, metric: str, first: str, second: str, role: str) -> dict:
        d = paired_differences(means, first, second)
        median, low, high = bootstrap_median_ci(d, self.s["bootstrap_resamples"], self.s["bootstrap_seed"])
        row = {"metric": metric, "comparison": f"{first} vs {second}", "role": role,
               "median_difference": median, "ci95_low": low, "ci95_high": high,
               "rank_biserial": rank_biserial(d)}
        if role == "descriptive":
            return row | {"n": len(d)}
        return row | {f"{k}": v for k, v in wilcoxon_test(d).items()}

    def planned_tests(self, table: pd.DataFrame) -> pd.DataFrame:
        """Friedman + the 4 planned Wilcoxon tests (Holm-corrected) + C2 vs C1 effect sizes, for one table."""
        rows = []
        for metric in self.s["primary_metrics"]:
            means = case_means(table, metric, self.conditions)
            rows.append({"metric": metric, "comparison": " vs ".join(self.conditions), "role": "friedman",
                         **friedman_test(means, self.conditions)})
            for first, second in self.s["planned_comparisons"]:
                rows.append(self.comparison_row(means, metric, first, second, "planned"))
            for first, second in self.s["descriptive_comparisons"]:
                rows.append(self.comparison_row(means, metric, first, second, "descriptive"))
        result = pd.DataFrame(rows)
        planned = result["role"] == "planned"
        result.loc[planned, "p_holm"] = holm(result.loc[planned, "p"].tolist())
        result.loc[planned, "significant_holm"] = result.loc[planned, "p_holm"] < self.s["alpha"]
        return result

    def descriptive(self) -> pd.DataFrame:
        """Per condition and metric: distribution of the case means (all generations)."""
        rows = []
        for metric in self.s["primary_metrics"] + self.s["secondary_metrics"]:
            means = case_means(self.table, metric, self.conditions)
            for condition in self.conditions:
                v = means[condition].dropna()
                rows.append({"metric": metric, "condition": condition, "n_cases": len(v),
                             "mean": v.mean() if len(v) else np.nan, "median": v.median() if len(v) else np.nan,
                             "q1": v.quantile(0.25) if len(v) else np.nan, "q3": v.quantile(0.75) if len(v) else np.nan})
        return pd.DataFrame(rows)

    def overapplication(self) -> pd.DataFrame:
        metric = self.s["overapplication_metric"]
        first, second = self.s["overapplication_comparison"]
        means = case_means(self.table, metric, self.conditions)
        return pd.DataFrame([self.comparison_row(means, metric, first, second, "overapplication")])

    def rq2(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Per-case effects and their Spearman correlation with the complexity of the reference model."""
        complexity = self.table.groupby("case_id")[self.s["complexity_measures"]].first()
        effects = pd.DataFrame(index=complexity.index)
        for metric in self.s["primary_metrics"]:
            means = case_means(self.table, metric, self.conditions)
            for first, second in self.s["planned_comparisons"]:
                effects[f"{metric}: {first}-{second}"] = (means[first] - means[second]).round(DECIMALS)
        rows = [{"complexity": c, "effect": e, **spearman(complexity[c], effects[e])}
                for c in self.s["complexity_measures"] for e in effects.columns]
        return pd.DataFrame(rows), complexity.join(effects).reset_index()

    def failure_types(self) -> pd.DataFrame:
        """Per condition: generations, valid, and each failure type (each generation counted once)."""
        rows = []
        for condition in self.conditions:
            group = self.table[self.table["condition"] == condition]
            row = {"condition": condition, "n_generations": len(group),
                   "n_valid": int(group["valid"].astype(bool).sum())}
            row |= {t: int((group["failure_type"] == t).sum()) for t in FAILURE_TYPES}
            rows.append(row)
        return pd.DataFrame(rows)

    def valid_or_rescued(self) -> pd.DataFrame:
        """Secondary analysis (plan section 5): only generations that are valid or rescued (di_stripped)."""
        keep = self.table["valid"].astype(bool) | self.table["di_stripped"].astype(bool)
        return self.planned_tests(self.table[keep])


def load_table(config: dict) -> pd.DataFrame:
    """The evaluation rows of the analysed runs, at the main similarity threshold."""
    settings = config["statistics"]
    table = pd.read_csv(project_path(config["paths"]["evaluation"]), dtype={"case_id": str})
    table = table[table["run_id"].isin(settings["runs"]) & ~table["smoke_test"].astype(bool)]
    table = table[np.isclose(table["similarity_threshold"], config["evaluation"]["similarity_threshold"])]
    expected = len(settings["runs"]) * len(config["conditions"]) * len(config["cases"]["ids"])
    if len(table) != expected:
        raise SystemExit(f"evaluation.csv has {len(table)} rows for {settings['runs']}, expected {expected}. "
                         f"Run python -m src.evaluate --runs {' '.join(settings['runs'])} first.")
    return table


def run_analysis(table: pd.DataFrame, config: dict, out_dir) -> dict[str, pd.DataFrame]:
    """Compute every table and write it to out_dir as CSV. Returns the tables by file name."""
    analysis = Analysis(table, config["statistics"], config["conditions"])
    rq2, rq2_cases = analysis.rq2()
    tables = {
        "rq1_primary_tests.csv": analysis.planned_tests(table),
        "rq1_descriptive.csv": analysis.descriptive(),
        "rq1_overapplication.csv": analysis.overapplication(),
        "rq2_spearman.csv": rq2,
        "rq2_case_effects.csv": rq2_cases,
        "secondary_valid_or_rescued_tests.csv": analysis.valid_or_rescued(),
        "failure_types.csv": analysis.failure_types(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(out_dir / name, index=False)
    return tables


def main() -> None:
    config = load_config()
    out_dir = project_path(config["paths"]["statistics_dir"])
    tables = run_analysis(load_table(config), config, out_dir)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for name, frame in tables.items():
        print(f"\n=== {name} ===")
        print(frame.round(4).to_string(index=False))
    print(f"\nSaved {len(tables)} tables in {out_dir}")


if __name__ == "__main__":
    main()
