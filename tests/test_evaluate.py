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

STUDY_RUNS = ["anthropic_rep1", "mock_rep1", "mock_rep2", "mock_rep3"]  # statistics.runs of the test evaluator


def local_evaluator(evaluator, tmp_path):
    """An Evaluator that reads runs from tmp_path/runs and writes all its outputs inside tmp_path."""
    results = tmp_path / "results"
    paths = dict(CONFIG["paths"], runs=str(tmp_path / "runs"), evaluation=str(results / "evaluation.csv"),
                 evaluation_run_summary=str(results / "evaluation_run_summary.csv"),
                 evaluation_summary=str(results / "evaluation_summary.csv"),
                 evaluation_threshold_csv=str(results / "sensitivity" / "evaluation_threshold_{threshold}.csv"),
                 evaluation_sensitivity_summary=str(results / "sensitivity" / "summary.csv"))
    study = dict(CONFIG["statistics"], runs=STUDY_RUNS)
    local = Evaluator(dict(CONFIG, paths=paths, statistics=study), evaluator.matcher)
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


def write_generated(run_dir, condition, case_id, xml_text, bpmnlint_valid):
    """A BPMNGen-style case: generated.bpmn as given, validation.json with OUR strict verdict on it."""
    from src.validator import BPMNValidator

    case_dir = run_dir / condition / case_id
    case_dir.mkdir(parents=True)
    (case_dir / "generated.bpmn").write_text(xml_text, encoding="utf-8")
    verdict = BPMNValidator().validate(case_dir / "generated.bpmn")
    (case_dir / "validation.json").write_text(json.dumps(
        {"generation_succeeded": True, "valid": verdict["valid"], "errors": verdict["errors"],
         "bpmngen": {"bpmnlint_valid": bpmnlint_valid}}), encoding="utf-8")
    return case_dir


def test_validity_rule_strict_valid_bpmnlint_and_di_rescue(evaluator, tmp_path):
    """valid stays strict; only a model whose diagram section is the sole problem is scored (di_stripped)."""
    from test_di_rescue import B3PMN_TYPO_AND_MISSING_DI, MISSING_DI_NAMESPACE, VALID

    local = local_evaluator(evaluator, tmp_path)
    run_dir = make_run(tmp_path, "mock_rep1", 1, conditions=("C1", "C2", "C3"), provider="ollama")
    write_generated(run_dir, "C1", "01", VALID, bpmnlint_valid=True)
    write_generated(run_dir, "C2", "01", B3PMN_TYPO_AND_MISSING_DI, bpmnlint_valid=False)
    rescued_dir = write_generated(run_dir, "C3", "01", MISSING_DI_NAMESPACE, bpmnlint_valid=True)

    rows = local.evaluate().set_index("condition")

    assert list(rows["valid"]) == [True, False, False]               # strict verdict, never changed
    assert list(rows["bpmnlint_valid"]) == [True, False, True]       # BPMNGen's own verdict, reported next to it
    assert list(rows["di_stripped"]) == [False, False, True]
    # the rescued model is scored exactly like the same model with a correct diagram section ...
    for column in ("n_generated_tasks", "n_matched", "precision", "recall", "f1"):
        assert rows.loc["C3", column] == rows.loc["C1", column], column
    assert rows.loc["C3", "n_generated_tasks"] == 2
    # ... the typo is not repaired: scored 0 like every other invalid model
    assert rows.loc["C2", "n_generated_tasks"] == 0 and rows.loc["C2", "f1"] == 0
    # the generated file itself is never changed, and the details say what happened
    assert (rescued_dir / "generated.bpmn").read_text(encoding="utf-8") == MISSING_DI_NAMESPACE
    details = json.loads((rescued_dir / "evaluation.json").read_text(encoding="utf-8"))["syntactic"]
    assert (details["valid"], details["bpmnlint_valid"], details["di_stripped"]) == (False, True, True)


def test_trace_threshold_sensitivity_check(evaluator, tmp_path):
    """trace_threshold stays 0.5; --sweep also evaluates 0.4 / 0.5 / 0.6 into their own files."""
    local = local_evaluator(evaluator, tmp_path)
    local.trace_csv_pattern = str(tmp_path / "results" / "sensitivity" / "trace_threshold_{threshold}.csv")
    local.trace_summary_path = tmp_path / "results" / "sensitivity" / "trace_summary.csv"
    write_case(make_run(tmp_path, "mock_rep1", 1, conditions=("C2",)), "C2", "01", valid=True)
    assert (local.trace_threshold, local.trace_sweep_thresholds) == (0.5, [0.4, 0.5, 0.6])  # from config.yaml

    summary = local.trace_sweep()

    assert list(summary["trace_threshold"]) == [0.4, 0.5, 0.6]
    for value in ("0.40", "0.50", "0.60"):
        table = pd.read_csv(tmp_path / "results" / "sensitivity" / f"trace_threshold_{value}.csv")
        assert list(table["trace_threshold"]) == [float(value)]
    assert local.trace_summary_path.exists()
    assert local.trace_threshold == 0.5                       # the fixed value is restored
    assert list(local.evaluate()["trace_threshold"]) == [0.5]  # main evaluation uses the fixed value


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


def test_only_study_runs_are_evaluated(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    local.case_ids = ["01", "03"]
    real = make_run(tmp_path, "mock_rep1", 1)
    write_case(real, "C1", "01", valid=True)
    write_case(real, "C1", "03", valid=True)
    write_case(make_run(tmp_path, "smoke_c1", 1), "C1", "01", valid=False)        # smoke run
    write_case(make_run(tmp_path, "pytest_leftover", 1), "C1", "01", valid=False)  # e.g. left by a crashed test

    table = local.evaluate()
    run_summary, summary = local.summarise(table)

    assert table["run_id"].unique().tolist() == ["mock_rep1"]   # nothing outside statistics.runs
    assert not table["smoke_test"].any()
    assert run_summary["run_id"].tolist() == ["mock_rep1"]
    assert summary.iloc[0]["n_repetitions"] == 1 and summary.iloc[0]["f1_mean"] == 1.0


def test_run_ids_outside_the_study_are_refused(evaluator, tmp_path):
    local = local_evaluator(evaluator, tmp_path)
    write_case(make_run(tmp_path, "smoke_test", 1), "C1", "01", valid=True)
    with pytest.raises(ValueError, match="not in config.yaml statistics.runs"):
        local.evaluate(run_ids=["smoke_test"])
    assert local.evaluate().empty   # only a smoke run exists: nothing is evaluated
