"""Tests for scripts/run_all_dev.py (step order, resume, log-and-continue, oracle set) and scripts/summarise_all_dev.py
(table and details). No LLM: the retrieval and mediation steps are replaced by fakes that write the files the real steps
write; the summary reads synthetic run folders.
"""

import json

import pytest

from scripts import compare_ceiling, run_all_dev, summarise_all_dev
from scripts.run_all_dev import AllDevRunner, oracle_ids
from src.config import load_config, project_path


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def item(id_, kind, status, quotes=(), cause=None, verifier=None, **extra):
    return {"id": id_, "kind": kind, "text": f"text {id_}", "status": status, "quotes_canonical": list(quotes),
            "downgrade_cause": cause, "verifier": verifier, **extra}


def record(pid, label, requirement=None, conditions=(), cause="cause"):
    return {"passage_id": pid, "label": label, "label_cause": cause, "failed_step": None, "error": None,
            "requirement": requirement, "applicability": {"conditions": list(conditions), "role_facts": [],
                                                          "exceptions": []}}


def fake_rag(run_dir, ids):
    write_json(run_dir / "04_merged_top5.json", {"passages": [{"passage_id": i} for i in ids]})
    (run_dir / "summary.txt").write_text("done", encoding="utf-8")


def fake_med(run_dir, records):
    write_json(run_dir / "09_audit_trail_full.json", records)
    (run_dir / "summary.txt").write_text("done", encoding="utf-8")


class FakeRunner(AllDevRunner):
    """AllDevRunner without Ollama: retrieval and mediation write fake folders and record what they were given."""

    def __init__(self, config, fail_retrieval=False):
        self.config, self.fresh, self.think_calls, self.groq_model = config, False, [], None
        self.groq_json, self.oracle_label = "schema", None
        self.messages, self.calls = [], []
        self.log = self.messages.append
        self.corpus_ids = ["GDPR-Art13-1", "GDPR-Art13-2-a", "GDPR-Art5-1-a", "GDPR-Art13-3"]
        self.fail_retrieval = fail_retrieval

    def retrieval(self, variant, run_dir):
        self.calls.append(("retrieval", variant, run_dir.name))
        if self.fail_retrieval:
            run_dir.mkdir(parents=True)
            raise RuntimeError("Ollama stopped")
        fake_rag(run_dir, ["GDPR-Art5-1-a", "GDPR-Art13-1"])

    def mediation(self, variant, run_dir, label, ids, source):
        self.calls.append(("mediation", label, run_dir.name, tuple(ids)))
        fake_med(run_dir, [record(ids[0], "Indeterminate")])


def case_dir(config, variant="01.1"):
    return project_path(config["paths"]["runs"]).parent / "debug" / variant


def test_oracle_is_the_target_then_the_rest_of_its_article_in_corpus_order():
    corpus = ["GDPR-Art13-1", "GDPR-Art13-2-a", "GDPR-Art5-1-a", "GDPR-Art13-3", "GDPR-Art130-1"]
    assert oracle_ids("GDPR-Art13-2-a", corpus) == ["GDPR-Art13-2-a", "GDPR-Art13-1", "GDPR-Art13-3"]


def test_one_run_is_retrieval_then_mediation_on_its_own_set_then_oracle():
    config = load_config()
    runner = FakeRunner(config)
    runner.run_variant("01.1", 1)
    assert runner.calls == [("retrieval", "01.1", "alldev_rag_run_1"),
                            ("mediation", "alldev", "med_alldev_run_1", ("GDPR-Art5-1-a", "GDPR-Art13-1")),
                            ("mediation", "alldev_oracle", "med_alldev_oracle_run_1",
                             ("GDPR-Art13-1", "GDPR-Art13-2-a", "GDPR-Art13-3"))]


