"""Tests for BPMNGenGenerator and the bpmngen path of ExperimentRunner.

No Node.js, BPMNGen or Ollama: a fake "runner" replaces subprocess.run and writes the files the
real harness (bpmngen_harness/run_bpmngen.ts) would write.
"""

import json
import subprocess
from pathlib import Path

import pytest

from run_experiment import ExperimentRunner
from src.bpmngen_generator import BPMNGenGenerator, context_limit_hit
from src.config import load_config
from src.generator import NO_KNOWLEDGE_TEXT
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

from bpmn_helpers import make_bpmn, sequential_model

LABEL = "[Domain information (it may or may not apply to this process):]"


def bpmngen_config():
    config = load_config()
    config["generator"] = {"type": "bpmngen", "bpmngen_server_dir": "/bpmngen/server", "harness": "h.ts",
                           "model": "qwen3:8b", "ollama_base_url": "http://ollama:11434",
                           "knowledge_label": LABEL, "timeout_seconds": 5, "npx_command": "npx",
                           "think_param": False}
    return config


def fake_harness(done_reason="stop", fits=True, returncode=0, stderr="", calls=None, thinking="", cut_off=False,
                 think_tags=0):
    """A stand-in for the harness process: writes the files the real harness writes.

    thinking: text the model "thought" (Ollama's separate field); cut_off: the harness stopped a runaway answer.
    """

    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        if returncode != 0:
            return subprocess.CompletedProcess(command, returncode, "", stderr)
        args = dict(zip(command[5::2], command[6::2]))  # "--flag value" pairs after the script path
        out = Path(args["--out"])
        out.mkdir(parents=True, exist_ok=True)
        knowledge = Path(args["--knowledge"]).read_text(encoding="utf-8").strip()
        description = Path(args["--description"]).read_text(encoding="utf-8").strip()
        user = f"{description}\n\n{args['--label']}\n{knowledge}\n\n/no_think"
        think = {"false": False, "true": True}.get(args.get("--think"))
        (out / "ollama_request.json").write_text(json.dumps(
            {"model": args["--model"], "messages": [{"role": "system", "content": "SYS"},
                                                    {"role": "user", "content": user}],
             "options": {"num_ctx": 16384, "temperature": 0.3}, "think": think}), encoding="utf-8")
        (out / "raw_model_output.txt").write_text("<xml/>", encoding="utf-8")
        (out / "raw_thinking.txt").write_text(thinking, encoding="utf-8")
        if not cut_off:
            (out / "generated.bpmn").write_text(make_bpmn(*sequential_model()), encoding="utf-8")
        meta = {"ollama_model_reported": "qwen3:8b", "temperature": 0.3, "num_ctx": 16384, "think_param": think,
                "prompt_tokens": 2100, "output_tokens": 16385 if cut_off else 900,
                "done_reason": "cut_off_by_harness" if cut_off else done_reason,
                "fits_context": False if cut_off else fits, "cut_off_by_harness": cut_off,
                "raw_has_think_block": bool(thinking) or think_tags > 0, "think_tags_in_answer": think_tags,
                "thinking_chars": len(thinking),
                "auto_repairs": {"auto_flows_added": 0, "auto_links_added": 1, "first_task_inserted": False},
                "valid": not cut_off, "seconds": 12.5}
        (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, json.dumps(meta), "")

    return run


def make_generator(tmp_path, runner):
    return BPMNGenGenerator(bpmngen_config(), RunLogger(tmp_path / "logs", "C2", "test"), runner=runner)


def description_file(tmp_path):
    path = tmp_path / "description.txt"
    path.write_text("The clerk checks the order.", encoding="utf-8")
    return path


def test_command_passes_knowledge_label_and_model(tmp_path):
    calls = []
    generator = make_generator(tmp_path, fake_harness(calls=calls))
    generator.run("19", description_file(tmp_path), "[CRD-Art8-3] passage text", tmp_path / "case")

    command, kwargs = calls[0]
    assert command[:5] == ["npx", "ts-node", "--cwdMode", "--transpile-only", str(generator.harness)]
    assert command[command.index("--label") + 1] == LABEL
    assert command[command.index("--model") + 1] == "qwen3:8b"
    assert kwargs["cwd"] == str(generator.server_dir)  # BPMNGen reads its prompt files from there
    assert generator.server_dir.parts[-2:] == ("bpmngen", "server")
    assert (tmp_path / "case" / "knowledge_block.txt").read_text(encoding="utf-8") == "[CRD-Art8-3] passage text\n"


