"""Evaluator: compares each generated BPMN model with the reference model of its case.

This is the ONLY component that reads the reference BPMN; no LLM ever sees it.

It evaluates every run in results/runs/ (see src/run_folder.py): for every run, every condition
that was run, and every case,
results/runs/<run_id>/<condition>/<case_id>/generated.bpmn is compared with data/cases/<case_id>/reference.bpmn:
  1. Syntactic validity  - was a model generated, and did it pass the validator?
                           A failed or invalid model scores 0 on everything else; it is never skipped.
  2. Semantic quality    - task matching by label meaning: precision, recall, F1,
                           plus lists of matched, missing and extra tasks (src/task_matcher.py)
  3. Behavioral quality  - share of matched task pairs with the same relation
                           (order / exclusive / parallel) in both models (src/behavioral_profile.py).
                           Empty and behavioral_computable = False when a valid model has
                           fewer than two matched tasks. Message flows count as order (config).
  3b. Unsupported additions - extra (unmatched) generated tasks, and how many of them look like they
                           came from the knowledge block (PROVISIONAL diagnostic, see extra_task_diagnostics)
  3c. Generator diagnostics (BPMNGen) - context limit hit, token counts, BPMNGen auto-repairs
  4. Reference complexity - tasks, gateways, loops, nesting depth and Cardoso's CFC (src/complexity.py)

Outputs (main threshold from config.yaml), see src/summarise.py for the summaries:
  results/evaluation.csv               one row per run per condition per case, with run_id, repetition,
                                       provider and model columns; smoke (test) runs are included but
                                       marked smoke_test = True, and left out of every summary
  results/evaluation_run_summary.csv   one row per run per condition (means over the cases)
  results/evaluation_summary.csv       one row per condition (and provider/model): mean and SD over repetitions
  results/runs/<run_id>/<condition>/<case_id>/evaluation.json   all details for one case
With --sweep, additionally for every threshold in evaluation.sensitivity_thresholds:
  results/sensitivity/evaluation_threshold_<t>.csv and results/sensitivity/summary.csv

Run from the project root:
  .venv\\Scripts\\python.exe -m src.evaluate                       (all runs, all conditions)
  .venv\\Scripts\\python.exe -m src.evaluate --runs anthropic_rep1 --conditions C1
  .venv\\Scripts\\python.exe -m src.evaluate --sweep
"""

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from src.behavioral_profile import behavioral_similarity
from src.bpmn_graph import BPMNGraph
from src.complexity import ComplexityMeasurer
from src.config import load_config, project_path
from src.run_folder import RunFolder
from src.summarise import summarise_repetitions, summarise_runs
from src.task_matcher import TaskMatcher


def split_sentences(text: str) -> list[str]:
    """Sentences and list lines of a text (for the extra-task diagnostic); very short pieces are dropped."""
    pieces = re.split(r"(?<=[.;:!?])\s+|\n+", text)
    return [p.strip(" -") for p in pieces if len(p.strip(" -")) >= 15]


