"""Tests for the silver legal reference: builder (mock annotator), evaluator metrics, RQ3 agreement."""

import json

from src.agents.silver_annotator import SilverAnnotator
from src.build_silver_reference import STATUS, SilverReferenceBuilder, create_annotator_llm
from src.config import load_config
from src.evaluate import Evaluator
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.rq3_agreement import agreement, cohen_kappa, label_pairs

CONFIG = load_config()

INDETERMINATE = json.dumps({"label": "indeterminate", "facts": [], "reason": "buyer type not stated",
                            "required_steps": [{"label": "should be removed"}],
                            "possible_steps": [{"label": "Provide withdrawal information"}], "evidence": []})


def make_builder(tmp_path, answers, cases=("19",), run_id="t1"):
    config = dict(CONFIG, cases={"ids": list(cases)})
    annotator = SilverAnnotator(MockLLM(answers), RunLogger(tmp_path / "logs", "SILVER", run_id))
    return SilverReferenceBuilder(config, annotator, tmp_path / "silver.json")


def test_mock_annotator_is_used_in_tests():
    assert isinstance(create_annotator_llm(CONFIG), MockLLM)  # tests can never call Gemini


def test_builder_writes_consistent_reference(tmp_path):
    data = make_builder(tmp_path, [INDETERMINATE]).build()
    case = data["cases"]["19"]
    assert data["status"] == STATUS and len(case["passages"]) == 5
    assert all(p["label"] == "indeterminate" for p in case["passages"])
    assert case["required_steps"] == []                     # removed: not applicable
    assert len(case["possible_steps"]) == 5                 # one per passage
    assert json.loads((tmp_path / "silver.json").read_text(encoding="utf-8"))["frozen_retrieval_sha256"]


def test_builder_resumes_and_skips_finished_cases(tmp_path):
    make_builder(tmp_path, [INDETERMINATE]).build()
    second = make_builder(tmp_path, ["not json"], cases=("19", "01"), run_id="t2")
    data = second.build()
    assert data["cases"]["19"]["passages"][0]["label"] == "indeterminate"   # kept, not re-annotated
    assert data["cases"]["01"]["passages"][0]["label"] == "annotation_failed"


class WordMatcher:
    """Fake TaskMatcher: labels match when they are equal (case-insensitive)."""
    model_name, threshold = "fake", 0.75

    def match(self, generated, reference, threshold=None):
        ref = {v.lower(): k for k, v in reference.items()}
        matched = [{"generated_id": g, "generated_label": label, "reference_id": ref[label.lower()],
                    "reference_label": label, "similarity": 1.0}
                   for g, label in generated.items() if label.lower() in ref]
        return {"matched": matched, "missing": [], "extra": []}

    def best_similarity(self, labels, texts):
        return [1.0 if any(label.lower() in t.lower() for t in texts) else 0.0 for label in labels]


def test_correct_legal_step_is_not_an_error(tmp_path):
    from bpmn_helpers import write_bpmn
    nodes = [("startEvent", "s", "Start"), ("task", "A", "Check stock"),
             ("task", "B", "Provide withdrawal information"), ("task", "C", "Invent discount"), ("endEvent", "e", "End")]
    path = write_bpmn(tmp_path / "g.bpmn", nodes, [("s", "A"), ("A", "B"), ("B", "C"), ("C", "e")])
    evaluator = Evaluator(CONFIG, WordMatcher())
    evaluator.silver = {"19": {"required_steps": [{"label": "Provide withdrawal information"},
                                                  {"label": "Confirm contract on durable medium"}]}}
    semantic = {"n_generated_tasks": 3, "n_matched": 1,
                "extra": [{"generated_id": "B", "generated_label": "Provide withdrawal information"},
                          {"generated_id": "C", "generated_label": "Invent discount"}]}
    additions = {"extra_tasks": [{"generated_id": "B", "label": "Provide withdrawal information", "knowledge_traceable": True},
                                 {"generated_id": "C", "label": "Invent discount", "knowledge_traceable": True}]}

    result = evaluator.silver_diagnostics("19", path, semantic, additions)

    assert result["n_required_steps"] == 2
    assert result["requirement_coverage"] == 0.5
    assert result["n_extra_justified"] == 1                 # the legal step is not counted as an error
    assert result["precision_adjusted"] == round(2 / 3, 4)  # plain precision would be 1/3
    assert result["n_unjustified_knowledge_additions"] == 1  # only the invented step


def test_no_silver_reference_gives_empty_metrics(tmp_path):
    evaluator = Evaluator(CONFIG, WordMatcher())
    evaluator.silver = None
    assert evaluator.silver_diagnostics("19", None, {}, {})["requirement_coverage"] is None


def test_failed_model_scores_zero_coverage():
    evaluator = Evaluator(CONFIG, WordMatcher())
    evaluator.silver = {"19": {"required_steps": [{"label": "X step"}]}}
    result = evaluator.silver_diagnostics("19", None, {"n_generated_tasks": 0, "n_matched": 0, "extra": []},
                                          {"extra_tasks": []})
    assert result["requirement_coverage"] == 0.0 and result["precision_adjusted"] == 0.0


def test_kappa_and_agreement():
    assert cohen_kappa([("applicable", "applicable"), ("indeterminate", "indeterminate")]) == 1.0
    assert cohen_kappa([]) is None
    result = agreement([("applicable", "applicable"), ("indeterminate", "applicable")])
    assert result["accuracy"] == 0.5 and result["confusion"]["indeterminate"]["applicable"] == 1


def test_label_pairs_maps_c3_labels(tmp_path):
    (tmp_path / "19.json").write_text(json.dumps({"passages": [
        {"passage_id": "P1", "label": "Applicable"}, {"passage_id": "P2", "label": "Mediation failed"},
        {"passage_id": "P3", "label": "Irrelevant"}]}), encoding="utf-8")
    silver = {"19": {"passages": [{"passage_id": "P1", "label": "applicable"},
                                  {"passage_id": "P2", "label": "indeterminate"},
                                  {"passage_id": "P3", "label": "not_applicable"}]}}
    pairs, skipped = label_pairs(tmp_path, silver)
    assert pairs == [("applicable", "applicable"), ("not_applicable", "irrelevant")] and skipped == 1
