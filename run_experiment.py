"""Entry point: run one experimental condition over all working cases, for one repetition.

Usage (from the project root):
    .venv\\Scripts\\python.exe run_experiment.py --condition C1 --repetition 1
    (optional: --run-id <name>; default "<provider>_rep<repetition>", e.g. "gemini_rep1")
    (optional: --cases 19 03; run only these cases)
Smoke test (one case, kept out of every evaluation summary):
    .venv\\Scripts\\python.exe run_experiment.py --condition C1 --repetition 1 --run-id smoke_c1 --cases 19

The conditions differ ONLY in the knowledge block of the generator prompt:
    C1  "No domain knowledge provided."
    C2  the case's 5 frozen passages from data/retrieval/frozen_retrieval.json, in rank order,
        each as "[passage id] full passage text" (retrieval is never run here)
    C3  the same 5 frozen passages after mediation by the Orchestrator (src/orchestrator.py):
        requirements from Applicable rules + a list of rules with unconfirmed applicability

Everything of one run goes into its own folder (src/run_folder.py); finished cases are never overwritten:
    results/runs/<run_id>/run_info.json
    results/runs/<run_id>/<condition>/<case_id>/generated.json, generated.bpmn, validation.json
    results/runs/<run_id>/C3/mediation/<case_id>.json and run_summary.json
    results/logs/<condition>_<run_id>.jsonl   (every LLM call; _part2, _part3, ... for resumed parts)

Two kinds of failure are treated differently:
  - the generator gives no valid output after its retry (or another error happens): the case is
    recorded as a failed generation; this is a result, the case is finished
  - the API is unreachable after all API retries (LLMUnavailableError, e.g. the daily free-tier
    limit): the run STOPS, the case stays unfinished. Running the same command again later resumes:
    finished cases are skipped, the others are run, logging goes to a new log part.
"""

import argparse
import json
import sys
from pathlib import Path

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.bpmn_builder import BPMNBuilder
from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator, format_passages
from src.llm.anthropic_llm import AnthropicLLM, MissingAPIKeyError
from src.llm.base_llm import LLMClient, LLMUnavailableError
from src.llm.gemini_llm import GeminiLLM, MissingGeminiKeyError
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.orchestrator import Orchestrator
from src.retrieval.passage import load_passages
from src.run_folder import RunFolder, default_run_id
from src.validator import BPMNValidator

MEDIATION_ROLES = ["relevance", "applicability", "requirement"]
PROVIDERS = ["mock", "gemini", "anthropic"]


class RunInterrupted(Exception):
    """The run stopped because the API is unavailable; it can be resumed by running the same command."""

    def __init__(self, case_id: str, error: LLMUnavailableError):
        super().__init__(f"stopped at case {case_id}: {error}")
        self.case_id = case_id


def create_llm(config: dict, role: str = "generator", shared: dict | None = None) -> LLMClient:
    """The LLM client for one role (generator, relevance, applicability, requirement).

    mock:      every role gets its own fixed answer file (paths.mock_<role>_response),
               because the agents expect different kinds of JSON.
    gemini / anthropic: the real API, with the same model and temperature for every role. Pass the
               same `shared` dict for all roles of a run so they share ONE client; then the pause
               between calls (free-tier per-minute limit) counts over all agents together.
    """
    llm_config = config["llm"]
    provider = llm_config["provider"]
    if provider == "mock":
        answer = project_path(config["paths"][f"mock_{role}_response"]).read_text(encoding="utf-8")
        return MockLLM([answer], temperature=llm_config["temperature"])
    if provider not in PROVIDERS:
        raise ValueError(f"llm.provider must be one of {PROVIDERS}, not {provider!r}")
    if shared is not None and provider in shared:
        return shared[provider]
    llm = GeminiLLM.from_config(config) if provider == "gemini" else AnthropicLLM.from_config(config)
    if shared is not None:
        shared[provider] = llm
    return llm


