"""Study 2: the variant 01.1 runs and the oracle diagnostic (one repetition each).

Generator: Study 1's harness (bpmngen_harness/run_bpmngen.ts) with BPMNGen's OpenSourceLLM and qwen3:8b on Ollama,
unchanged. Before any call, the run settings (model digest, Ollama server settings, BPMNGen file hashes and library
versions, agent settings) must equal those of the development smoke run (study2_gdpr.variant_same_as), and the Ollama
version must equal study2_gdpr.ollama_version (0.40.11; the smoke run had 0.40.8); otherwise nothing starts.

The five runs (config.yaml study2_gdpr):
  run      condition  case   passages
  main     C1         01     none ("No domain knowledge provided.")
  main     C2         01.1   frozen top 5 (study2_gdpr.frozen_variants_rerank)
  main     C3         01.1   the same frozen top 5, mediated by C3 v2 (src/orchestrator_v2.py)
  oracle   C2         01.1   oracle top 5 (study2_gdpr.oracle_top5)
  oracle   C3         01.1   the same oracle top 5, mediated by C3 v2
After the mediation fixes (C3 v2 round 3 final, tag c3v2-logic-final), C3 only, C1 and C2 are not rerun:
  after_round3_frozen  C3  01.1   frozen top 5, mediated by C3 v2 (final)
  after_round3_oracle  C3  01.1   oracle top 5, mediated by C3 v2 (final)
Repetitions 2 and 3 of the oracle runs (REP_RUNS; repetition 1 = oracle/C2 and after_round3_oracle/C3), same settings:
  oracle_rep2  C2, C3  01.1   oracle top 5, repetition 2 (run id study2_gdpr.oracle_rep_run_ids)
  oracle_rep3  C2, C3  01.1   oracle top 5, repetition 3; refused until both conditions of oracle_rep2 are complete
The oracle top 5 is the frozen 01.1 top 5 with one rank replaced by the target passage (study2_gdpr.oracle_replace).
It is written once with --build-oracle and committed before the runs.

C1 and C2 use ExperimentRunner unchanged. For C3, VariantRunner only swaps C3 v1's Orchestrator for OrchestratorV2;
the knowledge label, layout and generator are the same. Invalid XML is a result: never retried or repaired.

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m src.run_variant_01_1 --build-oracle
    .venv\\Scripts\\python.exe -m src.run_variant_01_1 --run main --condition C1
    .venv\\Scripts\\python.exe -m src.run_variant_01_1 --report
    .venv\\Scripts\\python.exe -m src.run_variant_01_1 --oracle-reps-report
"""

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

from run_experiment import (BPMNGEN_TYPES, MEDIATION_ROLES, ExperimentRunner, RunInterrupted, bpmngen_file_settings,
                            bpmngen_library_settings, create_llm, ollama_settings, print_summary)
from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.bpmngen_generator import GeneratorSetupError
from src.config import load_config, project_path
from src.logger import RunLogger
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template
from src.run_folder import RunFolder, now
from src.study2_config import study2_view

REPETITION = 1   # one repetition per run
RUNS = {"main": {"C1": "01", "C2": "01.1", "C3": "01.1"},
        "oracle": {"C2": "01.1", "C3": "01.1"},
        "after_round3_frozen": {"C3": "01.1"},
        "after_round3_oracle": {"C3": "01.1"}}
# Repetitions 2 and 3 of the oracle runs (C3 = C3 v2 final); kept apart from RUNS, so --report is unchanged
REP_RUNS = {"oracle_rep2": {"C2": "01.1", "C3": "01.1"},
            "oracle_rep3": {"C2": "01.1", "C3": "01.1"}}
REP_REPETITION = {"oracle_rep2": 2, "oracle_rep3": 3}
# Repetition 1 of the oracle runs, per condition: the run that holds it
ORACLE_REP1 = {"C2": "oracle", "C3": "after_round3_oracle"}
ALL_RUNS = RUNS | REP_RUNS
# The passage file of each run (a key of config.yaml study2_gdpr)
RUN_PASSAGES = {"main": "frozen_variants_rerank", "oracle": "oracle_top5",
                "after_round3_frozen": "frozen_variants_rerank", "after_round3_oracle": "oracle_top5",
                "oracle_rep2": "oracle_top5", "oracle_rep3": "oracle_top5"}
