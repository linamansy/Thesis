"""Tests for extended-reference scoring (src/extended_scoring.py, fix C3) on synthetic models and silver data.

A fake matcher (word overlap, no embedding model) keeps the tests fast and exact.
"""

import pandas as pd
import pytest

from src.bpmn_graph import BPMNGraph
from src.config import load_config
from src.evaluate import Evaluator
from src.extended_scoring import NOT_DEFINED, ExtendedScorer, report

from bpmn_helpers import START_END, write_bpmn

CONFIG = load_config()
DESCRIPTION = "The clerk checks the stock. The clerk checks the credit. Then the warehouse ships the goods."
LAW_APPLICABLE = "The trader shall confirm the contract on a durable medium."
LAW_NOT_APPLICABLE = "The consumer shall have a period of 14 days to withdraw from the distance contract."


class WordMatcher:
    """Fake TaskMatcher: similarity = share of the label's words found in the other text; greedy one-to-one."""
    model_name, threshold = "fake", 0.75

    @staticmethod
    def sim(a, b):
        words = a.lower().split()
        return sum(w in b.lower().split() for w in words) / len(words)

    def match(self, generated, reference, threshold=None):
        threshold = self.threshold if threshold is None else threshold
        pairs = sorted(((self.sim(g, r), gi, ri) for gi, g in generated.items() for ri, r in reference.items()),
                       reverse=True)
        used_g, used_r, matched = set(), set(), []
        for s, gi, ri in pairs:
            if s >= threshold and gi not in used_g and ri not in used_r:
                used_g.add(gi), used_r.add(ri)
                matched.append({"generated_id": gi, "generated_label": generated[gi], "reference_id": ri,
                                "reference_label": reference[ri], "similarity": s})
        return {"matched": matched,
                "missing": [{"reference_id": r, "reference_label": reference[r]} for r in reference if r not in used_r],
                "extra": [{"generated_id": g, "generated_label": generated[g]} for g in generated if g not in used_g]}

    def best_similarity(self, labels, texts):
        return [max((self.sim(label, t) for t in texts), default=0.0) for label in labels]


REFERENCE_TASKS = [("task", "A", "Check stock"), ("task", "B", "Check credit"), ("task", "C", "Ship goods")]


def model(path, tasks):
    nodes = START_END + tasks
    ids = ["s"] + [t[1] for t in tasks] + ["e"]
    return write_bpmn(path, nodes, list(zip(ids, ids[1:])))


def silver(applicable: bool):
    """One case with two frozen passages: P1 (applicable or not) with one required step, P2 never applicable."""
    p1 = {"passage_id": "P1", "label": "applicable" if applicable else "indeterminate"}
    return {"X": {"passages": [p1, {"passage_id": "P2", "label": "not_applicable"}],
                  "required_steps": [{"passage_id": "P1", "label": "Confirm contract"}] if applicable else []}}


FROZEN = {"X": {"passages": [{"rank": 1, "passage_id": "P1", "text": LAW_APPLICABLE},
                             {"rank": 2, "passage_id": "P2", "text": LAW_NOT_APPLICABLE}]}}


def scorer(applicable):
    return ExtendedScorer(Evaluator(CONFIG, WordMatcher()), FROZEN, silver(applicable))


def reference(tmp_path):
    return BPMNGraph.from_file(model(tmp_path / "ref.bpmn", REFERENCE_TASKS))


def test_a_correct_applicable_requirement_is_not_penalised(tmp_path):
    generated = model(tmp_path / "gen.bpmn", REFERENCE_TASKS + [("task", "D", "Confirm contract")])
    s = scorer(applicable=True).score("X", generated, reference(tmp_path), DESCRIPTION)
    assert s["extended_precision"] == 1.0            # plain precision would be 3/4
    assert s["pmo_recall"] == 1.0
    assert s["requirement_coverage"] == 1.0 and s["n_expected_requirements"] == 1
    assert s["over_application"] == 0
    plain = Evaluator(CONFIG, WordMatcher()).compare(generated, tmp_path / "ref.bpmn")["semantic"]
    assert plain["precision"] == 0.75


def test_a_task_from_a_non_applicable_rule_is_over_application(tmp_path):
    generated = model(tmp_path / "gen.bpmn", REFERENCE_TASKS + [("task", "W", "Withdraw from contract")])
    s = scorer(applicable=True).score("X", generated, reference(tmp_path), DESCRIPTION)
    assert s["over_application"] == 1 and s["over_application_tasks"] == ["Withdraw from contract"]
    assert s["extended_precision"] == 0.75            # it is still an unmatched task
    assert s["requirement_coverage"] == 0.0           # the expected requirement is missing


def test_a_task_from_the_description_is_not_over_application(tmp_path):
    generated = model(tmp_path / "gen.bpmn", REFERENCE_TASKS + [("task", "W", "Warehouse ships")])
    assert scorer(applicable=False).score("X", generated, reference(tmp_path), DESCRIPTION)["over_application"] == 0


def test_zero_applicable_rules_give_the_original_scores(tmp_path):
    generated = model(tmp_path / "gen.bpmn", [("task", "A", "Check stock"), ("task", "Z", "Bake a cake")])
    s = scorer(applicable=False).score("X", generated, reference(tmp_path), DESCRIPTION)
    plain = Evaluator(CONFIG, WordMatcher()).compare(generated, tmp_path / "ref.bpmn")["semantic"]
    assert s["extended_precision"] == round(plain["precision"], 4) == 0.5
    assert s["pmo_recall"] == round(plain["recall"], 4)
    assert s["requirement_coverage"] == NOT_DEFINED   # never 0 or 1 when nothing is expected


def test_failed_model_scores_zero_and_coverage_stays_undefined_without_requirements(tmp_path):
    s = scorer(applicable=False).score("X", None, reference(tmp_path), DESCRIPTION)
    assert (s["extended_precision"], s["pmo_recall"], s["over_application"]) == (0.0, 0.0, 0)
    assert s["requirement_coverage"] == NOT_DEFINED
    assert scorer(applicable=True).score("X", None, reference(tmp_path), DESCRIPTION)["requirement_coverage"] == 0.0


def test_report_compares_old_and_new_and_is_marked_provisional():
    table = pd.DataFrame([{"run_id": "r", "condition": "C1", "case_id": "X", "extended_precision": 0.5,
                           "pmo_recall": 0.25, "requirement_coverage": NOT_DEFINED, "over_application": 1,
                           "n_expected_requirements": 0}])
    evaluation = pd.DataFrame([{"run_id": "r", "condition": "C1", "case_id": "X", "precision": 0.5, "recall": 0.25}])
    text = report(table, evaluation, CONFIG["evaluation"]["extended_scoring_status"])
    assert "PROVISIONAL" in text and "| C1 | 1 | 0.5000 | 0.5000 | 0.2500 | 0.2500 | 0 | not defined | 1 |" in text
    assert "extended precision = old precision: 1 of 1" in text


def test_command_never_overwrites(tmp_path, monkeypatch):
    from src import extended_scoring
    existing = tmp_path / "extended.csv"
    existing.write_text("x", encoding="utf-8")
    config = dict(CONFIG, paths=dict(CONFIG["paths"], extended_scoring_csv=str(existing),
                                     extended_scoring_report=str(tmp_path / "report.md")))
    monkeypatch.setattr(extended_scoring, "load_config", lambda: config)
    with pytest.raises(SystemExit, match="never overwritten"):
        extended_scoring.main()
    assert existing.read_text(encoding="utf-8") == "x"