class ExperimentRunner:
    """Runs the generator, builder and validator for every case of one condition."""

    def __init__(self, config: dict, condition: str, llm: LLMClient, logger: RunLogger, output_dir: Path,
                 agent_llms: dict[str, LLMClient] | None = None):
        """output_dir: the condition folder of the run, e.g. results/runs/anthropic_rep1/C1.
        agent_llms: for C3, the LLM client of each mediation role ("relevance", "applicability", "requirement")."""
        paths = config["paths"]
        self.condition = condition
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.description_file = paths["case_description_file"]
        self.output_dir = Path(output_dir)
        self.json_file = paths["generated_json_file"]
        self.bpmn_file = paths["generated_bpmn_file"]
        self.validation_file = paths["validation_file"]
        self.logger = logger
        self.generator = BPMNGenerator(llm, logger)
        self.builder = BPMNBuilder()
        self.validator = BPMNValidator()

        self.frozen_cases = None
        self.orchestrator = None
        if condition in ("C2", "C3"):
            frozen_path = project_path(paths["frozen_retrieval"])
            self.frozen_cases = json.loads(frozen_path.read_text(encoding="utf-8"))["cases"]
        if condition == "C3":
            if agent_llms is None:
                raise ValueError("C3 needs an LLM client for each mediation agent (agent_llms)")
            titles = {p.id: p.title for p in load_passages(project_path(paths["passages"]))}
            self.orchestrator = Orchestrator(
                RelevanceAgent(agent_llms["relevance"], logger),
                ApplicabilityAgent(agent_llms["applicability"], logger),
                RequirementAgent(agent_llms["requirement"], logger),
                self.frozen_cases, titles, self.output_dir / paths["mediation_dir"])

    def knowledge_block(self, case_id: str, description: str) -> str:
        """The only part of the generator prompt that differs between conditions."""
        if self.condition == "C1":
            return NO_KNOWLEDGE_TEXT
        if case_id not in self.frozen_cases:
            raise KeyError(f"case {case_id} is missing from the frozen retrieval file")
        if self.condition == "C2":
            return format_passages(self.frozen_cases[case_id]["passages"])
        if self.condition == "C3":
            return self.orchestrator.mediate_case(case_id, description)["knowledge_block"]
        raise NotImplementedError(f"condition {self.condition} is not built")

    def run_case(self, case_id: str) -> dict:
        """Generate, build and validate one case, and save all outputs."""
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        case_dir = self.output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        json_path, bpmn_path = case_dir / self.json_file, case_dir / self.bpmn_file

        error = "generator returned no valid output after retry (see log file)"
        try:
            process = self.generator.run(case_id=case_id, description=description,
                                         knowledge_block=self.knowledge_block(case_id, description))
        except LLMUnavailableError:
            raise  # API unreachable: no result for this case; validation.json is NOT written
        except Exception as e:  # any other error: recorded as a failed generation
            process, error = None, f"generation failed with {type(e).__name__}: {e}"
        record = {"case_id": case_id, "condition": self.condition, "run_id": self.logger.run_id}

        if process is None:
            record |= {"generation_succeeded": False, "parses": False, "valid": False,
                       "errors": [error], "counts": None}
        else:
            json_path.write_text(json.dumps(process.model_dump(), indent=2), encoding="utf-8")
            self.builder.write(process, bpmn_path)
            record |= {"generation_succeeded": True, **self.validator.validate(bpmn_path)}

        # validation.json is written LAST: its existence marks the case as finished.
        (case_dir / self.validation_file).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def is_finished(self, case_id: str) -> bool:
        return (self.output_dir / case_id / self.validation_file).exists()

    def run_all(self) -> list[dict]:
        """Run every unfinished case; finished cases are skipped and their saved record is used.

        Raises RunInterrupted when the API is unavailable; the cases finished so far are kept.
        """
        records, self.skipped, self.ran = [], [], []
        try:
            for case_id in self.case_ids:
                if self.is_finished(case_id):
                    path = self.output_dir / case_id / self.validation_file
                    records.append(json.loads(path.read_text(encoding="utf-8")))
                    self.skipped.append(case_id)
                    continue
                try:
                    records.append(self.run_case(case_id))
                except LLMUnavailableError as e:
                    raise RunInterrupted(case_id, e) from e
                self.ran.append(case_id)
        finally:
            if self.orchestrator:
                self.orchestrator.save_run_summary(self.logger.run_id)
        return records