class Evaluator:
    """Scores generated models against the reference models."""

    def __init__(self, config: dict, matcher: TaskMatcher | None = None):
        paths, settings = config["paths"], config["evaluation"]
        self.config = config
        self.conditions = config["conditions"]
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.reference_file = paths["case_reference_file"]
        self.validation_file = paths["validation_file"]
        self.bpmn_file = paths["generated_bpmn_file"]
        self.details_file = paths["evaluation_details_file"]
        self.csv_path = project_path(paths["evaluation"])
        self.run_summary_path = project_path(paths["evaluation_run_summary"])
        self.summary_path = project_path(paths["evaluation_summary"])
        self.threshold_csv_pattern = paths["evaluation_threshold_csv"]
        self.sensitivity_summary_path = project_path(paths["evaluation_sensitivity_summary"])
        self.sweep_thresholds = settings["sensitivity_thresholds"]
        self.smoke_prefix = settings["smoke_run_prefix"]
        self.matcher = matcher or TaskMatcher(settings["embedding_model"], settings["similarity_threshold"])
        self.complexity = ComplexityMeasurer()
        self.message_flows_as_order = settings.get("message_flows_as_order", True)
        self.trace_threshold = settings.get("trace_threshold", 0.5)
        self.knowledge_file = paths.get("knowledge_block_file", "knowledge_block.txt")

    # ---------- comparing two models ----------

    def compare(self, generated_path: Path, reference_path: Path, threshold: float | None = None) -> dict:
        """Semantic and behavioral scores of one generated model against one reference."""
        generated = BPMNGraph.from_file(generated_path, self.message_flows_as_order)
        reference = BPMNGraph.from_file(reference_path, self.message_flows_as_order)
        matching = self.matcher.match(generated.task_labels(), reference.task_labels(), threshold)

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
        """Scores for a failed or invalid model: 0 everywhere, all reference tasks missing.

        Behavioral similarity is 0 here (not empty): the model is scored by rule, so it counts as computable.
        """
        return {
            "semantic": {
                "n_generated_tasks": 0, "n_reference_tasks": len(reference.tasks), "n_matched": 0,
                "precision": 0.0, "recall": 0.0, "f1": 0.0, "matched": [], "extra": [],
                "missing": [{"reference_id": i, "reference_label": label}
                            for i, label in reference.task_labels().items()],
            },
            "behavioral": {"behavioral_similarity": 0.0, "behavioral_computable": True,
                           "n_pairs": 0, "n_same": 0, "pairs": []},
        }

    # ---------- one case, all cases ----------

    def is_smoke(self, run_id: str) -> bool:
        """Smoke (test) runs: evaluated, but never part of any summary."""
        return run_id.startswith(self.smoke_prefix)

    def runs(self, run_ids: list[str] | None = None) -> list[dict]:
        """The run_info of every run (or of the given run ids)."""
        runs = RunFolder.find_runs(self.config)
        return [r for r in runs if run_ids is None or r["run_id"] in run_ids]

    def evaluate_case(self, run: dict, condition: str, case_id: str, threshold: float | None = None,
                      save_details: bool = True) -> dict:
        """Evaluate one case of one run, optionally save evaluation.json, and return its CSV row."""
        threshold = self.matcher.threshold if threshold is None else threshold
        case_dir = run["path"] / condition / case_id
        reference_path = self.cases_dir / case_id / self.reference_file
        reference = BPMNGraph.from_file(reference_path, self.message_flows_as_order)

        validation_path = case_dir / self.validation_file
        if validation_path.exists():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
        else:
            validation = {"generation_succeeded": False, "valid": False,
                          "errors": ["no output found for this case"]}

        usable = validation["generation_succeeded"] and validation["valid"]
        if usable:
            scores = self.compare(case_dir / self.bpmn_file, reference_path, threshold)
        else:
            scores = self.zero_scores(reference)
        complexity = self.complexity.measure(reference)
        additions = self.extra_task_diagnostics(condition, case_id, case_dir, scores["semantic"]["extra"]) \
            if usable else {"n_extra_tasks": 0, "n_extra_knowledge_traceable": 0, "extra_tasks": []}
        bpmngen = validation.get("bpmngen") or {}
        repairs = bpmngen.get("auto_repairs") or {}

        if save_details:
            details = {
                "run_id": run["run_id"],
                "repetition": run["repetition"],
                "provider": run["provider"],
                "model": run["model"],
                "condition": condition,
                "case_id": case_id,
                "syntactic": {key: validation.get(key) for key in ("generation_succeeded", "valid", "errors")},
                **scores,
                "extra_task_diagnostics": additions,
                "bpmngen": bpmngen or None,
                "reference_complexity": complexity,
                "settings": {"embedding_model": self.matcher.model_name, "similarity_threshold": threshold},
            }
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / self.details_file).write_text(json.dumps(details, indent=2, ensure_ascii=False),
                                                      encoding="utf-8")

        semantic, behavioral = scores["semantic"], scores["behavioral"]
        similarity = behavioral["behavioral_similarity"]
        return {
            "run_id": run["run_id"],
            "smoke_test": self.is_smoke(run["run_id"]),
            "repetition": run["repetition"],
            "provider": run["provider"],
            "model": run["model"],
            "condition": condition,
            "case_id": case_id,
            "similarity_threshold": threshold,
            "generation_succeeded": validation["generation_succeeded"],
            "valid": validation["valid"],
            "n_generated_tasks": semantic["n_generated_tasks"],
            "n_reference_tasks": semantic["n_reference_tasks"],
            "n_matched": semantic["n_matched"],
            "precision": round(semantic["precision"], 4),
            "recall": round(semantic["recall"], 4),
            "f1": round(semantic["f1"], 4),
            "behavioral_similarity": None if similarity is None else round(similarity, 4),
            "behavioral_computable": behavioral["behavioral_computable"],
            "n_pairs": behavioral["n_pairs"],
            "n_extra_tasks": additions["n_extra_tasks"],
            "n_extra_knowledge_traceable": additions["n_extra_knowledge_traceable"],
            "context_limit_hit": bool(validation.get("context_limit_hit", False)),
            "prompt_tokens": bpmngen.get("prompt_tokens"),
            "output_tokens": bpmngen.get("output_tokens"),
            "auto_flows_added": repairs.get("auto_flows_added"),
            "auto_links_added": repairs.get("auto_links_added"),
            "first_task_inserted": repairs.get("first_task_inserted"),
            **{f"ref_{name}": value for name, value in complexity.items()},
        }

    def extra_task_diagnostics(self, condition: str, case_id: str, case_dir: Path, extra: list[dict]) -> dict:
        """Unsupported additions: generated tasks with no match in the reference (PROVISIONAL diagnostic).

        n_extra_tasks: all unmatched generated tasks (= n_generated_tasks - n_matched).
        n_extra_knowledge_traceable: the extra tasks that look like they came from the KNOWLEDGE block,
        not from the description: label similarity to some knowledge sentence >= trace_threshold AND higher
        than to every description sentence. Only for C2 and C3 (C1 has no knowledge). This is the error
        raw RAG is expected to cause and mediation to reduce. A correct legal step that the PMo reference
        does not contain also lands here, so read the listed tasks before drawing conclusions.
        """
        labels = [e["generated_label"] for e in extra]
        result = {"n_extra_tasks": len(labels), "n_extra_knowledge_traceable": 0, "extra_tasks": []}
        knowledge_path = case_dir / self.knowledge_file
        if condition == "C1" or not labels or not knowledge_path.exists():
            result["extra_tasks"] = [{"label": label, "knowledge_traceable": False} for label in labels]
            return result
        description = (self.cases_dir / case_id / self.config["paths"]["case_description_file"]).read_text(
            encoding="utf-8")
        to_knowledge = self.matcher.best_similarity(labels, split_sentences(knowledge_path.read_text(encoding="utf-8")))
        to_description = self.matcher.best_similarity(labels, split_sentences(description))
        for label, k, d in zip(labels, to_knowledge, to_description):
            traceable = k >= self.trace_threshold and k > d
            result["extra_tasks"].append({"label": label, "similarity_to_knowledge": round(k, 4),
                                          "similarity_to_description": round(d, 4), "knowledge_traceable": traceable})
        result["n_extra_knowledge_traceable"] = sum(e["knowledge_traceable"] for e in result["extra_tasks"])
        return result

    def evaluate(self, conditions: list[str] | None = None, run_ids: list[str] | None = None,
                 threshold: float | None = None, csv_path: Path | None = None,
                 save_details: bool = True) -> pd.DataFrame:
        """Evaluate every case of every run (and condition run in it) at one threshold; write the CSV.

        A condition that was started in a run is always evaluated for all cases; a missing case
        gets 0 (never skipped). A condition that was never started in a run has no rows for that run.
        Smoke runs (test runs, often only one case) are evaluated only for the cases they ran.
        """
        rows = []
        for run in self.runs(run_ids):
            for condition in conditions or self.conditions:
                if condition not in run["conditions"]:
                    continue
                case_ids = self.case_ids
                if self.is_smoke(run["run_id"]):
                    case_ids = [c for c in case_ids
                                if (run["path"] / condition / c / self.validation_file).exists()]
                rows += [self.evaluate_case(run, condition, case_id, threshold, save_details)
                         for case_id in case_ids]
        table = pd.DataFrame(rows)
        csv_path = csv_path or self.csv_path
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        table.to_csv(csv_path, index=False)
        return table

    def without_smoke_runs(self, table: pd.DataFrame) -> pd.DataFrame:
        return table[~table["smoke_test"]] if not table.empty else table

    def summarise(self, table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Per run per condition, and per condition across repetitions; both saved as CSV.

        Smoke runs are left out of both summaries (they stay in evaluation.csv, marked smoke_test).
        """
        run_summary = summarise_runs(self.without_smoke_runs(table))
        summary = summarise_repetitions(run_summary)
        run_summary.to_csv(self.run_summary_path, index=False)
        summary.to_csv(self.summary_path, index=False)
        return run_summary, summary

    def sweep(self, conditions: list[str] | None = None, run_ids: list[str] | None = None) -> pd.DataFrame:
        """Sensitivity analysis: evaluate at every sweep threshold, one CSV per threshold.

        Per-case evaluation.json files are not written here; they always describe the main threshold.
        Returns (and saves) the per-threshold, per-condition summary (mean and SD over repetitions).
        """
        tables = []
        for threshold in self.sweep_thresholds:
            csv_path = project_path(self.threshold_csv_pattern.format(threshold=f"{threshold:.2f}"))
            tables.append(self.evaluate(conditions, run_ids, threshold, csv_path, save_details=False))
        keys = ["similarity_threshold"]
        summary = summarise_repetitions(summarise_runs(self.without_smoke_runs(pd.concat(tables)), keys), keys)
        self.sensitivity_summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(self.sensitivity_summary_path, index=False)
        return summary


def main() -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="Evaluate generated BPMN models against the references.")
    parser.add_argument("--conditions", nargs="+", choices=config["conditions"], help="default: all")
    parser.add_argument("--runs", nargs="+", help="run ids to evaluate; default: every run in results/runs/")
    parser.add_argument("--sweep", action="store_true",
                        help="also evaluate at every threshold in evaluation.sensitivity_thresholds")
    args = parser.parse_args()

    evaluator = Evaluator(config)
    table = evaluator.evaluate(args.conditions, args.runs)
    if table.empty:
        print("No runs found to evaluate.")
        return

    run_summary, summary = evaluator.summarise(table)
    smoke_runs = sorted(table.loc[table["smoke_test"], "run_id"].unique())
    print(f"Evaluated {len(table)} rows from {table['run_id'].nunique()} run(s) "
          f"at threshold {evaluator.matcher.threshold}.")
    if smoke_runs:
        print(f"Smoke runs (in evaluation.csv, left out of the summaries): {', '.join(smoke_runs)}")
    if run_summary.empty:
        print("No non-smoke runs to summarise.")
        return
    print("\nPer run:")
    print(run_summary[["run_id", "repetition", "condition", "n_valid", "precision_mean", "recall_mean",
                       "f1_mean", "behavioral_mean_excluding", "behavioral_n_excluded",
                       "behavioral_mean_as_zero"]].to_string(index=False))
    print("\nPer condition, mean and SD over repetitions:")
    print(summary.to_string(index=False))
    print(f"\nSaved {evaluator.csv_path}\nSaved {evaluator.run_summary_path}\nSaved {evaluator.summary_path}")

    if args.sweep:
        sensitivity = evaluator.sweep(args.conditions, args.runs)
        print("\nSensitivity analysis:")
        print(sensitivity.to_string(index=False))
        print(f"\nSaved one CSV per threshold and {evaluator.sensitivity_summary_path}")


if __name__ == "__main__":
    main()
