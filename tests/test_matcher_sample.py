"""Tests for the matcher sample (src/matcher_sample.py, fix D4) with synthetic evaluation details and a fake
matcher (no embedding model)."""

import json

import pytest

from src.config import load_config
from src.matcher_sample import MatcherSample

CONFIG = load_config()


class FakeMatcher:
    """Similarity = 1 if the first words are equal, else 0.1 * shared words."""
    def similarity_matrix(self, generated, reference):
        def sim(a, b):
            a, b = a.lower().split(), b.lower().split()
            return 1.0 if a[0] == b[0] else 0.1 * len(set(a) & set(b))
        return [[sim(g, r) for r in reference] for g in generated]


def write_details(run_dir, condition, case_id, matched, missing, extra):
    case_dir = run_dir / condition / case_id
    case_dir.mkdir(parents=True)
    semantic = {"matched": [{"generated_label": g, "reference_label": r, "similarity": s} for g, r, s in matched],
                "missing": [{"reference_label": r} for r in missing],
                "extra": [{"generated_label": g} for g in extra]}
    (case_dir / "evaluation.json").write_text(json.dumps({"semantic": semantic}), encoding="utf-8")


def config_with_runs(tmp_path, n_cases=40, size=30):
    runs = tmp_path / "runs"
    for run_id in ("study_rep1", "smoke_x"):
        (runs / run_id).mkdir(parents=True)
        (runs / run_id / "run_info.json").write_text(json.dumps({"run_id": run_id, "conditions": {"C1": {}}}))
    cases = [f"{i:02d}" for i in range(n_cases)]
    for case_id in cases:
        write_details(runs / "study_rep1", "C1", case_id, [("Check order", "Check the order", 0.91)],
                      ["Ship goods", "Send invoice"], ["Ship parcel", "Bake cake"])
    write_details(runs / "smoke_x", "C1", "00", [("Smoke task", "Smoke ref", 0.99)], [], ["Smoke extra"])
    return dict(CONFIG, paths=dict(CONFIG["paths"], runs=str(runs)), cases={"ids": cases}, conditions=["C1"],
                statistics=dict(CONFIG["statistics"], runs=["study_rep1"]),
                diagnostics=dict(CONFIG["diagnostics"], matcher_sample_size=size))


def test_populations_use_only_study_runs_and_pair_each_extra_with_its_best_reference(tmp_path):
    matched, unmatched = MatcherSample(config_with_runs(tmp_path), FakeMatcher()).populations()
    assert len(matched) == 40 and len(unmatched) == 80
    assert all(r["run_id"] == "study_rep1" for r in matched + unmatched)          # smoke run left out
    ship = next(r for r in unmatched if r["generated_label"] == "Ship parcel")
    assert ship["reference_label"] == "Ship goods" and ship["similarity"] == 1.0   # most similar reference task
    assert {r["matcher_decision"] for r in matched} == {"matched"}


def test_sample_has_30_of_each_kind_an_empty_judgement_column_and_is_reproducible(tmp_path):
    sampler = MatcherSample(config_with_runs(tmp_path), FakeMatcher())
    first = sampler.sample(*sampler.populations())
    second = sampler.sample(*sampler.populations())
    assert (first["matcher_decision"] == "matched").sum() == 30
    assert (first["matcher_decision"] == "unmatched").sum() == 30
    assert (first["manual_judgement"] == "").all() and list(first["sample_id"]) == list(range(1, 61))
    assert first.equals(second)                                                   # fixed seed
    assert list(first["matcher_decision"][:30]) != ["matched"] * 30               # shuffled together


def test_small_population_takes_everything(tmp_path):
    sampler = MatcherSample(config_with_runs(tmp_path, n_cases=5), FakeMatcher())
    table = sampler.sample(*sampler.populations())
    assert (table["matcher_decision"] == "matched").sum() == 5 and (table["matcher_decision"] == "unmatched").sum() == 10


def test_command_never_overwrites(tmp_path, monkeypatch):
    from src import matcher_sample
    existing = tmp_path / "sample.csv"
    existing.write_text("x", encoding="utf-8")
    monkeypatch.setattr(matcher_sample, "load_config",
                        lambda: dict(CONFIG, paths=dict(CONFIG["paths"], matcher_sample=str(existing))))
    with pytest.raises(SystemExit, match="never overwritten"):
        matcher_sample.main()