def test_outputs_are_copied_and_logged(tmp_path):
    generator = make_generator(tmp_path, fake_harness())
    meta = generator.run("19", description_file(tmp_path), "block", tmp_path / "case")

    assert meta["done_reason"] == "stop"
    assert (tmp_path / "case" / "generated.bpmn").exists()
    record = json.loads(generator.logger.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["component"] == "BPMNGenGenerator" and record["finish_reason"] == "stop"
    assert record["temperature"] == 0.3 and record["raw_output"] == "<xml/>"
    assert LABEL in record["prompt"] and "block" in record["prompt"]  # the exact prompt is logged


DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"


def test_log_records_carry_the_model_digest(tmp_path):
    generator = BPMNGenGenerator(bpmngen_config(), RunLogger(tmp_path / "logs", "C2", "test"),
                                 runner=fake_harness(), model_digest=DIGEST)
    generator.run("19", description_file(tmp_path), "block", tmp_path / "case")

    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)
    generator.runner = timed_out
    generator.run("21", description_file(tmp_path), "block", tmp_path / "case21")

    records = [json.loads(line) for line in generator.logger.log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["model_digest"] for r in records] == [DIGEST, DIGEST]   # normal answer and timeout


def test_experiment_runner_gives_the_checked_digest_to_the_generator(tmp_path):
    runner = ExperimentRunner(bpmngen_config(), "C1", None, RunLogger(tmp_path / "logs", "C1", "test"),
                              tmp_path / "run" / "C1", generator_digest=DIGEST)
    assert runner.generator.model_digest == DIGEST


def test_readme_manual_command_turns_thinking_off():
    from src.config import PROJECT_ROOT
    readme = (PROJECT_ROOT / "bpmngen_harness" / "README.md").read_text(encoding="utf-8")
    commands = [line for line in readme.splitlines() if line.startswith("npx ts-node") and "run_bpmngen.ts" in line]
    assert commands and all("--think false" in c for c in commands)


@pytest.mark.parametrize("stderr", ["TypeError: fetch failed", "connect ECONNREFUSED 127.0.0.1:11434",
                                    "Ollama error 404: model not found"])
def test_ollama_problems_stop_the_run(tmp_path, stderr):
    generator = make_generator(tmp_path, fake_harness(returncode=1, stderr=stderr))
    with pytest.raises(LLMUnavailableError):
        generator.run("19", description_file(tmp_path), "block", tmp_path / "case")


def test_other_harness_failures_are_errors(tmp_path):
    generator = make_generator(tmp_path, fake_harness(returncode=1, stderr="SyntaxError in harness"))
    with pytest.raises(RuntimeError, match="exit code 1"):
        generator.run("19", description_file(tmp_path), "block", tmp_path / "case")


def slow(command, **kwargs):
    raise subprocess.TimeoutExpired(command, 5)


def test_timeout_is_returned_not_raised(tmp_path):
    meta = make_generator(tmp_path, slow).run("19", description_file(tmp_path), "block", tmp_path / "case")
    assert meta["timed_out"] is True and meta["valid"] is False


def test_think_false_is_passed_to_the_harness(tmp_path):
    calls = []
    make_generator(tmp_path, fake_harness(calls=calls)).run("19", description_file(tmp_path), "block", tmp_path / "c")
    command = calls[0][0]
    assert command[command.index("--think") + 1] == "false"


# ---------- 2. thinking text is always saved, and flagged if it appears ----------

def test_no_thinking_is_not_flagged(tmp_path):
    runner = make_runner(tmp_path, "C1", fake_harness())
    record = runner.run_case("19")
    assert "thinking_detected" not in record and "warnings" not in record
    assert record["bpmngen"]["think_param"] is False and record["bpmngen"]["thinking_chars"] == 0
    assert (tmp_path / "run" / "C1" / "19" / "bpmngen" / "raw_thinking.txt").exists()   # always saved


