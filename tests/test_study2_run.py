"""Tests for the Study 2 SR freeze (src/freeze_sr.py) and the Study 2 runner (src/run_study2.py).

No Ollama, no BPMNGen, no retrieval models: MockLLM answers, the fake retrievers of tests/test_rag_v3_steps.py and the
fake harness of tests/test_bpmngen_generator.py. Frozen files, run folders and logs live in tmp_path only.
"""

import copy
import hashlib
import json
import re

import pytest

from src.agents.base_agent import BaseAgent
from src.bpmngen_generator import BPMNGenGenerator
from src.config import load_config, project_path
from src.freeze_sr import check_ids, freeze, held_out_ids
from src.freeze_sr import main as freeze_main
from src.llm.mock_llm import MockLLM
from src.rag_v3_steps import RoutingAgent, StepRouter, StepsAgent
from src.run_folder import RunFolder
from src.run_study2 import CONDITIONS, check_not_existing, prepare, run_condition
from src.run_study2 import main as run_main

from test_bpmngen_generator import bpmngen_config, fake_harness
from test_rag_v3_steps import PASSAGES, FakeReranker, FakeRetriever

CONFIG = load_config()
CASE = "01.1"
HELD_OUT = sorted(held_out_ids(CONFIG))
IRRELEVANT = {"law_focus": "x", "law_quote": "x", "relevant": False, "process_step": None,
              "description_quote": None, "reason": "not about this process"}


def corpus_passages(n=3):
    rows = [json.loads(line) for line in project_path(CONFIG["study2_corpus"]["passages"])
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"rank": i, "passage_id": r["id"], "text": r["text"]} for i, r in enumerate(rows[:n], 1)]


def study_config(tmp_path, cases=None):
    """config.yaml with the bpmngen test generator, a frozen SR file + manifest and run folders in tmp_path."""
    config = copy.deepcopy(CONFIG)
    config["generator"], config["model"] = bpmngen_config()["generator"], bpmngen_config()["model"]
    config["paths"]["runs"], config["paths"]["logs"] = str(tmp_path / "runs"), str(tmp_path / "logs")
    frozen, manifest = tmp_path / "frozen_sr.json", tmp_path / "frozen_sr_manifest.json"
    frozen.write_text(json.dumps({"cases": cases or {CASE: {"passages": corpus_passages()}}}), encoding="utf-8")
    manifest.write_text(json.dumps({"sha256": hashlib.sha256(frozen.read_bytes()).hexdigest()}), encoding="utf-8")
    config["study2_run"] = dict(config["study2_run"], frozen_retrieval=str(frozen), frozen_manifest=str(manifest),
                                freeze_output_dir=str(tmp_path / "sr_freeze"))
    return config


def fake_bpmngen(view, logger):
    return BPMNGenGenerator(view, logger, runner=fake_harness())


def run_all_conditions(config, run_id="study2_test", conditions=CONDITIONS, answers=None):
    view, _ = prepare(config, CASE, run_id, conditions)
    folder = RunFolder(view, run_id, 1)
    check_not_existing(view, folder, conditions, CASE)
    n = len(json.loads(project_path(config["study2_run"]["frozen_retrieval"]).read_text(encoding="utf-8"))
            ["cases"][CASE]["passages"])
    agent_llm = MockLLM([json.dumps(a) for a in (answers or [IRRELEVANT] * n)])
    think_llm = MockLLM(["{}"])
    for condition in conditions:
        run_condition(view, folder, condition, agent_llm, think_llm, bpmngen_factory=fake_bpmngen)
    return view, folder


def case_dir(folder, condition):
    return folder.condition_dir(condition) / CASE


def user_prompt(folder, condition, config):
    request = case_dir(folder, condition) / config["paths"]["bpmngen_output_dir"] / config["paths"]["bpmngen_request_file"]
    return json.loads(request.read_text(encoding="utf-8"))["messages"][-1]["content"]


# ---------- freeze ----------