def test_a_finished_step_is_skipped_on_resume():
    config = load_config()
    FakeRunner(config).run_variant("01.1", 2)
    again = FakeRunner(config)
    again.run_variant("01.1", 2)
    assert again.calls == [] and sum("skip" in m for m in again.messages) == 3


def test_a_failure_is_logged_the_run_goes_on_and_the_folder_is_kept_on_resume():
    config = load_config()
    failing = FakeRunner(config, fail_retrieval=True)
    failing.run_variant("01.1", 3)
    assert any(m.startswith("FAILED 01.1 run 3 retrieval") and "Ollama stopped" in m for m in failing.messages)
    assert "skip 01.1 run 3 mediation: retrieval not done" in failing.messages
    assert [c[0:2] for c in failing.calls] == [("retrieval", "01.1"), ("mediation", "alldev_oracle")]
    resumed = FakeRunner(config)
    resumed.run_variant("01.1", 3)                       # the stopped folder is moved, not deleted
    moved = list((case_dir(config) / "_incomplete").glob("alldev_rag_run_3_*"))
    assert len(moved) == 1 and [c[1] for c in resumed.calls] == ["01.1", "alldev"]


def test_summary_table_and_details():
    config = load_config()
    variant, target = "06.1", "CRD-Art13-1"
    d = case_dir(config, variant)
    good = record(target, "Applicable", {"requirement": "The shop refunds within 14 days.", "requirement_invalid": False})
    stuck = record(target, "Indeterminate", conditions=[
        item("R1", "role", "confirmed"),
        item("C1", "situation", "not_stated", ["The customer sends a bill"], "verifier rejected",
             {"reason": "a bill is not a payment"}, first_look_status="not_stated"),
        item("C2", "situation", "not_stated")])
    for n, (oracle, full, retrieved) in enumerate([(good, good, True), (good, stuck, True), (stuck, None, False)], 1):
        fake_rag(d / f"alldev_rag_run_{n}", [target] if retrieved else ["CRD-Art8-1"])
        fake_med(d / f"med_alldev_oracle_run_{n}", [oracle])
        fake_med(d / f"med_alldev_run_{n}", [full] if full else [record("CRD-Art8-1", "Irrelevant")])
    text = summarise_all_dev.summarise(config, [variant], 3)
    row = next(line for line in text.splitlines() if line.startswith(variant))
    assert "2/3" in row and "2/3 (A A I)" in row and "1/3 (A I -)" in row and "The shop refunds within 14 days." in row
    assert "06.1 CRD-Art13-1 oracle 3: Indeterminate (I)" in text and "full run 2: Indeterminate" in text
    assert 'quotes: ["The customer sends a bill"]' in text and "verifier: a bill is not a payment" in text
    assert "failing stage: verifier (second look)" in text and "failing stage: first look: not_stated" in text
    assert "full run 3" not in text                       # not retrieved: nothing to detail


def test_summary_marks_missing_runs():
    config = load_config()
    text = summarise_all_dev.summarise(config, ["45.1"], 3)
    row = next(line for line in text.splitlines() if line.startswith("45.1"))
    assert "0/3 (? ? ?)" in row and row.split()[2] == "0/3"


def test_variant_list():
    assert run_all_dev.VARIANTS == ("01.1", "01.2", "06.1", "11.1", "13.1", "17.1", "19.1", "45.1")


def test_ceiling_runs_only_the_oracle_under_its_own_label():
    config = load_config()
    runner = FakeRunner(config)
    runner.groq_model = "qwen/qwen3.8-27b"
    runner.run_variant("01.1", 4)
    assert runner.calls == [("mediation", "ceiling_qwen3.8-27b", "med_ceiling_qwen3.8-27b_run_4",
                             ("GDPR-Art13-1", "GDPR-Art13-2-a", "GDPR-Art13-3"))]


