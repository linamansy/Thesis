"""Evaluator: compares each generated BPMN model with the reference model of its case.

This is the ONLY component that reads the reference BPMN; no LLM ever sees it.

It evaluates every run in results/runs/ (see src/run_folder.py): for every run, every condition
that was run, and every case,
results/runs/<run_id>/<condition>/<case_id>/generated.bpmn is compared with data/cases/<case_id>/reference.bpmn:
  1. Syntactic validity  - was a model generated, and did it pass the validator?
                           valid (main metric) = our strict validator; bpmnlint_valid = BPMNGen's own verdict.
                           A failed or invalid model scores 0 on everything else; it is never skipped.
                           Only exception (decided 18 Oct 2026, all conditions): if the diagram (bpmndi)
                           section is the file's only problem, the structural metrics are computed without
                           it and di_stripped = True; valid stays False (src/di_rescue.py).
  2. Semantic quality    - task matching by label meaning: precision, recall, F1,
                           plus lists of matched, missing and extra tasks (src/task_matcher.py)
  3. Behavioral quality  - share of matched task pairs with the same relation
                           (order / exclusive / parallel) in both models (src/behavioral_profile.py).
                           Empty and behavioral_computable = False when a valid model has
                           fewer than two matched tasks. Message flows count as order (config).
  3b. Unsupported additions - extra (unmatched) generated tasks, and how many of them look like they
                           came from the knowledge block (PROVISIONAL diagnostic, see extra_task_diagnostics)
  3d. Legal steps (SILVER reference, data/silver/silver_reference.json, AI-made, provisional):
                           requirement coverage, extra tasks that are justified legal steps (not errors),
                           precision_adjusted, unjustified knowledge additions (see silver_diagnostics)
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
and, for the knowledge-traceable diagnostic, for every value in evaluation.trace_sensitivity_thresholds
(trace_threshold 0.5 fixed before the real runs, checked at 0.4 / 0.5 / 0.6):
  results/sensitivity/trace_threshold_<t>.csv and results/sensitivity/trace_summary.csv

Run from the project root:
  .venv\\Scripts\\python.exe -m src.evaluate                       (all runs, all conditions)
  .venv\\Scripts\\python.exe -m src.evaluate --runs anthropic_rep1 --conditions C1
  .venv\\Scripts\\python.exe -m src.evaluate --sweep
"""

import argparse
import json
import re
import tempfile
from pathlib import Path

import pandas as pd