def test_held_out_ids_are_refused_by_the_freeze():
    assert HELD_OUT == sorted(CONFIG["mediation_test"]["held_out_variants"]["old"]
                              + CONFIG["mediation_test"]["held_out_variants"]["v3"])
    for held in HELD_OUT:
        with pytest.raises(ValueError, match="held-out"):
            check_ids(CONFIG, [CASE, held])
        with pytest.raises(SystemExit, match="held-out"):   # refused before Ollama or any model is loaded
            freeze_main(["--ids", f"{CASE},{held}"])
    check_ids(CONFIG, CONFIG["mediation_test"]["development_variants"])


def test_repeated_and_unknown_ids_are_refused():
    with pytest.raises(ValueError, match="repeated"):
        check_ids(CONFIG, [CASE, CASE])
    with pytest.raises(ValueError, match="no case description"):
        check_ids(CONFIG, ["99.9"])


def test_freeze_writes_the_frozen_layout_and_every_stage(tmp_path):
    config = study_config(tmp_path)
    answers = [{"steps": [{"step_id": "S1", "actor": "sales staff", "activity": "store the contact details",
                           "data_or_object": "email address", "quote": "store them in the system"}]},
               {"routes": [{"article_id": "GDPR-Art13", "reason": "r"}]}]

    def factory(logger):
        llm = MockLLM([json.dumps(a) for a in answers])
        order = [p.id for p in PASSAGES]
        return StepRouter(config, StepsAgent(llm, logger), RoutingAgent(llm, logger), PASSAGES, FakeRetriever(order),
                          FakeRetriever(order[::-1]), FakeReranker(order))

    stages_dir = tmp_path / "sr_freeze" / "t"
    frozen = freeze(config, [CASE], factory, stages_dir)
    assert frozen["case_ids"] == [CASE]
    passages = frozen["cases"][CASE]["passages"]
    assert [p["passage_id"] for p in passages] == ["GDPR-Art13-1", "GDPR-Art13-2"]
    assert all(set(p) == {"rank", "passage_id", "text"} for p in passages)
    assert set(json.loads((stages_dir / f"{CASE}.json").read_text(encoding="utf-8"))) == {"S1", "S2", "S3", "S4"}
    assert list((stages_dir / "logs").glob("SR_FREEZE_*.jsonl"))
    with pytest.raises(FileExistsError):                 # a stages folder is never reused
        freeze(config, [CASE], factory, stages_dir)


# ---------- runner: refusals ----------

def test_held_out_ids_are_refused_by_the_runner(tmp_path):
    config = study_config(tmp_path, {h: {"passages": corpus_passages()} for h in HELD_OUT})
    for held in HELD_OUT:
        with pytest.raises(ValueError, match="held-out"):
            prepare(config, held, "study2_test", CONDITIONS)
        with pytest.raises(SystemExit, match="held-out"):
            run_main(["--case", held, "--run-id", "study2_test"])