def test_oracle_label_runs_only_the_oracle_under_that_label():
    config = load_config()
    runner = FakeRunner(config)
    runner.oracle_label = "round1"
    runner.run_variant("01.1", 4)
    assert runner.calls == [("mediation", "round1", "med_round1_run_4",
                             ("GDPR-Art13-1", "GDPR-Art13-2-a", "GDPR-Art13-3"))]
    with pytest.raises(SystemExit):
        run_all_dev.main(["--oracle-label", "alldev_oracle"])          # never the old folders' name
    with pytest.raises(SystemExit):
        run_all_dev.main(["--oracle-label", "round1", "--groq-model", "qwen/qwen3.8-27b"])


def test_ablation_options_need_an_oracle_label_and_reach_the_runner(monkeypatch):
    with pytest.raises(SystemExit):
        run_all_dev.main(["--no-d5"])                                   # never into the alldev folders
    seen = []

    class Recorder:
        def __init__(self, *args):
            seen.append(args[-1])

        def run_variant(self, variant, n):
            pass

    monkeypatch.setattr(run_all_dev, "AllDevRunner", Recorder)
    monkeypatch.setattr(run_all_dev, "make_log", lambda path: lambda message: None)
    run_all_dev.main(["--oracle-label", "abl_noD5", "--no-d5", "--runs", "1"])
    run_all_dev.main(["--oracle-label", "abl_noD5_noD4b", "--no-d5", "--no-d4b", "--runs", "1"])
    run_all_dev.main(["--oracle-label", "round9", "--runs", "1"])
    run_all_dev.main(["--oracle-label", "round9b", "--d4b", "--runs", "1"])
    assert seen == [{"case_events": False}, {"case_events": False}, {}, {"sub_rules": True}]   # D4b off by default
    with pytest.raises(SystemExit):
        run_all_dev.main(["--d4b"])
    with pytest.raises(SystemExit):
        run_all_dev.main(["--oracle-label", "x", "--d4b", "--no-d4b"])


def test_ceiling_refuses_the_silver_model_and_ollama_options():
    config = load_config()
    with pytest.raises(ValueError, match="silver"):
        run_all_dev.groq_llm(config, config["silver"]["model"])
    with pytest.raises(SystemExit):
        run_all_dev.main(["--groq-model", "qwen/qwen3.8-27b", "--fresh"])


def test_ceiling_client_is_groq_with_json_schema_and_config_unchanged(monkeypatch):
    from src.llm.groq_llm import GroqLLM
    from src.study2_config import study2_view
    monkeypatch.setenv("GROQ_API_KEY", "test-key")   # never sent: no request is made
    config = load_config()
    view = study2_view(run_all_dev.ceiling_config(config, "qwen/qwen3.8-27b"))
    assert view["c3_agents_llm"]["provider"] == "groq"
    llm = GroqLLM.from_agent_config(view)
    assert llm.model == "qwen/qwen3.8-27b" and llm.json_schema and llm.accepts_format_schema
    assert (llm.temperature, llm.seed, llm.max_tokens) == (0, config["llm"]["seed"], config["llm"]["max_tokens"])
    assert config["c3_agents_llm"]["provider"] == "ollama" and "json_schema" not in config["c3_agents_llm"]["groq"]
    assert llm.cache_dir.parts[-2:] == ("_groq_cache", "qwen__qwen3.8-27b")


def test_ceiling_comparison_report():
    config = load_config()
    variant, target = "19.1", "ECD-Art11-1"
    d = case_dir(config, variant)
    fake_med(d / "med_alldev_oracle_run_5", [record(target, "Not applicable", conditions=[
        item("C1", "situation", "contradicted", ["We ship"], verifier={"reason": "shipping is not ordering"})])])
    fake_med(d / "med_ceiling_qwen3.8-27b_run_5", [record(target, "Applicable", {"requirement": "Acknowledge.",
                                                                               "requirement_invalid": False},
                                                          conditions=[item("C1", "situation", "confirmed", ["Orders"])])])
    text = compare_ceiling.compare(config, "qwen/qwen3.8-27b", [variant, "45.1"], 5)
    assert next(l for l in text.splitlines() if l.startswith("19.1")).split()[2:4] == ["N", "A"]
    assert "C1  situation  contradicted -> confirmed" in text and "requirement strong: Acknowledge." in text
    assert 'quotes qwen:     ["We ship"]' in text and "verifier qwen:   shipping is not ordering" in text
    assert "45.1 " in text and "run missing" in text


