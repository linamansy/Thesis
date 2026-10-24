"""Study 2 development smoke run: Study 1's generator on the 7 GDPR development cases, with the reranked GDPR
retrieval. One condition per call.

What is the same as Study 1 (nothing of it is changed): the harness (bpmngen_harness/run_bpmngen.ts) with
BPMNGen's OpenSourceLLM and qwen3:8b on Ollama (same digest, temperature 0.3, num_ctx 16384, think false), the
knowledge label and layout, the C3 agents v1 (same model, temperature 0), the run folder and log rules. All of it
runs through run_experiment.py's own classes (RunFolder, ExperimentRunner and the setting checks).

What is different: the config view of src/study2_config.py, i.e. the GDPR development cases, the frozen file
data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json (C2 passages, C3 mediation input) and the GDPR passage
titles. The run id is study2_gdpr.smoke_run_id (smoke_gdpr_dev); it starts with "smoke", so every Study 1 analysis
ignores it. Outputs: results/runs/smoke_gdpr_dev/<condition>/<case_id>/ and results/logs/<condition>_smoke_gdpr_dev.jsonl.
The evaluation is a separate step (src/evaluate_gdpr_dev_smoke.py).

Development cases only (docs/C3_V2_DEVELOPMENT.md section 2.1); test cases are never run here.

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m src.run_gdpr_dev_smoke --condition C1
"""

import argparse
import sys

from run_experiment import (BPMNGEN_TYPES, MEDIATION_ROLES, ExperimentRunner, RunInterrupted, bpmngen_file_settings,
                            bpmngen_library_settings, create_llm, ollama_settings, print_summary)
from src.bpmngen_generator import GeneratorSetupError
from src.config import load_config, project_path
from src.logger import RunLogger
from src.run_folder import RunFolder
from src.study2_config import study2_view

REPETITION = 1   # a smoke run is one repetition


def smoke_run_id(config: dict) -> str:
    """The run id of the smoke run; refused unless it starts with the smoke prefix (kept out of Study 1)."""
    run_id = config["study2_gdpr"]["smoke_run_id"]
    prefix = config["evaluation"]["smoke_run_prefix"]
    if not run_id.startswith(prefix) or run_id in config["statistics"]["runs"]:
        raise ValueError(f"study2_gdpr.smoke_run_id {run_id!r} must start with {prefix!r} and not be a study run")
    return run_id


def check_development_only(config: dict) -> None:
    """Refuse any case that is not a GDPR development case (or that is a test case)."""
    cases, development = config["cases"]["ids"], config["study2_gdpr"]["development_ids"]
    not_allowed = [c for c in cases if c not in development or c in config["cases"]["test_ids"]]
    if not_allowed:
        raise ValueError(f"the smoke run may use GDPR development cases only, not {not_allowed}")


def main() -> None:
    config = study2_view(load_config())
    parser = argparse.ArgumentParser(description="Study 2 development smoke run, one condition.")
    parser.add_argument("--condition", required=True, choices=config["conditions"])
    args = parser.parse_args()

    try:
        run_id = smoke_run_id(config)
        check_development_only(config)
        folder = RunFolder(config, run_id, REPETITION,
                           ollama_settings(config) | bpmngen_file_settings(config, run_id)
                           | bpmngen_library_settings(config)
                           | {"study2_frozen_retrieval": config["paths"]["frozen_retrieval"],
                              "study2_passages": config["paths"]["passages"]})
        folder.check_can_start(args.condition)
        shared = {}
        llm = None if config["generator"]["type"] in BPMNGEN_TYPES else create_llm(config, "generator", shared)
        agent_llms = ({role: create_llm(config, role, shared) for role in MEDIATION_ROLES}
                      if args.condition == "C3" else None)
        part = folder.next_part(args.condition)
        logger = RunLogger(project_path(config["paths"]["logs"]), args.condition, run_id, part)
    except (FileExistsError, FileNotFoundError, ValueError, RuntimeError) as e:
        sys.exit(f"Not started: {e}")

    runner = ExperimentRunner(config, args.condition, llm, logger, folder.condition_dir(args.condition), agent_llms,
                              generator_digest=folder.settings.get("generator_digest"))
    if runner.generator_type in BPMNGEN_TYPES:
        try:
            runner.generator.check_setup()
        except (FileNotFoundError, GeneratorSetupError) as e:
            sys.exit(f"Not started: {e}")
    to_run = folder.start_part(args.condition, part, logger.log_path)
    print(f"Study 2 smoke run {run_id} | condition {args.condition} | part {part} | "
          f"frozen retrieval {config['paths']['frozen_retrieval']} | {len(to_run)} to run: {' '.join(to_run)}\n")
    try:
        records = runner.run_all()
    except RunInterrupted as e:
        folder.end_part(args.condition, [], interrupted=str(e))
        sys.exit(f"Run interrupted, {e}\nRun the same command again to continue with the unfinished cases.")
    folder.end_part(args.condition, records)
    print_summary(records)
    print(f"\nOutputs: {runner.output_dir}\nLog:     {logger.log_path}")


if __name__ == "__main__":
    main()
