"""Tests for the Evaluator and TaskMatcher (these load the embedding model once)."""

import json
import shutil

import pandas as pd
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


def test_one_matched_task_makes_behavioral_not_computable(evaluator, tmp_path):
    reference = write_bpmn(tmp_path / "reference.bpmn", *split_model("parallelGateway"))
    generated = write_bpmn(tmp_path / "generated.bpmn",
                           [("startEvent", "s", ""), ("task", "T", "Check stock"), ("endEvent", "e", "")],
                           [("s", "T"), ("T", "e")])

    scores = evaluator.compare(generated, reference)

    assert scores["semantic"]["n_matched"] == 1
    assert scores["behavioral"]["behavioral_similarity"] is None
    assert scores["behavioral"]["behavioral_computable"] is False


def test_threshold_can_be_changed_per_call(evaluator):
    # "Ship goods" vs "Package goods" has a cosine similarity of about 0.81.
    generated, reference = {"g": "Ship goods"}, {"r": "Package goods"}
    assert len(evaluator.matcher.match(generated, reference, threshold=0.80)["matched"]) == 1
    assert len(evaluator.matcher.match(generated, reference, threshold=0.85)["matched"]) == 0


def test_unrelated_labels_are_not_matched(evaluator):
    result = evaluator.matcher.match({"g": "Bake a birthday cake"}, {"r": "Send invoice to customer"})
    assert result["matched"] == []
    assert len(result["missing"]) == 1 and len(result["extra"]) == 1


# ---------- evaluating runs ----------

def local_evaluator(evaluator, tmp_path):
    """An Evaluator that reads runs from tmp_path/runs and writes all its outputs inside tmp_path."""
    results = tmp_path / "results"
    paths = dict(CONFIG["paths"], runs=str(tmp_path / "runs"), evaluation=str(results / "evaluation.csv"),
                 evaluation_run_summary=str(results / "evaluation_run_summary.csv"),
                 evaluation_summary=str(results / "evaluation_summary.csv"),
                 evaluation_threshold_csv=str(results / "sensitivity" / "evaluation_threshold_{threshold}.csv"),
                 evaluation_sensitivity_summary=str(results / "sensitivity" / "summary.csv"))
    local = Evaluator(dict(CONFIG, paths=paths), evaluator.matcher)
    local.case_ids = ["01"]
    return local


def make_run(tmp_path, run_id, repetition, conditions=("C1",), provider="mock", model="MODEL_NAME_PLACEHOLDER"):
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    info = {"run_id": run_id, "repetition": repetition, "provider": provider, "model": model, "temperature": 0,
            "conditions": {c: {} for c in conditions}}
    (run_dir / "run_info.json").write_text(json.dumps(info), encoding="utf-8")
    return run_dir


def write_case(run_dir, condition, case_id, valid):
    """A valid case is a copy of the reference model (perfect scores); an invalid one failed generation."""
    case_dir = run_dir / condition / case_id
    case_dir.mkdir(parents=True)
    if valid:
        shutil.copyfile(reference_path(case_id), case_dir / "generated.bpmn")
    (case_dir / "validation.json").write_text(json.dumps(
        {"generation_succeeded": valid, "valid": valid, "errors": [] if valid else ["failed"]}))
    return case_dir


