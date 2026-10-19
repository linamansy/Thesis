"""Tests for requirement fidelity (src/requirement_fidelity.py, fix C4) on SYNTHETIC data only (Study 1 has no rule
that both C3 and silver call applicable). A fake word-overlap matcher replaces the embedding model."""

import json

import pytest

from src.config import load_config
from src.requirement_fidelity import NOT_ESTIMABLE, RequirementFidelity

CONFIG = load_config()
THRESHOLD = CONFIG["evaluation"]["similarity_threshold"]


class WordMatcher:
    def best_similarity(self, labels, texts):
        def sim(a, b):
            words = a.lower().split()
            return sum(w in b.lower().split() for w in words) / len(words)
        return [max((sim(label, t) for t in texts), default=0.0) for label in labels]


SILVER = {"X": {
    "passages": [{"passage_id": "P1", "label": "applicable"}, {"passage_id": "P2", "label": "applicable"},
                 {"passage_id": "P3", "label": "indeterminate"}, {"passage_id": "P4", "label": "applicable"}],
    "required_steps": [
        {"passage_id": "P1", "label": "confirm contract", "actor": "trader", "timing": "after the order"},
        {"passage_id": "P1", "label": "send invoice", "actor": None, "timing": None},
        {"passage_id": "P2", "label": "inform consumer about withdrawal", "actor": "trader", "timing": None},
        {"passage_id": "P4", "label": "pay interest", "actor": "debtor", "timing": None}]}}


def requirement(action, actor="trader", ordering=None):
    return {"actor": actor, "action": action, "condition": None, "ordering": ordering}


MEDIATION = {"passages": [
    {"passage_id": "P1", "label": "Applicable", "requirement": requirement("confirm contract", ordering="after the order")},
    {"passage_id": "P2", "label": "Applicable", "requirement": requirement("archive records", actor="clerk")},
    {"passage_id": "P3", "label": "Applicable", "requirement": requirement("anything")},   # silver: indeterminate
    {"passage_id": "P4", "label": "Indeterminate", "requirement": None}]}                 # C3: not applicable


def fidelity():
    return RequirementFidelity(WordMatcher(), THRESHOLD, SILVER)


def test_only_rules_both_call_applicable_are_compared():
    rows, c3_only, silver_only = fidelity().pairs("X", MEDIATION)
    assert [r["passage_id"] for r in rows] == ["P1", "P2"]
    assert (c3_only, silver_only) == (1, 1)


def test_a_faithful_requirement_matches_its_expected_step():
    p1 = fidelity().pairs("X", MEDIATION)[0][0]
    assert p1["expected_step"] == "confirm contract" and p1["action_similarity"] == 1.0 and p1["action_faithful"]
    assert p1["actor_faithful"] is True and p1["timing_similarity"] == 1.0
    assert p1["n_expected_steps"] == 2   # the best of the rule's two expected steps is used


def test_an_unfaithful_requirement_is_detected():
    p2 = fidelity().pairs("X", MEDIATION)[0][1]
    assert p2["action_faithful"] is False and p2["actor_faithful"] is False
    assert p2["timing_similarity"] is None   # neither side states a timing: not comparable


def test_missing_silver_actor_is_not_comparable():
    result = fidelity().compare(requirement("send invoice"), [SILVER["X"]["required_steps"][1]])
    assert result["action_faithful"] and result["actor_similarity"] is None and result["actor_faithful"] is None


def test_run_summary_and_not_estimable():
    f = fidelity()
    rows, c3_only, silver_only = f.pairs("X", MEDIATION)
    summary = f.run_summary(rows, c3_only, silver_only)
    assert summary["n_pairs"] == 2 and summary["action_faithful_share"] == 0.5
    assert summary["actor_faithful_share"] == 0.5 and summary["n_actor_comparable"] == 2
    empty = f.run_summary([], 0, 3)
    assert empty["action_faithful_share"] == NOT_ESTIMABLE and empty["actor_faithful_share"] == NOT_ESTIMABLE


def test_mediation_folder_is_read_without_the_run_summary(tmp_path):
    (tmp_path / "X.json").write_text(json.dumps(MEDIATION), encoding="utf-8")
    (tmp_path / "run_summary.json").write_text("{}", encoding="utf-8")
    rows, summary = fidelity().analyse_mediation_dir(tmp_path, "run_summary.json")
    assert len(rows) == 2 and summary["n_pairs"] == 2


def test_command_never_overwrites(tmp_path, monkeypatch):
    from src import requirement_fidelity
    existing = tmp_path / "pairs.csv"
    existing.write_text("x", encoding="utf-8")
    config = dict(CONFIG, paths=dict(CONFIG["paths"], requirement_fidelity_csv=str(existing),
                                     requirement_fidelity_summary=str(tmp_path / "s.csv")))
    monkeypatch.setattr(requirement_fidelity, "load_config", lambda: config)
    with pytest.raises(SystemExit, match="never overwritten"):
        requirement_fidelity.main()