from src.behavioral_profile import behavioral_similarity
from src.bpmn_graph import BPMNGraph
from src.complexity import ComplexityMeasurer
from src.config import load_config, project_path
from src.di_rescue import DIRescue
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
        self.di_rescue = DIRescue()
        self.message_flows_as_order = settings.get("message_flows_as_order", True)
        self.trace_threshold = settings.get("trace_threshold", 0.5)
        self.trace_sweep_thresholds = settings.get("trace_sensitivity_thresholds", [])
        self.trace_csv_pattern = paths.get("evaluation_trace_csv")
        self.trace_summary_path = (project_path(paths["evaluation_trace_summary"])
                                   if "evaluation_trace_summary" in paths else None)
        self.knowledge_file = paths.get("knowledge_block_file", "knowledge_block.txt")
        silver_path = project_path(paths["silver_reference"]) if "silver_reference" in paths else None
        self.silver = (json.loads(silver_path.read_text(encoding="utf-8"))["cases"]
                       if silver_path and silver_path.exists() else None)

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

        generated_path = case_dir / self.bpmn_file
        with tempfile.TemporaryDirectory() as work_dir:
            # The model file that is scored: the generated file if it is valid; otherwise, if the diagram
            # section was its only problem, a copy without that section (src/di_rescue.py); else none (score 0).
            model_path = None
            di_stripped = False
            if validation["generation_succeeded"] and validation["valid"]:
                model_path = generated_path
            elif validation["generation_succeeded"] and generated_path.exists():
                model_path = self.di_rescue.rescue(generated_path, Path(work_dir))
                di_stripped = model_path is not None
            usable = model_path is not None
            if usable:
                scores = self.compare(model_path, reference_path, threshold)
            else:
                scores = self.zero_scores(reference)
            additions = self.extra_task_diagnostics(condition, case_id, case_dir, scores["semantic"]["extra"]) \
                if usable else {"n_extra_tasks": 0, "n_extra_knowledge_traceable": 0, "extra_tasks": []}
            legal = self.silver_diagnostics(case_id, model_path, scores["semantic"], additions)
        complexity = self.complexity.measure(reference)
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
                "syntactic": {**{key: validation.get(key) for key in ("generation_succeeded", "valid", "errors")},
                              "bpmnlint_valid": bpmngen.get("bpmnlint_valid"), "di_stripped": di_stripped},
                **scores,
                "extra_task_diagnostics": additions,
                "silver_legal_diagnostics": legal,
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
            "trace_threshold": self.trace_threshold,
            "generation_succeeded": validation["generation_succeeded"],
            "valid": validation["valid"],                        # strict: our validator (main metric)
            "bpmnlint_valid": bpmngen.get("bpmnlint_valid"),     # BPMNGen's own verdict (None: not BPMNGen)
            "di_stripped": di_stripped,                          # scored without its diagram section
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
            "n_required_steps": legal["n_required_steps"],
            "requirement_coverage": legal["requirement_coverage"],
            "n_extra_justified": legal["n_extra_justified"],
            "precision_adjusted": legal["precision_adjusted"],
            "n_unjustified_knowledge_additions": legal["n_unjustified_knowledge_additions"],
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
        ids = [e["generated_id"] for e in extra]
        result = {"n_extra_tasks": len(labels), "n_extra_knowledge_traceable": 0, "extra_tasks": []}
        knowledge_path = case_dir / self.knowledge_file
        if condition == "C1" or not labels or not knowledge_path.exists():
            result["extra_tasks"] = [{"generated_id": i, "label": label, "knowledge_traceable": False}
                                     for i, label in zip(ids, labels)]
            return result
        description = (self.cases_dir / case_id / self.config["paths"]["case_description_file"]).read_text(
            encoding="utf-8")
        to_knowledge = self.matcher.best_similarity(labels, split_sentences(knowledge_path.read_text(encoding="utf-8")))
        to_description = self.matcher.best_similarity(labels, split_sentences(description))
        for i, label, k, d in zip(ids, labels, to_knowledge, to_description):
            traceable = k >= self.trace_threshold and k > d
            result["extra_tasks"].append({"generated_id": i, "label": label, "similarity_to_knowledge": round(k, 4),
                                          "similarity_to_description": round(d, 4), "knowledge_traceable": traceable})
        result["n_extra_knowledge_traceable"] = sum(e["knowledge_traceable"] for e in result["extra_tasks"])
        return result

    def silver_diagnostics(self, case_id: str, generated_path: Path | None, semantic: dict, additions: dict) -> dict:
        """Scores against the SILVER legal reference (data/silver/silver_reference.json, AI-made, provisional).

        n_required_steps       steps that the applicable rules of the case require (silver)
        requirement_coverage   share of those steps realised by some generated task (one-to-one matching, same
                               embedding threshold as the task matching); None if the case has no required step
        n_extra_justified      extra tasks (not in the PMo reference) that realise a required step: they are a
                               correct legal addition, NOT an error
        precision_adjusted     (n_matched + n_extra_justified) / n_generated_tasks: precision in which correct
                               legal steps no longer count against the model (plain precision is kept as well)
        n_unjustified_knowledge_additions  knowledge-traceable extra tasks that realise NO required step:
                               the damage raw retrieval is expected to cause and mediation to prevent
        All are None when no silver reference has been built yet.
        """
        empty = {"n_required_steps": None, "requirement_coverage": None, "n_extra_justified": None,
                 "precision_adjusted": None, "n_unjustified_knowledge_additions": None, "required_step_matches": []}
        if self.silver is None or case_id not in self.silver:
            return empty
        required = {f"req_{i}": step["label"] for i, step in enumerate(self.silver[case_id]["required_steps"])}
        result = dict(empty, n_required_steps=len(required))
        if generated_path is None:  # failed or invalid model: nothing realised
            return dict(result, requirement_coverage=0.0 if required else None, n_extra_justified=0,
                        precision_adjusted=0.0, n_unjustified_knowledge_additions=0)
        generated = BPMNGraph.from_file(generated_path, self.message_flows_as_order).task_labels()
        matches = self.matcher.match(generated, required)["matched"] if required else []
        realising = {m["generated_id"] for m in matches}
        extra_ids = {e["generated_id"] for e in semantic["extra"]}
        justified = extra_ids & realising
        unjustified = sum(1 for e in additions["extra_tasks"]
                          if e["knowledge_traceable"] and e["generated_id"] not in justified)
        n_generated = semantic["n_generated_tasks"]
        return dict(result,
                    requirement_coverage=round(len(matches) / len(required), 4) if required else None,
                    n_extra_justified=len(justified),
                    precision_adjusted=round((semantic["n_matched"] + len(justified)) / n_generated, 4)
                    if n_generated else 0.0,
                    n_unjustified_knowledge_additions=unjustified,
                    required_step_matches=matches)

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

    def trace_sweep(self, conditions: list[str] | None = None, run_ids: list[str] | None = None) -> pd.DataFrame:
        """Sensitivity check of trace_threshold (decided before the real runs: 0.5 fixed, checked at 0.4/0.5/0.6).

        Only the knowledge-traceable counts (n_extra_knowledge_traceable, n_unjustified_knowledge_additions)
        depend on it; everything else is computed at the main thresholds. One CSV per value, plus a summary
        per value per condition (mean and SD over repetitions). evaluation.json files are not written here.
        """
        fixed = self.trace_threshold
        tables = []
        try:
            for value in self.trace_sweep_thresholds:
                self.trace_threshold = value
                csv_path = project_path(self.trace_csv_pattern.format(threshold=f"{value:.2f}"))
                tables.append(self.evaluate(conditions, run_ids, csv_path=csv_path, save_details=False))
        finally:
            self.trace_threshold = fixed
        keys = ["trace_threshold"]
        summary = summarise_repetitions(summarise_runs(self.without_smoke_runs(pd.concat(tables)), keys), keys)
        self.trace_summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(self.trace_summary_path, index=False)
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
        trace = evaluator.trace_sweep(args.conditions, args.runs)
        print(f"\nSensitivity check of trace_threshold (fixed {evaluator.trace_threshold}):")
        print(trace[["trace_threshold", "condition", "extra_knowledge_traceable_mean", "extra_knowledge_traceable_sd",
                     "unjustified_knowledge_additions_mean"]].to_string(index=False) if not trace.empty else "(no runs)")
        print(f"\nSaved one CSV per trace threshold and {evaluator.trace_summary_path}")


if __name__ == "__main__":
    main()