def test_failed_and_missing_cases_get_zero_and_are_kept(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    run_dir = make_run(tmp_path, "mock_rep1", 1)
    failed_dir = write_case(run_dir, "C1", "01", valid=False)
    local.case_ids = ["01", "03"]  # 03 has no output folder at all

    table = local.evaluate()

    assert list(table["case_id"]) == ["01", "03"]  # nothing skipped
    assert (table[["precision", "recall", "f1", "behavioral_similarity"]] == 0).all().all()
    assert table["behavioral_computable"].all()  # scored 0 by rule, not "not computable"
    assert (table["run_id"] == "mock_rep1").all() and (table["repetition"] == 1).all()
    assert (tmp_path / "results" / "evaluation.csv").exists()
    details = json.loads((failed_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert details["syntactic"]["generation_succeeded"] is False
    assert (details["run_id"], details["repetition"]) == ("mock_rep1", 1)
    assert len(details["semantic"]["missing"]) == details["semantic"]["n_reference_tasks"]


def test_only_conditions_run_in_a_run_are_evaluated(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "mock_rep1", 1, conditions=("C1",)), "C1", "01", valid=True)
    write_case(make_run(tmp_path, "mock_rep2", 2, conditions=("C1", "C2")), "C2", "01", valid=True)

    table = local.evaluate()

    assert list(zip(table["run_id"], table["condition"])) == [("mock_rep1", "C1"), ("mock_rep2", "C1"),
                                                            ("mock_rep2", "C2")]
    assert table.loc[1, "f1"] == 0  # rep2 started C1 but case 01 has no output: 0, not skipped


def test_summary_gives_mean_and_sd_over_repetitions(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "mock_rep1", 1), "C1", "01", valid=True)    # f1 = 1
    write_case(make_run(tmp_path, "mock_rep2", 2), "C1", "01", valid=False)   # f1 = 0
    write_case(make_run(tmp_path, "mock_rep3", 3), "C1", "01", valid=True)    # f1 = 1

    run_summary, summary = local.summarise(local.evaluate())

    assert run_summary["f1_mean"].tolist() == [1.0, 0.0, 1.0]
    row = summary.iloc[0]
    assert (row["condition"], row["n_repetitions"], row["repetitions"]) == ("C1", 3, "1,2,3")
    assert row["f1_mean"] == pytest.approx(2 / 3, abs=1e-4)
    assert row["f1_sd"] == pytest.approx(0.57735, abs=1e-4)   # sample SD of 1, 0, 1
    assert (tmp_path / "results" / "evaluation_summary.csv").exists()
    assert (tmp_path / "results" / "evaluation_run_summary.csv").exists()


def test_mock_and_real_runs_are_never_mixed(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "mock_rep1", 1), "C1", "01", valid=False)
    write_case(make_run(tmp_path, "anthropic_rep1", 1, provider="anthropic", model="claude-x"), "C1", "01",
               valid=True)

    _, summary = local.summarise(local.evaluate())

    assert list(zip(summary["provider"], summary["f1_mean"])) == [("anthropic", 1.0), ("mock", 0.0)]


def test_single_repetition_has_empty_sd(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "mock_rep1", 1), "C1", "01", valid=True)
    _, summary = local.summarise(local.evaluate())
    assert pd.isna(summary.iloc[0]["f1_sd"])


def test_sweep_writes_one_csv_per_threshold(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    case_dir = write_case(make_run(tmp_path, "mock_rep1", 1), "C1", "01", valid=True)

    summary = local.sweep()

    sensitivity_dir = tmp_path / "results" / "sensitivity"
    for threshold in ["0.70", "0.75", "0.80", "0.85"]:
        table = pd.read_csv(sensitivity_dir / f"evaluation_threshold_{threshold}.csv")
        assert table["similarity_threshold"].tolist() == [float(threshold)]
        assert table["repetition"].tolist() == [1]
    assert (sensitivity_dir / "summary.csv").exists()
    assert summary["similarity_threshold"].tolist() == [0.70, 0.75, 0.80, 0.85]
    assert set(summary.columns) >= {"f1_mean", "f1_sd", "n_repetitions"}
    assert not (case_dir / "evaluation.json").exists()  # details only describe the main threshold


def test_smoke_runs_are_left_out_of_summaries(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    local.case_ids = ["01", "03"]
    real = make_run(tmp_path, "mock_rep1", 1)
    write_case(real, "C1", "01", valid=True)
    write_case(real, "C1", "03", valid=True)
    smoke = make_run(tmp_path, "smoke_c1", 1)
    write_case(smoke, "C1", "01", valid=False)   # the smoke run only ran case 01 (and it failed)

    table = local.evaluate()
    run_summary, summary = local.summarise(table)

    smoke_rows = table[table["smoke_test"]]
    assert smoke_rows["case_id"].tolist() == ["01"]          # only the case it ran, no zero rows for 03
    assert run_summary["run_id"].tolist() == ["mock_rep1"]   # smoke run not in the per-run summary
    assert summary.iloc[0]["n_repetitions"] == 1 and summary.iloc[0]["f1_mean"] == 1.0


def test_only_smoke_runs_gives_empty_summaries(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "smoke_test", 1), "C1", "01", valid=True)
    run_summary, summary = local.summarise(local.evaluate())
    assert run_summary.empty and summary.empty
