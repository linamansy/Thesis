"""Entry point: run one experimental condition over all working cases.

Usage (from the project root):
    .venv\\Scripts\\python.exe run_experiment.py --condition C1

For every case it saves, in results/<condition>/<case_id>/:
    generated.json   the process structure returned by the generator
    generated.bpmn   the BPMN XML built from it
    validation.json  the result of the validity checks
A case where the generator fails is recorded as a failed generation, never skipped.
"""

import argparse
import json
from pathlib import Path

from src.bpmn_builder import BPMNBuilder
from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator
from src.llm.base_llm import LLMClient
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.validator import BPMNValidator

CONDITIONS = ["C1", "C2", "C3"]


def create_llm(config: dict) -> LLMClient:
    """Choose the LLM provider named in config.yaml."""
    llm_config = config["llm"]
    if llm_config["provider"] == "mock":
        sample = project_path(config["paths"]["mock_generator_response"]).read_text(encoding="utf-8")
        return MockLLM([sample], temperature=llm_config["temperature"])
    raise NotImplementedError(f"LLM provider {llm_config['provider']!r} is not available yet")


class ExperimentRunner:
    """Runs the generator, builder and validator for every case of one condition."""

    def __init__(self, config: dict, condition: str, llm: LLMClient, logger: RunLogger):
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

    def knowledge_block(self, case_id: str) -> str:
        """The only part of the generator prompt that differs between conditions."""
        if self.condition == "C1":
            return NO_KNOWLEDGE_TEXT
        raise NotImplementedError(f"condition {self.condition} is not built yet")

    def run_case(self, case_id: str) -> dict:
        """Generate, build and validate one case, and save all outputs."""
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        case_dir = self.output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        json_path, bpmn_path = case_dir / self.json_file, case_dir / self.bpmn_file

        process = self.generator.run(case_id=case_id, description=description,
                                     knowledge_block=self.knowledge_block(case_id))
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
        return [self.run_case(case_id) for case_id in self.case_ids]


def print_summary(records: list[dict]) -> None:
    print(f"{'case':<6}{'generated':>11}{'valid':>7}{'tasks':>7}{'gateways':>10}  errors")
    for r in records:
        counts = r["counts"] or {}
        print(f"{r['case_id']:<6}{str(r['generation_succeeded']):>11}{str(r['valid']):>7}"
              f"{counts.get('tasks', '-'):>7}{counts.get('gateways', '-'):>10}  {len(r['errors'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one experimental condition.")
    parser.add_argument("--condition", required=True, choices=CONDITIONS)
    parser.add_argument("--run-id", default=None, help="optional; defaults to the start time")
    args = parser.parse_args()

    config = load_config()
    llm = create_llm(config)
    logger = RunLogger(project_path(config["paths"]["logs"]), args.condition, args.run_id)
    runner = ExperimentRunner(config, args.condition, llm, logger)

    print(f"Condition {args.condition} | LLM: {llm.model} (temperature {llm.temperature}) | run {logger.run_id}\n")
    records = runner.run_all()
    print_summary(records)
    print(f"\nOutputs: {runner.output_dir}")
    print(f"Log:     {logger.log_path}")


if __name__ == "__main__":
    main()
