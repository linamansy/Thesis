"""Tests for the Evaluator and TaskMatcher (these load the embedding model once)."""

import json

import pytest
from bpmn_helpers import sequential_model, split_model, write_bpmn
from lxml import etree

from src.config import load_config, project_path
from src.evaluate import Evaluator
from src.task_matcher import TaskMatcher

CONFIG = load_config()
CASE_IDS = CONFIG["cases"]["ids"]
BPMN = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"


@pytest.fixture(scope="module")
def evaluator():
    settings = CONFIG["evaluation"]
    return Evaluator(CONFIG, TaskMatcher(settings["embedding_model"], settings["similarity_threshold"]))


def reference_path(case_id):
    return project_path(CONFIG["paths"]["cases"]) / case_id / CONFIG["paths"]["case_reference_file"]


# (a) sanity check: every reference compared with itself scores perfectly
@pytest.mark.parametrize("case_id", CASE_IDS)
def test_reference_against_itself_is_perfect(evaluator, case_id):
    scores = evaluator.compare(reference_path(case_id), reference_path(case_id))
    semantic, behavioral = scores["semantic"], scores["behavioral"]
    assert semantic["precision"] == 1.0
    assert semantic["recall"] == 1.0
    assert semantic["f1"] == 1.0
    assert semantic["missing"] == [] and semantic["extra"] == []
    assert behavioral["n_pairs"] > 0
    assert behavioral["behavioral_similarity"] == 1.0


def remove_one_task(source_path, target_path):
    """Delete the first task with one incoming and one outgoing flow, and reconnect around it."""
    tree = etree.parse(str(source_path))
    process = tree.getroot().find(f"{BPMN}process")
    flows = process.findall(f"{BPMN}sequenceFlow")
    for task in process:
        if not (isinstance(task.tag, str) and task.tag.lower().endswith("task")):
            continue
        incoming = [f for f in flows if f.get("targetRef") == task.get("id")]
        outgoing = [f for f in flows if f.get("sourceRef") == task.get("id")]
        if len(incoming) == 1 and len(outgoing) == 1:
            incoming[0].set("targetRef", outgoing[0].get("targetRef"))
            process.remove(outgoing[0])
            process.remove(task)
            tree.write(str(target_path))
            return task.get("name")
    raise AssertionError("no simple task found")


# (b) a model missing one reference task has lower recall
def test_removed_task_lowers_recall(evaluator, tmp_path):
    reduced = tmp_path / "reduced.bpmn"
    removed_name = remove_one_task(reference_path("01"), reduced)

    semantic = evaluator.compare(reduced, reference_path("01"))["semantic"]

    assert semantic["recall"] == pytest.approx((semantic["n_reference_tasks"] - 1) / semantic["n_reference_tasks"])
    assert semantic["precision"] == 1.0
    assert [m["reference_label"] for m in semantic["missing"]] == [removed_name]


# (c) parallel branches made sequential give lower behavioral similarity
def test_parallel_made_sequential_lowers_behavioral_similarity(evaluator, tmp_path):
    reference = write_bpmn(tmp_path / "parallel.bpmn", *split_model("parallelGateway"))
    generated = write_bpmn(tmp_path / "sequential.bpmn", *sequential_model())

    scores = evaluator.compare(generated, reference)

    assert scores["semantic"]["recall"] == 1.0  # same tasks ...
    behavioral = scores["behavioral"]
    assert behavioral["behavioral_similarity"] == pytest.approx(2 / 3)  # ... but A||B became A->B
    changed = [p for p in behavioral["pairs"] if not p["same"]]
    assert changed[0]["reference_relation"] == "||" and changed[0]["generated_relation"] == "->"


def test_unrelated_labels_are_not_matched(evaluator):
    result = evaluator.matcher.match({"g": "Bake a birthday cake"}, {"r": "Send invoice to customer"})
    assert result["matched"] == []
    assert len(result["missing"]) == 1 and len(result["extra"]) == 1


def test_failed_and_missing_cases_get_zero_and_are_kept(evaluator, tmp_path):
    config = dict(CONFIG, paths=dict(CONFIG["paths"], results=str(tmp_path / "results"),
                                     evaluation=str(tmp_path / "results" / "evaluation.csv")))
    local = Evaluator(config, evaluator.matcher)
    failed_dir = tmp_path / "results" / "C1" / "01"
    failed_dir.mkdir(parents=True)
    (failed_dir / "validation.json").write_text(json.dumps(
        {"run_id": "test", "generation_succeeded": False, "valid": False, "errors": ["failed"]}))
    local.case_ids = ["01", "03"]  # 03 has no output folder at all

    table = local.evaluate(["C1"])

    assert list(table["case_id"]) == ["01", "03"]  # nothing skipped
    assert (table[["precision", "recall", "f1", "behavioral_similarity"]] == 0).all().all()
    assert (tmp_path / "results" / "evaluation.csv").exists()
    details = json.loads((failed_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert details["syntactic"]["generation_succeeded"] is False
    assert len(details["semantic"]["missing"]) == details["semantic"]["n_reference_tasks"]