def test_ceiling_json_object_option(monkeypatch):
    from src.llm.groq_llm import GroqLLM
    from src.study2_config import study2_view
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert run_all_dev.ceiling_label("qwen/qwen3.8-27b", "object") == "ceiling_qwen3.8-27b_jsonobject"
    llm = GroqLLM.from_agent_config(study2_view(run_all_dev.ceiling_config(load_config(), "qwen/qwen3.8-27b", "object")))
    assert llm.json_mode and not llm.json_schema and not llm.accepts_format_schema
    assert llm.request_body("x")["response_format"] == {"type": "json_object"}


def test_design_round_report():
    from scripts import compare_round
    config = load_config()
    # 01.1: target Applicable (conditional) with requirement -> regression rule PASS; another passage Applicable too
    d = case_dir(config, "01.1")
    fake_med(d / "med_alldev_oracle_run_6", [record("GDPR-Art13-1", "Applicable",
                                                    {"requirement": "Tell.", "requirement_invalid": False})])
    target = record("GDPR-Art13-1", "Applicable (conditional)", {"requirement": "When asked, tell.",
                                                                 "requirement_invalid": False},
                    conditions=[item("C1", "situation", "not_stated", item_kind="case_event", logic="all", group="G1")])
    target["resolution"] = {"units": [{"id": "C1", "logic": "one", "status": "not_stated", "case_event": True,
                                       "items": ["C1"]}], "case_events": [{"id": "C1", "text": "the customer asks"}]}
    other = record("GDPR-Art13-3", "Applicable", {"requirement": "Inform again.", "requirement_invalid": False})
    fake_med(d / "med_round9_run_6", [target, other])
    # 17.1: main rule Indeterminate, a sub-rule (special case) Not applicable -> listed as still failing, with items
    d = case_dir(config, "17.1")
    fake_med(d / "med_alldev_oracle_run_6", [record("CRD-Art14-1", "Indeterminate")])
    stuck = record("CRD-Art14-1", "Indeterminate", conditions=[
        item("S1", "scope", "not_stated", cause="verifier rejected", verifier={"reason": "not explicit"})])
    stuck["applicability"]["sub_rules"] = [{"id": "K1", "clause": "In the case of", "label": "Not applicable",
                                            "label_cause": "an IF item is contradicted", "failed_step": None,
                                            "conditions": [item("C1", "situation", "contradicted", ["No visits"])],
                                            "role_facts": [], "exceptions": []}]
    fake_med(d / "med_round9_run_6", [stuck])
    text = compare_round.compare(config, "round9", ["01.1", "17.1", "45.1"], 6)
    assert "PASS (AC)" in text
    rows = {v: next(l for l in text.splitlines() if l.startswith(v)) for v in ("01.1", "17.1", "45.1")}   # table
    assert rows["01.1"].split()[2:5] == ["A", "AC", "D5"]
    assert rows["17.1"].split()[2:5] == ["I", "I", "[K1:N]"] and "D4b" in rows["17.1"]
    assert "17.1 CRD-Art14-1: I [K1:N]" in text and "verifier: not explicit" in text
    assert "sub-rule K1 ('In the case of'): Not applicable" in text and 'quotes: ["No visits"]' in text
    assert "01.1 GDPR-Art13-1 (target) main: Applicable (conditional) (AC)" in text
    assert "    case events: C1: the customer asks" in text
    assert "01.1 GDPR-Art13-3 main: Applicable (A)" in text and "requirement: Inform again." in text
