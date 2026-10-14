"""Evaluator: compares each generated BPMN model with the reference model of its case.

This is the ONLY component that reads the reference BPMN; no LLM ever sees it.

For results/<condition>/<case_id>/generated.bpmn against data/cases/<case_id>/reference.bpmn:
  1. Syntactic validity  - was a model generated, and did it pass the validator?
                           A failed or invalid model scores 0 on everything else; it is never skipped.
  2. Semantic quality    - task matching by label meaning: precision, recall, F1,
                           plus lists of matched, missing and extra tasks (src/task_matcher.py)
  3. Behavioral quality  - share of matched task pairs with the same relation
                           (order / exclusive / parallel) in both models (src/behavioral_profile.py)
  4. Reference complexity - size and control-flow complexity of the reference (src/complexity.py)

Outputs:
  results/evaluation.csv                          one row per case per condition
  results/<condition>/<case_id>/evaluation.json   all details for one case

Run from the project root:
  .venv\\Scripts\\python.exe -m src.evaluate                  (every condition that has results)
  .venv\\Scripts\\python.exe -m src.evaluate --conditions C1
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from src.behavioral_profile import behavioral_similarity
from src.bpmn_graph import BPMNGraph
from src.complexity import ComplexityMeasurer
from src.config import load_config, project_path
from src.task_matcher import TaskMatcher


class Evaluator:
    """Scores generated models against the reference models."""

    def __init__(self, config: dict, matcher: TaskMatcher | None = None):
        paths, settings = config["paths"], config["evaluation"]
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.reference_file = paths["case_reference_file"]
        self.results_dir = project_path(paths["results"])
        self.validation_file = paths["validation_file"]
        self.bpmn_file = paths["generated_bpmn_file"]
        self.details_file = paths["evaluation_details_file"]
        self.csv_path = project_path(paths["evaluation"])
        self.matcher = matcher or TaskMatcher(settings["embedding_model"], settings["similarity_threshold"])
        self.complexity = ComplexityMeasurer(settings["complexity_weights"])

    # ---------- comparing two models ----------

    def compare(self, generated_path: Path, reference_path: Path) -> dict:
        """Semantic and behavioral scores of one generated model against one reference."""
        generated = BPMNGraph.from_file(generated_path)
        reference = BPMNGraph.from_file(reference_path)
        matching = self.matcher.match(generated.task_labels(), reference.task_labels())

        n_matched = len(matching["matched"])
        precision = n_matched / len(generated.tasks) if generated.tasks else 0.0  # generated tasks that are correct
        recall = n_matched / len(reference.tasks) if reference.tasks else 0.0     # reference tasks that were found
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        pairs = [(m["generated_id"], m["reference_id"]) for m in matching["matched"]]
        return {
            "semantic": {
                "n_generated_tasks": len(generated.tasks),
                "n_reference_tasks": len(reference.tasks),
                "n_matched": n_matched,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                **matching,
            },
            "behavioral": behavioral_similarity(generated, reference, pairs),
        }

    def zero_scores(self, reference: BPMNGraph) -> dict:
        """Scores for a failed or invalid model: 0 everywhere, all reference tasks missing."""
        return {
            "semantic": {
                "n_generated_tasks": 0, "n_reference_tasks": len(reference.tasks), "n_matched": 0,
                "precision": 0.0, "recall": 0.0, "f1": 0.0, "matched": [], "extra": [],
                "missing": [{"reference_id": i, "reference_label": label}
                            for i, label in reference.task_labels().items()],
            },
            "behavioral": {"behavioral_similarity": 0.0, "n_pairs": 0, "n_same": 0, "pairs": []},
        }

    # ---------- one case, all cases ----------

    def evaluate_case(self, condition: str, case_id: str) -> dict:
        """Evaluate one case, save evaluation.json, and return its CSV row."""
        case_dir = self.results_dir / condition / case_id
        reference_path = self.cases_dir / case_id / self.reference_file
        reference = BPMNGraph.from_file(reference_path)

        validation_path = case_dir / self.validation_file
        if validation_path.exists():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
        else:
            validation = {"generation_succeeded": False, "valid": False,
                          "errors": ["no output found for this case"]}

        usable = validation["generation_succeeded"] and validation["valid"]
        scores = self.compare(case_dir / self.bpmn_file, reference_path) if usable else self.zero_scores(reference)
        complexity = self.complexity.measure(reference)

        details = {
            "condition": condition,
            "case_id": case_id,
            "run_id": validation.get("run_id"),
            "syntactic": {key: validation.get(key) for key in ("generation_succeeded", "valid", "errors")},
            **scores,
            "reference_complexity": complexity,
            "settings": {"embedding_model": self.matcher.model_name,
                         "similarity_threshold": self.matcher.threshold},
        }
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / self.details_file).write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")

        semantic, behavioral = scores["semantic"], scores["behavioral"]
        return {
            "condition": condition,
            "case_id": case_id,
            "run_id": validation.get("run_id"),
            "generation_succeeded": validation["generation_succeeded"],
            "valid": validation["valid"],
            "n_generated_tasks": semantic["n_generated_tasks"],
            "n_reference_tasks": semantic["n_reference_tasks"],
            "n_matched": semantic["n_matched"],
            "precision": round(semantic["precision"], 4),
            "recall": round(semantic["recall"], 4),
            "f1": round(semantic["f1"], 4),
            "behavioral_similarity": round(behavioral["behavioral_similarity"], 4),
            "n_pairs": behavioral["n_pairs"],
            **{f"ref_{name}": value for name, value in complexity.items()},
        }

    def evaluate(self, conditions: list[str]) -> pd.DataFrame:
        """Evaluate every case of the given conditions and write results/evaluation.csv."""
        rows = [self.evaluate_case(condition, case_id) for condition in conditions for case_id in self.case_ids]
        table = pd.DataFrame(rows)
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(self.csv_path, index=False)
        return table


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="Evaluate generated BPMN models against the references.")
    parser.add_argument("--conditions", nargs="+", choices=config["conditions"],
                        help="default: every condition that has a results folder")
    args = parser.parse_args()

    evaluator = Evaluator(config)
    conditions = args.conditions or [c for c in config["conditions"] if (evaluator.results_dir / c).is_dir()]
    if not conditions:
        print("No results found to evaluate.")
        return

    table = evaluator.evaluate(conditions)
    columns = ["condition", "case_id", "valid", "n_matched", "precision", "recall", "f1",
               "behavioral_similarity", "ref_tasks", "ref_gateways", "ref_loops", "ref_nesting_depth",
               "ref_complexity_score"]
    print(table[columns].to_string(index=False))
    print(f"\nSaved {evaluator.csv_path}")


if __name__ == "__main__":
    main()
