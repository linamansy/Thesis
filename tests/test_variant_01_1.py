"""Tests for the variant 01.1 runs and the oracle diagnostic (src/run_variant_01_1.py).

No Ollama, no BPMNGen: MockLLM answers for the C3 v2 agents and the fake harness of tests/test_bpmngen_generator.py.
"""

import copy
import json
from pathlib import Path

import pytest

from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.orchestrator_v2 import OrchestratorV2
from src.run_variant_01_1 import (REP_REPETITION, REP_RUNS, RUNS, SAME_AS_DEV, VariantRunner, check_previous_repetition,
                                  check_same_as_dev, oracle_rep_dirs, oracle_top5, run_id,
                                  run_view, target_in_prompt)

from test_bpmngen_generator import bpmngen_config, fake_harness
from src.bpmngen_generator import BPMNGenGenerator

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]


def frozen_01_1():
    return json.loads(project_path(GDPR["frozen_variants_rerank"]).read_text(encoding="utf-8"))["cases"]["01.1"]


def test_oracle_replaces_only_rank_5_with_art13_1():
    frozen = sorted(frozen_01_1()["passages"], key=lambda p: p["rank"])
    oracle = oracle_top5(CONFIG)["cases"]["01.1"]["passages"]
    assert [p["rank"] for p in oracle] == [1, 2, 3, 4, 5]
    assert [(p["passage_id"], p["text"]) for p in oracle[:4]] == [(p["passage_id"], p["text"]) for p in frozen[:4]]
    assert oracle[4]["passage_id"] == "GDPR-Art13-1" and oracle[4]["replaces"] == frozen[4]["passage_id"]
    assert oracle[4]["text"].startswith("General Data Protection Regulation (2016/679) - Article 13")


def test_committed_oracle_file_equals_the_rule():
    path = project_path(GDPR["oracle_top5"])
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved.pop("created_at")
    assert saved == oracle_top5(CONFIG)


def test_run_views_use_one_case_and_the_right_passage_file():
    assert run_view(CONFIG, "main", "C1")["cases"]["ids"] == ["01"]
    for condition in ("C2", "C3"):
        assert run_view(CONFIG, "main", condition)["paths"]["frozen_retrieval"] == GDPR["frozen_variants_rerank"]
        oracle = run_view(CONFIG, "oracle", condition)
        assert oracle["cases"]["ids"] == ["01.1"] and oracle["paths"]["frozen_retrieval"] == GDPR["oracle_top5"]
    assert run_id(CONFIG, "main") == "variant_01.1" and run_id(CONFIG, "oracle") == "oracle_01.1"
    with pytest.raises(ValueError):
        run_view(CONFIG, "oracle", "C1")
    assert CONFIG["cases"]["ids"] != ["01"]                     # the config itself is unchanged


def test_settings_must_equal_the_development_run(tmp_path):
    # the real development run_info.json (read only), copied into a temporary runs folder
    real = Path(__file__).resolve().parents[1] / "results" / "runs" / GDPR["variant_same_as"] / "run_info.json"
    (tmp_path / GDPR["variant_same_as"]).mkdir()
    (tmp_path / GDPR["variant_same_as"] / "run_info.json").write_bytes(real.read_bytes())
    config = copy.deepcopy(CONFIG)
    config["paths"]["runs"] = str(tmp_path)
    dev = json.loads(real.read_text(encoding="utf-8"))
    assert dev["ollama_version"] == "0.40.8" and dev["generator"] == "bpmngen/qwen3:8b"
    settings = {k: dev.get(k) for k in SAME_AS_DEV} | {"ollama_version": "0.40.11"}
    assert str(GDPR["ollama_version"]) == "0.40.11"
    check_same_as_dev(config, settings)
    for key, value in (("ollama_version", "0.40.8"), ("ollama_version", None), ("generator_digest", "x"),
                       ("temperature", 0.3)):
        with pytest.raises(ValueError, match=key):
            check_same_as_dev(config, dict(settings, **{key: value}))


def test_target_in_prompt():
    text = "Title line\n1. Where personal data relating to a data subject are collected from the data subject"
    assert target_in_prompt("... [GDPR-Art13-1] ...", text, "GDPR-Art13-1")
    assert target_in_prompt(f"x {text.split(chr(10))[1]} y", text, "GDPR-Art13-1")
    assert not target_in_prompt("Title line only", text, "GDPR-Art13-1")


def variant_runner(tmp_path, run, condition, answers=None):
    view = run_view(CONFIG, run, condition)
    view["generator"], view["model"] = bpmngen_config()["generator"], bpmngen_config()["model"]
    logger = RunLogger(tmp_path / "logs", condition, "t")
    generator = BPMNGenGenerator(view, logger, runner=fake_harness())
    llms = None
    if condition == "C3":
        llm = MockLLM([json.dumps(a) for a in answers])
        llms = {"relevance": llm, "applicability": llm, "requirement": llm}
    return VariantRunner(view, condition, logger, tmp_path / "run" / condition, llms, bpmngen=generator)