def test_runner_refuses_a_study1_run_id_a_changed_frozen_file_and_a_missing_case(tmp_path):
    config = study_config(tmp_path)
    with pytest.raises(ValueError, match="Study 1"):
        prepare(config, CASE, CONFIG["statistics"]["runs"][0], CONDITIONS)
    with pytest.raises(ValueError, match="not in the frozen file"):
        prepare(config, "01.2", "study2_test", CONDITIONS)
    frozen = project_path(config["study2_run"]["frozen_retrieval"])
    frozen.write_text(frozen.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(RuntimeError, match="manifest"):
        prepare(config, CASE, "study2_test", CONDITIONS)


def test_runner_refuses_another_generator(tmp_path):
    config = study_config(tmp_path)
    config["generator"]["type"] = "bpmngen_server"
    with pytest.raises(ValueError, match="bpmngen"):
        prepare(config, CASE, "study2_test", CONDITIONS)


# ---------- runner: the whole run with the mock generator ----------

def test_mock_run_of_all_three_conditions(tmp_path):
    config = study_config(tmp_path)
    _, folder = run_all_conditions(config)
    for condition in CONDITIONS:
        validation = json.loads((case_dir(folder, condition) / "validation.json").read_text(encoding="utf-8"))
        assert validation["generation_succeeded"] and validation["condition"] == condition
        assert folder.is_complete(condition)
    trail = json.loads((folder.condition_dir("C3") / "mediation" / f"{CASE}.json").read_text(encoding="utf-8"))
    assert trail["c3_version"] == "v2"


def test_description_is_identical_in_c1_c2_c3(tmp_path):
    config = study_config(tmp_path)
    _, folder = run_all_conditions(config)
    description = (project_path(config["paths"]["cases"]) / CASE / "description.txt").read_text(encoding="utf-8").strip()
    label = config["generator"]["knowledge_label"]
    parts = {c: user_prompt(folder, c, config).split(f"\n\n{label}\n", 1) for c in CONDITIONS}
    assert all(len(p) == 2 for p in parts.values())
    assert {p[0] for p in parts.values()} == {description}


def test_c2_and_c3_get_the_same_passages(tmp_path):
    config = study_config(tmp_path)
    _, folder = run_all_conditions(config)
    frozen = corpus_passages()
    c2_block = (case_dir(folder, "C2") / "knowledge_block.txt").read_text(encoding="utf-8")
    assert re.findall(r"^\[([^\]]+)\] ", c2_block, flags=re.M) == [p["passage_id"] for p in frozen]
    assert all(p["text"] in c2_block for p in frozen)
    trail = json.loads((folder.condition_dir("C3") / "mediation" / f"{CASE}.json").read_text(encoding="utf-8"))
    assert [(r["passage_id"], r["passage_text"]) for r in trail["passages"]] == [
        (p["passage_id"], p["text"]) for p in frozen]


def test_c3_thinking_only_on_the_named_calls(tmp_path):
    from src.run_study2 import Study2Runner
    from src.logger import RunLogger
    config = study_config(tmp_path)
    view, _ = prepare(config, CASE, "study2_test", ["C3"])
    agent_llm, think_llm = MockLLM(["{}"]), MockLLM(["{}"])
    logger = RunLogger(tmp_path / "l", "C3", "t")
    runner = Study2Runner(view, "C3", logger, tmp_path / "out", {r: agent_llm for r in
                                                                ("relevance", "applicability", "requirement")},
                          bpmngen=fake_bpmngen(view, logger), think_llm=think_llm)
    agent = runner.orchestrator.applicability_agent
    calls = [c for c in vars(agent).values() if isinstance(c, BaseAgent)]
    named = set(config["study2_run"]["think_calls"])
    assert named == {"CheckIfCallV2", "SecondLookCallV2", "VerifierCallV2"}
    assert named <= {type(c).__name__ for c in calls}
    for call in calls:   # a named call or a subclass of one (EventVerifierCallV2 is a VerifierCallV2), as give_thinking
        is_named = bool({k.__name__ for k in type(call).__mro__} & named)
        assert (call.llm is think_llm) == is_named, type(call).__name__
    assert runner.orchestrator.relevance_agent.llm is agent_llm


def test_existing_run_folders_are_untouched(tmp_path):
    config = study_config(tmp_path)
    _, folder = run_all_conditions(config, "study2_old", ["C1"])
    runs = project_path(config["paths"]["runs"])

    def snapshot():
        return {str(p.relative_to(runs)): p.read_bytes() for p in sorted(runs.rglob("*")) if p.is_file()}

    before = snapshot()
    with pytest.raises(FileExistsError, match="never overwritten"):
        run_all_conditions(config, "study2_old", ["C1"])
    with pytest.raises(FileExistsError, match="never overwritten"):
        run_all_conditions(config, "study2_old", CONDITIONS)    # C1 exists: nothing of the run starts
    assert snapshot() == before
    run_all_conditions(config, "study2_new", CONDITIONS)       # another run id leaves the old run as it was
    assert {k: v for k, v in snapshot().items() if k.startswith("study2_old")} == before
