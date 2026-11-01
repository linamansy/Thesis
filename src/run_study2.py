"""Study 2 runner: C1, C2 and C3 for ONE case or variant id, reading the frozen SR retrieval (src/freeze_sr.py).

The three conditions differ only in the knowledge block, as in Study 1:
  C1  "No domain knowledge provided."
  C2  the case's frozen passages (study2_run.frozen_retrieval), verbatim, in rank order
  C3  the same frozen passages, mediated by C3 v2 (OrchestratorV2, current defaults); the ApplicabilityAgentV2 calls
      named in study2_run.think_calls (CheckIfCallV2, SecondLookCallV2, VerifierCallV2) are sent with think: true
All three read the same description file (data/cases/<id>/description.txt). Retrieval is never run here.

Generator: Study 1's harness (bpmngen_harness/run_bpmngen.ts, generator.type bpmngen) through ExperimentRunner, one
generator call per case, no retries; invalid XML is a result. Only the config view differs (src/study2_config.py, with
the Study 2 corpus and the frozen SR file).

Refused before anything runs: a held-out variant id (mediation_test.held_out_variants), a Study 1 run id
(statistics.runs), a generator other than bpmngen, a frozen file whose SHA-256 differs from its manifest or that does
not hold the case, and any condition whose case folder (or, for C3, mediation file) already exists in the run: an
existing run is never overwritten or resumed (use a new --run-id). Once study2_run.reference_run_id is set, every other
run id must have the reference run's settings (SAME_AS_REFERENCE, from its run_info.json) or it does not start.

Outputs, as Study 1: results/runs/<run_id>/run_info.json, results/runs/<run_id>/<condition>/<id>/...,
results/runs/<run_id>/C3/mediation/<id>.json, results/logs/<condition>_<run_id>.jsonl.

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m src.run_study2 --case 01.1 --run-id study2_01.1_rep1
    (optional: --conditions C2,C3; --repetition 2; --fresh: unload the model from Ollama before each condition)
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

from run_experiment import (MEDIATION_ROLES, RunInterrupted, bpmngen_file_settings, bpmngen_library_settings,
                            create_llm, ollama_settings, print_summary)
from src.bpmngen_generator import GeneratorSetupError
from src.config import load_config, project_path
from src.freeze_sr import held_out_ids
from src.logger import RunLogger
from src.run_folder import RunFolder
from src.run_variant_01_1 import VariantRunner
from src.study2_config import study2_view

CONDITIONS = ["C1", "C2", "C3"]
# settings every Study 2 run must share with the reference run (study2_run.reference_run_id)
SAME_AS_REFERENCE = ["ollama_version", "model_digest", "generator_digest", "ollama_server_env", "bpmngen_file_hashes",
                     "bpmngen_library_versions", "think_calls", "frozen_sha256", "c3_version", "fresh"]


# ---------- checks and config view ----------

def check_case(config: dict, case_id: str) -> None:
    if case_id in held_out_ids(config):
        raise ValueError(f"{case_id} is a held-out variant; it is never run")
    if not (project_path(config["paths"]["cases"]) / case_id / config["paths"]["case_description_file"]).exists():
        raise ValueError(f"no case description for {case_id}")


def check_run_id(config: dict, run_id: str) -> None:
    if not run_id or run_id in config["statistics"]["runs"]:
        raise ValueError(f"run id {run_id!r} is empty or a Study 1 run")


def load_frozen(config: dict, case_id: str) -> str:
    """Check the frozen SR file against its manifest and that it holds the case; returns its SHA-256."""
    run = config["study2_run"]
    path, manifest_path = project_path(run["frozen_retrieval"]), project_path(run["frozen_manifest"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = json.loads(manifest_path.read_text(encoding="utf-8"))["sha256"]
    if sha != expected:
        raise RuntimeError(f"{path} differs from its manifest (frozen file changed): {sha} != {expected}")
    if case_id not in json.loads(path.read_text(encoding="utf-8"))["cases"]:
        raise ValueError(f"case {case_id} is not in the frozen file {path}")
    return sha


def check_same_as_reference(config: dict, settings: dict, run_id: str) -> None:
    """Stop unless every setting in SAME_AS_REFERENCE equals the reference run's run_info.json. No check while
    study2_run.reference_run_id is empty, or for the reference run itself (its own folder keeps its settings)."""
    reference = config["study2_run"].get("reference_run_id") or ""
    if not reference or run_id == reference:
        return
    path = project_path(config["paths"]["runs"]) / reference / config["paths"]["run_info_file"]
    if not path.exists():
        raise ValueError(f"reference run {reference!r} has no {path}")
    ref = json.loads(path.read_text(encoding="utf-8"))
    different = {k: (ref.get(k), settings.get(k)) for k in SAME_AS_REFERENCE if ref.get(k) != settings.get(k)}
    if different:
        raise ValueError(f"settings differ from the reference run {reference} (theirs vs now): {different}")


def run_view(config: dict, case_id: str) -> dict:
    """Study 2 config view for one case: the Study 2 corpus and the frozen SR file."""
    view = copy.deepcopy(study2_view(config))
    view["paths"]["passages"] = config["study2_corpus"]["passages"]
    view["paths"]["frozen_retrieval"] = config["study2_run"]["frozen_retrieval"]
    view["cases"]["ids"] = [case_id]
    return view


def check_not_existing(view: dict, folder: RunFolder, conditions: list[str], case_id: str) -> None:
    """Refuse if any condition to run already has a folder (or C3 mediation file) for the case."""
    existing = [folder.condition_dir(c) / case_id for c in conditions if (folder.condition_dir(c) / case_id).exists()]
    if "C3" in conditions:
        trail = folder.condition_dir("C3") / view["paths"]["mediation_dir"] / f"{case_id}.json"
        existing += [trail] if trail.exists() else []
    if existing:
        raise FileExistsError(f"already in run {folder.run_id!r}, never overwritten: {[str(p) for p in existing]}. "
                              f"Choose a new --run-id.")


# ---------- C3 v2 with thinking calls ----------

class Study2Runner(VariantRunner):
    """VariantRunner (C3 = C3 v2) whose named ApplicabilityAgentV2 calls go through think_llm."""

    def __init__(self, config: dict, condition: str, logger: RunLogger, output_dir: Path,
                 agent_llms: dict | None = None, bpmngen=None, generator_digest: str | None = None,
                 think_llm=None):
        super().__init__(config, condition, logger, output_dir, agent_llms, bpmngen, generator_digest)
        if condition == "C3":
            from scripts.oracle_o2 import give_thinking
            give_thinking(self.orchestrator.applicability_agent, list(config["study2_run"]["think_calls"]),
                          think_llm)


def run_condition(view: dict, folder: RunFolder, condition: str, agent_llm=None, think_llm=None,
                  bpmngen_factory=None, fresh: bool = False, ollama_client=None) -> list[dict]:
    """One condition for the view's one case. bpmngen_factory(view, logger) replaces the real generator (tests).
    fresh: unload the model from Ollama first (empty prompt cache); ollama_client replaces the real client (tests)."""
    folder.check_can_start(condition)
    if fresh:
        from scripts.debug_single_case import unload_model
        unload_model(view, client=ollama_client)
    part = folder.next_part(condition)
    logger = RunLogger(project_path(view["paths"]["logs"]), condition, folder.run_id, part)
    llms = {role: agent_llm for role in MEDIATION_ROLES} if condition == "C3" else None
    runner = Study2Runner(view, condition, logger, folder.condition_dir(condition), llms,
                          bpmngen=bpmngen_factory(view, logger) if bpmngen_factory else None,
                          generator_digest=folder.settings.get("generator_digest"), think_llm=think_llm)
    if not bpmngen_factory:
        runner.generator.check_setup()
    folder.start_part(condition, part, logger.log_path)
    try:
        records = runner.run_all()
    except RunInterrupted as e:
        folder.end_part(condition, [], interrupted=str(e))
        raise
    folder.end_part(condition, records)
    return records


def prepare(config: dict, case_id: str, run_id: str, conditions: list[str]) -> tuple[dict, str]:
    """Every check that needs no Ollama; returns (view, frozen SHA-256)."""
    check_case(config, case_id)
    if config["generator"]["type"] != "bpmngen":
        raise ValueError(f"generator.type must be 'bpmngen' (Study 1's harness), not {config['generator']['type']!r}")
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown or not conditions:
        raise ValueError(f"conditions must be from {CONDITIONS}, not {conditions}")
    check_run_id(config, run_id)
    sha = load_frozen(config, case_id)
    return run_view(config, case_id), sha


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Study 2: C1, C2 and C3 for one case or variant id.")
    parser.add_argument("--case", required=True, help="case or variant id, e.g. 01.1")
    parser.add_argument("--run-id", required=True, help="new run id (an existing run is never overwritten)")
    parser.add_argument("--conditions", default=",".join(CONDITIONS), help="comma-separated (default C1,C2,C3)")
    parser.add_argument("--repetition", type=int, default=1, help="repetition number (default 1)")
    parser.add_argument("--fresh", action="store_true",
                        help="unload the model from Ollama before each condition (empty prompt cache); default off")
    args = parser.parse_args(argv)
    config = load_config()
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    try:
        view, frozen_sha = prepare(config, args.case, args.run_id, conditions)
        settings = (ollama_settings(view) | bpmngen_file_settings(view, args.run_id) | bpmngen_library_settings(view)
                    | {"c3_version": config["study2_run"]["c3_version"],
                       "frozen_retrieval": view["paths"]["frozen_retrieval"], "frozen_sha256": frozen_sha,
                       "think_calls": list(config["study2_run"]["think_calls"]), "fresh": args.fresh})
        folder = RunFolder(view, args.run_id, args.repetition, settings)
        check_same_as_reference(config, folder.settings, args.run_id)
        check_not_existing(view, folder, conditions, args.case)
        agent_llm = create_llm(view, "relevance", {}) if "C3" in conditions else None
        think_llm = None
        if "C3" in conditions:
            from scripts.oracle_o2 import thinking_llm
            think_llm = thinking_llm(config)
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as e:
        sys.exit(f"Not started: {e}")
    for condition in conditions:
        print(f"Run {args.run_id} | condition {condition} | case {args.case} | frozen {view['paths']['frozen_retrieval']}")
        try:
            records = run_condition(view, folder, condition, agent_llm, think_llm, fresh=args.fresh)
        except (FileNotFoundError, GeneratorSetupError) as e:
            sys.exit(f"Not started: {e}")
        except RunInterrupted as e:
            sys.exit(f"Run interrupted, {e}\nNothing is overwritten; start again with a new --run-id.")
        print_summary(records)


if __name__ == "__main__":
    main()