# Settings that must equal the development smoke run's run_info.json. The Ollama version is checked against
# study2_gdpr.ollama_version instead (0.40.11; the smoke run ran on 0.40.8).
SAME_AS_DEV = ["provider", "model", "temperature", "generator", "model_digest", "seed", "num_ctx", "think",
               "max_tokens", "generator_digest", "ollama_server_env", "generator_think_param",
               "bpmngen_file_hashes", "bpmngen_library_versions"]


# ---------- oracle top 5 ----------

def oracle_top5(config: dict) -> dict:
    """The frozen 01.1 top 5 with one rank replaced by the target passage (text from the GDPR Chapters I-V file)."""
    gdpr = config["study2_gdpr"]
    replace = gdpr["oracle_replace"]
    frozen_path = project_path(gdpr["frozen_variants_rerank"])
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))["cases"][replace["case_id"]]["passages"]
    passages = {}
    for line in project_path(gdpr["passages_restricted"]).read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        passages[p["id"]] = p
    target = replace["passage_id"]
    if target in [p["passage_id"] for p in frozen]:
        raise ValueError(f"{target} is already in the frozen top 5")
    top5 = []
    for p in sorted(frozen, key=lambda p: p["rank"]):
        if p["rank"] == replace["rank"]:
            top5.append({"rank": p["rank"], "passage_id": target, "text": passages[target]["text"],
                         "replaces": p["passage_id"]})
        else:
            top5.append({"rank": p["rank"], "passage_id": p["passage_id"], "text": p["text"]})
    return {"note": "ORACLE diagnostic, not a retrieval result: frozen top 5 with one rank replaced by hand",
            "based_on": gdpr["frozen_variants_rerank"], "replaced": replace,
            "cases": {replace["case_id"]: {"passages": top5}}}