def print_summary(records: list[dict]) -> None:
    print(f"{'case':<6}{'generated':>11}{'valid':>7}{'tasks':>7}{'gateways':>10}  errors")
    for r in records:
        counts = r["counts"] or {}
        print(f"{r['case_id']:<6}{str(r['generation_succeeded']):>11}{str(r['valid']):>7}"
              f"{counts.get('tasks', '-'):>7}{counts.get('gateways', '-'):>10}  {len(r['errors'])}")


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="Run one experimental condition for one repetition.")
    parser.add_argument("--condition", required=True, choices=config["conditions"])
    parser.add_argument("--repetition", required=True, type=int,
                        help=f"1 to {config['experiment']['repetitions']}")
    parser.add_argument("--run-id", default=None,
                        help="default: <provider>_rep<repetition>. For test runs use an id starting with "
                             f"'{config['evaluation']['smoke_run_prefix']}' (excluded from evaluation summaries)")
    parser.add_argument("--cases", nargs="+", default=None,
                        help="run only these case ids, e.g. --cases 19; default: all cases in config.yaml")
    args = parser.parse_args()
    if args.cases:
        unknown = [c for c in args.cases if c not in config["cases"]["ids"]]
        if unknown:
            sys.exit(f"Not started: unknown case id(s) {unknown}; known: {' '.join(config['cases']['ids'])}")
        args.cases = [c for c in config["cases"]["ids"] if c in args.cases]  # config order, no duplicates

    run_id = args.run_id or default_run_id(config, args.repetition)
    try:
        folder = RunFolder(config, run_id, args.repetition)
        folder.check_can_start(args.condition)  # stop before any LLM call if this would overwrite something
        if args.run_id is None:
            folder.check_previous_repetition_complete(config["conditions"])
        shared = {}
        llm = create_llm(config, "generator", shared)
        agent_llms = ({role: create_llm(config, role, shared) for role in MEDIATION_ROLES}
                      if args.condition == "C3" else None)
        part = folder.next_part(args.condition)
        logger = RunLogger(project_path(config["paths"]["logs"]), args.condition, run_id, part)
    except (FileExistsError, ValueError, MissingAPIKeyError, MissingGeminiKeyError) as e:
        sys.exit(f"Not started: {e}")

    to_run = folder.start_part(args.condition, part, logger.log_path, args.cases)
    runner = ExperimentRunner(config, args.condition, llm, logger, folder.condition_dir(args.condition), agent_llms)
    if args.cases:
        runner.case_ids = args.cases
    print(f"Run {run_id} (repetition {args.repetition}) | condition {args.condition} | part {part} | "
          f"provider {config['llm']['provider']} | model {llm.model} (temperature {llm.temperature})")
    print(f"{len(runner.case_ids) - len(to_run)} selected case(s) already finished and skipped; "
          f"{len(to_run)} to run: {' '.join(to_run)}\n")
    try:
        records = runner.run_all()
    except RunInterrupted as e:
        folder.end_part(args.condition, [], interrupted=str(e))
        sys.exit(f"Run interrupted, {e}\nFinished in this part: {' '.join(runner.ran) or 'none'}. "
                 f"Run the same command again later to continue with the unfinished cases.")
    folder.end_part(args.condition, records)

    print_summary(records)
    print(f"\nOutputs: {runner.output_dir}")
    print(f"Log:     {logger.log_path}")


if __name__ == "__main__":
    main()
