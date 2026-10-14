"""Entry point: run one experimental condition over all working cases.

Usage (from the project root):
    .venv\\Scripts\\python.exe run_experiment.py --condition C1

The conditions differ ONLY in the knowledge block of the generator prompt:
    C1  "No domain knowledge provided."
    C2  the case's 5 frozen passages from data/retrieval/frozen_retrieval.json, in rank order,
        each as "[passage id] full passage text" (retrieval is never run here)
    C3  the same 5 frozen passages after mediation by the Orchestrator (src/orchestrator.py):
        requirements from Applicable rules + a list of rules with unconfirmed applicability

For every case it saves, in results/<condition>/<case_id>/:
    generated.json   the process structure returned by the generator
    generated.bpmn   the BPMN XML built from it
    validation.json  the result of the validity checks
C3 also saves results/C3/mediation/<case_id>.json and results/C3/mediation/run_summary.json.
A case where the generator fails is recorded as a failed generation, never skipped.
"""

import argparse
import json

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.bpmn_builder import BPMNBuilder
from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator, format_passages
from src.llm.base_llm import LLMClient
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.orchestrator import Orchestrator
from src.retrieval.passage import load_passages
from src.validator import BPMNValidator

MEDIATION_ROLES = ["relevance", "applicability", "requirement"]


def create_llm(config: dict, role: str = "generator") -> LLMClient:
    """The LLM client for one role (generator, relevance, applicability, requirement).

    With the mock provider every role gets its own fixed answer file (paths.mock_<role>_response),
    because the agents expect different kinds of JSON.
    """
    llm_config = config["llm"]
    if llm_config["provider"] == "mock":
        answer = project_path(config["paths"][f"mock_{role}_response"]).read_text(encoding="utf-8")
        return MockLLM([answer], temperature=llm_config["temperature"])
    raise NotImplementedError(f"LLM provider {llm_config['provider']!r} is not available yet")


class ExperimentRunner:
    """Runs the generator, builder and validator for every case of one condition."""

    def __init__(self, config: dict, condition: str, llm: LLMClient, logger: RunLogger,
                 agent_llms: dict[str, LLMClient] | None = None):
        """agent_llms: for C3, the LLM client of each mediation role ("relevance", "applicability", "requirement")."""
        paths = config["paths"]
        self.condition = condition
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.description_file = paths["case_description_file"]
        self.output_dir = project_path(paths["results"]) / condition
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
                self.frozen_cases, titles, project_path(paths["mediation"]))

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

        process = self.generator.run(case_id=case_id, description=description,
                                     knowledge_block=self.knowledge_block(case_id, description))
        record = {"case_id": case_id, "condition": self.condition, "run_id": self.logger.run_id}

        if process is None:
            # Remove outputs of an earlier run so they cannot be mistaken for this run's result.
            json_path.unlink(missing_ok=True)
            bpmn_path.unlink(missing_ok=True)
            record |= {"generation_succeeded": False, "parses": False, "valid": False,
                       "errors": ["generator returned no valid output after retry (see log file)"],
                       "counts": None}
        else:
            json_path.write_text(json.dumps(process.model_dump(), indent=2), encoding="utf-8")
            self.builder.write(process, bpmn_path)
            record |= {"generation_succeeded": True, **self.validator.validate(bpmn_path)}

        (case_dir / self.validation_file).write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    def run_all(self) -> list[dict]:
        records = [self.run_case(case_id) for case_id in self.case_ids]
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
    parser = argparse.ArgumentParser(description="Run one experimental condition.")
    parser.add_argument("--condition", required=True, choices=config["conditions"])
    parser.add_argument("--run-id", default=None, help="optional; defaults to the start time")
    args = parser.parse_args()

    llm = create_llm(config, "generator")
    agent_llms = {role: create_llm(config, role) for role in MEDIATION_ROLES} if args.condition == "C3" else None
    logger = RunLogger(project_path(config["paths"]["logs"]), args.condition, args.run_id)
    runner = ExperimentRunner(config, args.condition, llm, logger, agent_llms)

    print(f"Condition {args.condition} | LLM: {llm.model} (temperature {llm.temperature}) | run {logger.run_id}\n")
    records = runner.run_all()
    print_summary(records)
    print(f"\nOutputs: {runner.output_dir}")
    if runner.orchestrator:
        print(f"Mediation: {runner.orchestrator.output_dir}")
    print(f"Log:     {logger.log_path}")


if __name__ == "__main__":
    main()