def test_thinking_despite_think_false_is_saved_and_flagged(tmp_path):
    thinking = "Okay, let's tackle this BPMN diagram..."
    runner = make_runner(tmp_path, "C1", fake_harness(thinking=thinking))
    record = runner.run_case("19")

    assert record["thinking_detected"] is True and "thinking text despite think=False" in record["warnings"][0]
    assert record["bpmngen"]["raw_has_think_block"] is True and record["bpmngen"]["thinking_chars"] == len(thinking)
    log = json.loads(runner.logger.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert log["parsed_output"]["thinking_detected"] is True
    assert log["parsed_output"]["raw_thinking"] == "Okay, let's tackle this BPMN diagram..."   # saved in the log too
    saved = json.loads((tmp_path / "run" / "C1" / "19" / "validation.json").read_text(encoding="utf-8"))
    assert saved["thinking_detected"] is True


def test_stray_closing_think_tag_in_the_answer_is_flagged(tmp_path):
    """Seen in the smoke test: with think:false qwen3 wrote a draft, then "</think>", then the real XML."""
    runner = make_runner(tmp_path, "C1", fake_harness(think_tags=2))
    record = runner.run_case("19")
    assert record["thinking_detected"] is True and record["bpmngen"]["think_tags_in_answer"] == 2
    assert "2 think tag(s) in the answer" in record["warnings"][0]


# ---------- 3. cut-off answers are failed generations, scored and never retried ----------

def test_harness_cut_off_is_a_finished_failed_generation(tmp_path):
    runner = make_runner(tmp_path, "C1", fake_harness(cut_off=True))
    runner.case_ids = ["19"]
    records = runner.run_all()                                  # no RunInterrupted: the run goes on

    record = records[0]
    assert record["generation_succeeded"] is False and record["valid"] is False
    assert record["context_limit_hit"] is True and record["timed_out"] is False
    assert record["bpmngen"]["done_reason"] == "cut_off_by_harness"
    assert runner.is_finished("19")                             # validation.json written: never retried
    assert not (tmp_path / "run" / "C1" / "19" / "generated.bpmn").exists()


# ---------- 4. timeouts are failed generations; only Ollama problems stop the run ----------

def test_timeout_is_a_finished_failed_generation(tmp_path):
    runner = make_runner(tmp_path, "C1", slow)
    runner.case_ids = ["19"]
    record = runner.run_all()[0]                                # no RunInterrupted

    assert record["generation_succeeded"] is False and record["timed_out"] is True
    assert record["context_limit_hit"] is False and "timed out after 5 s" in record["errors"][0]
    assert runner.is_finished("19")
    log = json.loads(runner.logger.log_path.read_text(encoding="utf-8").splitlines()[0])
    assert log["parsed_output"]["timed_out"] is True            # the timeout is logged as well


def test_timeout_kills_the_whole_process_tree(tmp_path):
    """A parent that starts a child which keeps the output pipe open (like npx -> node on Windows).
    Without killing the tree, waiting for the pipes would last as long as the child (60 s)."""
    import sys
    import time

    from src.bpmngen_generator import run_with_tree_kill

    child = "import time; time.sleep(60)"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(60)"
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_with_tree_kill([sys.executable, "-c", parent], cwd=str(tmp_path), timeout=2)
    assert time.monotonic() - start < 30                        # parent AND child were killed


def test_context_limit_detection():
    assert not context_limit_hit({"done_reason": "stop", "fits_context": True})
    assert context_limit_hit({"done_reason": "length", "fits_context": True})
    assert context_limit_hit({"done_reason": "stop", "fits_context": False})


def make_runner(tmp_path, condition, harness):
    config = bpmngen_config()
    logger = RunLogger(tmp_path / "logs", condition, "test")
    generator = BPMNGenGenerator(config, logger, runner=harness)
    return ExperimentRunner(config, condition, None, logger, tmp_path / "run" / condition, bpmngen=generator)


def test_c1_gets_the_same_layout_with_the_empty_block(tmp_path):
    runner = make_runner(tmp_path, "C1", fake_harness())
    record = runner.run_case("19")

    case_dir = tmp_path / "run" / "C1" / "19"
    assert (case_dir / "knowledge_block.txt").read_text(encoding="utf-8").strip() == NO_KNOWLEDGE_TEXT
    user = json.loads((case_dir / "bpmngen" / "ollama_request.json").read_text(encoding="utf-8"))["messages"][-1]
    assert f"{LABEL}\n{NO_KNOWLEDGE_TEXT}" in user["content"]
    assert record["generation_succeeded"] and record["valid"] and not record["context_limit_hit"]
    assert record["bpmngen"]["auto_repairs"]["auto_links_added"] == 1
    assert json.loads((case_dir / "validation.json").read_text(encoding="utf-8")) == record


def test_c2_block_is_the_frozen_passages(tmp_path):
    runner = make_runner(tmp_path, "C2", fake_harness())
    runner.run_case("19")
    block = (tmp_path / "run" / "C2" / "19" / "knowledge_block.txt").read_text(encoding="utf-8")
    ids = [p["passage_id"] for p in runner.frozen_cases["19"]["passages"]]
    assert all(f"[{i}]" in block for i in ids)


def test_cut_off_answer_is_a_failed_generation(tmp_path):
    runner = make_runner(tmp_path, "C1", fake_harness(done_reason="length"))
    record = runner.run_case("19")
    assert record["generation_succeeded"] is False and record["valid"] is False
    assert record["context_limit_hit"] is True
    assert "cut off" in record["errors"][0]


def test_unreachable_ollama_leaves_the_case_unfinished(tmp_path):
    runner = make_runner(tmp_path, "C1", fake_harness(returncode=1, stderr="fetch failed"))
    with pytest.raises(LLMUnavailableError):
        runner.run_case("19")
    assert not runner.is_finished("19")