def build_oracle_file(config: dict) -> Path:
    """Write study2_gdpr.oracle_top5 once; an existing file is never overwritten."""
    path = project_path(config["study2_gdpr"]["oracle_top5"])
    if path.exists():
        raise FileExistsError(f"{path} already exists; it is never overwritten")
    data = {"created_at": now(), **oracle_top5(config)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------- config view and checks ----------

def run_view(config: dict, run: str, condition: str) -> dict:
    """Study 2 config view for one run and condition: its one case and its passage file."""
    gdpr = config["study2_gdpr"]
    if condition not in ALL_RUNS.get(run, {}):
        raise ValueError(f"no condition {condition!r} in run {run!r} (runs: {ALL_RUNS})")
    case_id = ALL_RUNS[run][condition]
    allowed = gdpr["development_ids"] + gdpr["variant_ids"]
    if case_id not in allowed or case_id in config["cases"]["test_ids"]:
        raise ValueError(f"case {case_id} is not a GDPR development or variant case")
    view = copy.deepcopy(study2_view(config))
    view["cases"]["ids"] = [case_id]
    view["paths"]["frozen_retrieval"] = gdpr[RUN_PASSAGES[run]]
    return view


def run_id(config: dict, run: str) -> str:
    gdpr = config["study2_gdpr"]
    run_ids = ({"main": gdpr["variant_run_id"], "oracle": gdpr["oracle_run_id"]} | gdpr["after_round3_run_ids"]
               | gdpr["oracle_rep_run_ids"])
    if run_ids[run] in config["statistics"]["runs"]:
        raise ValueError(f"run id {run_ids[run]!r} is a Study 1 run")
    return run_ids[run]


def check_same_as_dev(config: dict, settings: dict) -> None:
    """Stop unless every setting in SAME_AS_DEV equals the development smoke run's run_info.json and the Ollama
    version equals study2_gdpr.ollama_version."""
    dev_id = config["study2_gdpr"]["variant_same_as"]
    path = project_path(config["paths"]["runs"]) / dev_id / config["paths"]["run_info_file"]
    dev = json.loads(path.read_text(encoding="utf-8"))
    different = {k: (dev.get(k), settings.get(k)) for k in SAME_AS_DEV if dev.get(k) != settings.get(k)}
    if different:
        raise ValueError(f"settings differ from {dev_id} (theirs vs now): {different}")
    expected = str(config["study2_gdpr"]["ollama_version"])
    if settings.get("ollama_version") != expected:
        raise ValueError(f"ollama_version is {settings.get('ollama_version')!r}, but study2_gdpr.ollama_version "
                         f"fixes {expected!r}")


def check_previous_repetition(config: dict, run: str) -> None:
    """oracle_rep3 starts only when both conditions of oracle_rep2 are complete (all of rep 2 before rep 3)."""
    if REP_REPETITION.get(run) != 3:
        return
    folder = RunFolder(run_view(config, "oracle_rep2", "C2"), run_id(config, "oracle_rep2"), 2)
    unfinished = [c for c in REP_RUNS["oracle_rep2"] if not folder.is_complete(c)]
    if unfinished:
        raise ValueError(f"oracle_rep2 is not complete yet (unfinished: {', '.join(unfinished)})")


# ---------- C3 v2 in the runner ----------

class RunOrchestratorV2(OrchestratorV2):
    """OrchestratorV2 as the runner calls it. Its audit trail is one file per case, so there is no run summary."""

    def save_run_summary(self, run_id: str) -> None:
        pass


class VariantRunner(ExperimentRunner):
    """ExperimentRunner with C3 v2 (OrchestratorV2) in place of C3 v1. C1 and C2 are unchanged."""

    def __init__(self, config: dict, condition: str, logger: RunLogger, output_dir: Path,
                 agent_llms: dict | None = None, bpmngen=None, generator_digest: str | None = None):
        super().__init__(config, condition, None, logger, output_dir, agent_llms, bpmngen=bpmngen,
                         generator_digest=generator_digest)
        if condition == "C3":
            self.orchestrator = RunOrchestratorV2(
                RelevanceAgentV2(agent_llms["relevance"], logger),
                ApplicabilityAgentV2(agent_llms["applicability"], logger, config=config),
                RequirementAgentV2(agent_llms["requirement"], logger),
                self.frozen_cases, self.output_dir / config["paths"]["mediation_dir"],
                load_c3_block_template(config, "c3_block_template_v2"), self.no_knowledge_text)


def run(config: dict, run: str, condition: str) -> None:
    view = run_view(config, run, condition)
    try:
        rid = run_id(config, run)
        settings = (ollama_settings(view) | bpmngen_file_settings(view, rid) | bpmngen_library_settings(view)
                    | {"c3_version": "v2", "frozen_retrieval": view["paths"]["frozen_retrieval"]})
        folder = RunFolder(view, rid, REP_REPETITION.get(run, REPETITION), settings)
        check_same_as_dev(config, folder.settings)
        check_previous_repetition(config, run)
        folder.check_can_start(condition)
        shared = {}
        agent_llms = {role: create_llm(view, role, shared) for role in MEDIATION_ROLES} if condition == "C3" else None
        part = folder.next_part(condition)
        logger = RunLogger(project_path(view["paths"]["logs"]), condition, rid, part)
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as e:
        sys.exit(f"Not started: {e}")

    runner = VariantRunner(view, condition, logger, folder.condition_dir(condition), agent_llms,
                           generator_digest=folder.settings.get("generator_digest"))
    if runner.generator_type in BPMNGEN_TYPES:
        try:
            runner.generator.check_setup()
        except (FileNotFoundError, GeneratorSetupError) as e:
            sys.exit(f"Not started: {e}")
    to_run = folder.start_part(condition, part, logger.log_path)
    print(f"Run {rid} | condition {condition} | part {part} | frozen {view['paths']['frozen_retrieval']} | "
          f"to run: {' '.join(to_run)}\n")
    try:
        records = runner.run_all()
    except RunInterrupted as e:
        folder.end_part(condition, [], interrupted=str(e))
        sys.exit(f"Run interrupted, {e}\nRun the same command again to continue.")
    folder.end_part(condition, records)
    print_summary(records)
    print(f"\nOutputs: {runner.output_dir}\nLog:     {logger.log_path}")


# ---------- report ----------

def target_in_prompt(prompt: str, target_text: str, target_id: str) -> bool:
    """Is the target passage in the generator prompt: its id, or the start of its text (after the title line)?"""
    body = target_text.split("\n", 1)[-1].strip()
    return target_id in prompt or body[:200] in prompt


def report(config: dict, evaluator=None) -> dict:
    """One row per run, from the saved files only (no LLM call). Writes report.md and summary.json."""
    from src.evaluate import Evaluator   # loads the embedding model; only needed here

    gdpr, paths = config["study2_gdpr"], config["paths"]
    variant = json.loads((project_path(paths["cases"]) / "01.1" / "variant.json").read_text(encoding="utf-8"))
    reference = project_path(paths["cases"]) / "01.1" / paths["case_reference_file"]
    target_id = gdpr["oracle_replace"]["passage_id"]
    target_text = json.loads(project_path(gdpr["oracle_top5"]).read_text(encoding="utf-8"))["cases"]["01.1"][
        "passages"][gdpr["oracle_replace"]["rank"] - 1]["text"]
    evaluator = evaluator or Evaluator(config)
    expected_ref_id = "Task_9"   # the expected step's task in the 01.1 reference (variant.json "reference")
    rows = []
    for name, conditions in RUNS.items():
        for condition, case_id in conditions.items():
            view = run_view(config, name, condition)
            case_dir = project_path(paths["runs"]) / run_id(config, name) / condition / case_id
            validation = json.loads((case_dir / paths["validation_file"]).read_text(encoding="utf-8"))
            request = json.loads((case_dir / paths["bpmngen_output_dir"] / paths["bpmngen_request_file"])
                                 .read_text(encoding="utf-8"))
            prompt = request["messages"][-1]["content"]
            frozen = json.loads(project_path(view["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))
            given = ([p["passage_id"] for p in frozen["cases"][case_id]["passages"]] if condition != "C1" else [])
            row = {"run": f"{run_id(config, name)}/{condition}/{case_id}", "passages_given": given,
                   "valid": validation["valid"], "bpmnlint_valid": (validation.get("bpmngen") or {}).get(
                       "bpmnlint_valid"), "errors": validation["errors"],
                   "auto_repairs": (validation.get("bpmngen") or {}).get("auto_repairs"),
                   "target_in_prompt": target_in_prompt(prompt, target_text, target_id)}
            with tempfile.TemporaryDirectory() as work:
                scored, rescued = evaluator.scored_model(validation, case_dir / paths["generated_bpmn_file"],
                                                         Path(work))
                if scored is None:
                    row |= {"expected_step_present": None, "di_stripped": False, "expected_step_match": None}
                else:
                    matched = evaluator.compare(scored, reference)["semantic"]["matched"]
                    match = next((m for m in matched if m["reference_id"] == expected_ref_id), None)
                    row |= {"expected_step_present": match is not None, "di_stripped": rescued,
                            "expected_step_match": match}
            if condition == "C3":
                trail = json.loads((case_dir.parent / paths["mediation_dir"] / f"{case_id}.json")
                                   .read_text(encoding="utf-8"))
                row["c3_passages"] = [{"passage_id": p["passage_id"], "label": p["label"],
                                       "look": (p["applicability"] or {}).get("look"),
                                       "failed_step": p["failed_step"]} for p in trail["passages"]]
                row["c3_block"] = trail["knowledge_block"]
            rows.append(row)

    out_dir = project_path(gdpr["variant_report_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"expected_step": variant["expected_step"], "target_passage": target_id,
               "match_threshold": evaluator.matcher.threshold, "rows": rows}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(markdown(summary), encoding="utf-8")
    return summary


def yes_no(value) -> str:
    return {True: "yes", False: "no", None: "n/a (no scorable model)"}[value]


def markdown(summary: dict) -> str:
    lines = ["# Variant 01.1 and oracle diagnostic", "",
             f"Expected step: \"{summary['expected_step']}\" (01.1 reference Task_9, PROVISIONAL; label match at "
             f"threshold {summary['match_threshold']}). Target passage: {summary['target_passage']}.", "",
             "| run | passages given | XML valid | auto-repairs | Art13-1 in prompt? | expected step present? |",
             "|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        repairs = r["auto_repairs"] or {}
        repairs_text = ", ".join(f"{k}={v}" for k, v in repairs.items()) or "-"
        lines.append(f"| {r['run']} | {', '.join(r['passages_given']) or 'none'} | {yes_no(r['valid'])} | "
                     f"{repairs_text} | {yes_no(r['target_in_prompt'])} | {yes_no(r['expected_step_present'])} |")
    for r in summary["rows"]:
        if "c3_passages" in r:
            lines += ["", f"## {r['run']}", "", "| passage | label | look |", "|---|---|---|"]
            lines += [f"| {p['passage_id']} | {p['label']} | {p['look'] or '-'} |" for p in r["c3_passages"]]
            lines += ["", "C3 block:", "", "```", r["c3_block"].strip(), "```"]
    return "\n".join(lines) + "\n"


# ---------- oracle repetitions report ----------

def oracle_rep_dirs(config: dict) -> list[tuple[str, int, str, Path]]:
    """(condition, repetition, run id, case folder) of the oracle runs, repetitions 1-3, C2 first."""
    runs_dir = project_path(config["paths"]["runs"])
    rows = []
    for condition in ("C2", "C3"):
        for run, repetition in [(ORACLE_REP1[condition], 1)] + list(REP_REPETITION.items()):
            rid = run_id(config, run)
            rows.append((condition, repetition, rid, runs_dir / rid / condition / ALL_RUNS[run][condition]))
    return rows


def oracle_reps_report(config: dict, evaluator=None) -> dict:
    """One row per oracle run and repetition, from the saved files only (no LLM call)."""
    from src.bpmn_graph import BPMNGraph
    from src.evaluate import Evaluator   # loads the embedding model; only needed here

    paths = config["paths"]
    reference = project_path(paths["cases"]) / "01.1" / paths["case_reference_file"]
    expected_ref_id = "Task_9"   # the expected step's task in the 01.1 reference
    expected_label = BPMNGraph.from_file(reference).task_labels()[expected_ref_id]
    evaluator = evaluator or Evaluator(config)
    rows, block_rep1 = [], None
    for condition, repetition, rid, case_dir in oracle_rep_dirs(config):
        validation = json.loads((case_dir / paths["validation_file"]).read_text(encoding="utf-8"))
        row = {"run": f"{rid}/{condition}/01.1", "condition": condition, "repetition": repetition,
               "valid": validation["valid"], "errors": validation["errors"]}
        with tempfile.TemporaryDirectory() as work:
            scored, rescued = evaluator.scored_model(validation, case_dir / paths["generated_bpmn_file"], Path(work))
            row |= {"scorable": scored is not None, "di_stripped": rescued, "expected_step_present": None,
                    "closest_label": None, "closest_similarity": None}
            if scored is not None:
                matched = evaluator.compare(scored, reference)["semantic"]["matched"]
                row["expected_step_present"] = any(m["reference_id"] == expected_ref_id for m in matched)
                labels = list(BPMNGraph.from_file(scored).task_labels().values())
                if labels:   # the generated task closest in meaning to the expected step
                    similarity = evaluator.matcher.similarity_matrix(labels, [expected_label])[:, 0]
                    best = int(similarity.argmax())
                    row |= {"closest_label": labels[best], "closest_similarity": round(float(similarity[best]), 4)}
        if condition == "C3":
            block = (case_dir / paths["knowledge_block_file"]).read_text(encoding="utf-8")
            block_rep1 = block if repetition == 1 else block_rep1
            row["c3_block_identical_to_rep1"] = block == block_rep1
        rows.append(row)

    out_dir = project_path(config["study2_gdpr"]["oracle_reps_report"])
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"expected_step": expected_label, "match_threshold": evaluator.matcher.threshold, "rows": rows}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(oracle_reps_markdown(summary), encoding="utf-8")
    return summary


def oracle_reps_markdown(summary: dict) -> str:
    lines = ["# Oracle runs on 01.1, repetitions 1-3", "",
             f"Expected step: \"{summary['expected_step']}\" (01.1 reference Task_9, PROVISIONAL; label match at "
             f"threshold {summary['match_threshold']}).", "",
             "| run | rep | XML valid | scorable (di_stripped rule) | expected step present | closest task label + "
             "similarity | C3 block identical to rep 1? |", "|---|---|---|---|---|---|---|"]
    for r in summary["rows"]:
        scorable = "no" if not r["scorable"] else "yes (di_stripped)" if r["di_stripped"] else "yes"
        closest = f"\"{r['closest_label']}\" ({r['closest_similarity']:.2f})" if r["closest_label"] else "n/a"
        block = yes_no(r["c3_block_identical_to_rep1"]) if "c3_block_identical_to_rep1" in r else "-"
        lines.append(f"| {r['run']} | {r['repetition']} | {yes_no(r['valid'])} | {scorable} | "
                     f"{yes_no(r['expected_step_present'])} | {closest} | {block} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="Variant 01.1 runs and the oracle diagnostic.")
    parser.add_argument("--build-oracle", action="store_true", help="write the oracle top 5 file (once)")
    parser.add_argument("--run", choices=list(ALL_RUNS))
    parser.add_argument("--condition", choices=config["conditions"])
    parser.add_argument("--report", action="store_true", help="write the report from the saved runs")
    parser.add_argument("--oracle-reps-report", action="store_true", help="table of the oracle runs, reps 1-3")
    args = parser.parse_args()
    if args.build_oracle:
        print(f"Written: {build_oracle_file(config)}")
    elif args.report:
        print(markdown(report(config)))
    elif args.oracle_reps_report:
        print(oracle_reps_markdown(oracle_reps_report(config)))
    elif args.run and args.condition:
        run(config, args.run, args.condition)
    else:
        parser.error("use --build-oracle, --run with --condition, --report or --oracle-reps-report")


if __name__ == "__main__":
    main()