def test_c2_main_and_oracle_give_their_passages(tmp_path):
    main = variant_runner(tmp_path / "m", "main", "C2")
    main.run_case("01.1")
    block = (tmp_path / "m" / "run" / "C2" / "01.1" / "knowledge_block.txt").read_text(encoding="utf-8")
    assert "[GDPR-Art13-3]" in block and "[GDPR-Art13-1]" not in block
    oracle = variant_runner(tmp_path / "o", "oracle", "C2")
    oracle.run_case("01.1")
    block = (tmp_path / "o" / "run" / "C2" / "01.1" / "knowledge_block.txt").read_text(encoding="utf-8")
    assert "[GDPR-Art13-1]" in block and "[GDPR-Art13-3]" not in block


def test_c3_uses_c3_v2_and_writes_its_audit_trail(tmp_path):
    irrelevant = {"law_focus": "x", "law_quote": "x", "relevant": False, "process_step": None,
                  "description_quote": None, "reason": "not about this process"}
    runner = variant_runner(tmp_path, "oracle", "C3", [irrelevant] * 5)
    assert isinstance(runner.orchestrator, OrchestratorV2)
    record = runner.run_case("01.1")
    trail = json.loads((tmp_path / "run" / "C3" / "mediation" / "01.1.json").read_text(encoding="utf-8"))
    assert trail["c3_version"] == "v2" and len(trail["passages"]) == 5
    assert trail["knowledge_block"] == runner.no_knowledge_text   # nothing Applicable -> C1's text
    assert record["generation_succeeded"]
    runner.orchestrator.save_run_summary("t")                       # no run summary in v2 (no error)


def test_runs_table():
    assert RUNS == {"main": {"C1": "01", "C2": "01.1", "C3": "01.1"}, "oracle": {"C2": "01.1", "C3": "01.1"},
                    "after_round3_frozen": {"C3": "01.1"}, "after_round3_oracle": {"C3": "01.1"}}


def test_after_round3_runs_are_c3_only_with_their_own_run_ids():
    frozen, oracle = run_view(CONFIG, "after_round3_frozen", "C3"), run_view(CONFIG, "after_round3_oracle", "C3")
    assert frozen["cases"]["ids"] == oracle["cases"]["ids"] == ["01.1"]
    assert frozen["paths"]["frozen_retrieval"] == GDPR["frozen_variants_rerank"]
    assert oracle["paths"]["frozen_retrieval"] == GDPR["oracle_top5"]
    assert run_id(CONFIG, "after_round3_frozen") == "after_round3_frozen"
    assert run_id(CONFIG, "after_round3_oracle") == "after_round3_oracle"
    for condition in ("C1", "C2"):
        with pytest.raises(ValueError):
            run_view(CONFIG, "after_round3_frozen", condition)


def test_oracle_repetition_runs_use_the_oracle_top5_and_their_own_run_ids():
    assert REP_RUNS == {"oracle_rep2": {"C2": "01.1", "C3": "01.1"}, "oracle_rep3": {"C2": "01.1", "C3": "01.1"}}
    assert REP_REPETITION == {"oracle_rep2": 2, "oracle_rep3": 3}
    for run in REP_RUNS:
        for condition in ("C2", "C3"):
            view = run_view(CONFIG, run, condition)
            assert view["cases"]["ids"] == ["01.1"] and view["paths"]["frozen_retrieval"] == GDPR["oracle_top5"]
        with pytest.raises(ValueError):
            run_view(CONFIG, run, "C1")
    assert run_id(CONFIG, "oracle_rep2") == "oracle_01.1_rep2"
    assert run_id(CONFIG, "oracle_rep3") == "oracle_01.1_rep3"


def test_oracle_rep3_waits_for_both_conditions_of_rep2(tmp_path):
    config = copy.deepcopy(CONFIG)
    config["paths"]["runs"] = str(tmp_path)
    check_previous_repetition(config, "oracle_rep2")                # rep 2 has no previous check
    for condition in ("C2", "C3"):
        with pytest.raises(ValueError, match="oracle_rep2 is not complete"):
            check_previous_repetition(config, "oracle_rep3")
        case_dir = tmp_path / "oracle_01.1_rep2" / condition / "01.1"
        case_dir.mkdir(parents=True)
        (case_dir / CONFIG["paths"]["validation_file"]).write_text("{}", encoding="utf-8")
    check_previous_repetition(config, "oracle_rep3")


def test_oracle_rep_dirs_take_rep1_from_oracle_c2_and_after_round3_c3():
    rows = [(c, r, rid) for c, r, rid, _ in oracle_rep_dirs(CONFIG)]
    assert rows == [("C2", 1, "oracle_01.1"), ("C2", 2, "oracle_01.1_rep2"), ("C2", 3, "oracle_01.1_rep3"),
                    ("C3", 1, "after_round3_oracle"), ("C3", 2, "oracle_01.1_rep2"), ("C3", 3, "oracle_01.1_rep3")]
