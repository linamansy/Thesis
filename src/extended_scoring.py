"""ExtendedScorer: extended-reference scoring (fix C3, 19 Oct 2026). A NEW, separate output: it never changes
evaluation.csv, the summaries or the statistics.

STATUS: PROVISIONAL until the Study 2 analysis-plan addendum is committed (config.yaml
evaluation.extended_scoring_status). Not part of the Study 1 analysis plan.

Why: the PMo reference models contain no legal steps. Here the reference is EXTENDED with the steps the silver
reference expects: reference = PMo tasks + the required_steps of every rule the silver annotator labelled
"applicable" (data/silver/silver_reference.json). One one-to-one matching (the same TaskMatcher and threshold as the
main evaluation) pairs the generated tasks with this combined reference. Per case:

  extended_precision     matched generated tasks / generated tasks (a correct required legal step is not an error)
  pmo_recall             PMo tasks matched / PMo tasks (from the same matching)
  requirement_coverage   expected requirements matched / expected requirements; "not defined" when the case
                         expects none (never 0 or 1)
  over_application       extra (unmatched) generated tasks that are law-traceable to a rule NOT labelled applicable:
                         the existing trace check (src/evaluate.py) with trace_threshold, against the sentences of
                         the case's frozen passages whose silver label is not "applicable" (decided 19 Oct 2026; the
                         law text, so C1 is checked too): similarity >= trace_threshold AND higher than to every
                         sentence of the description
With zero applicable rules the reference is the PMo model alone, so extended_precision and pmo_recall equal the
main evaluation's precision and recall. Invalid models: the same rule as the main evaluation (only the bpmndi
rescue), else 0 (coverage 0 if defined).

Run from the project root (refuses to overwrite its outputs):
  .venv\\Scripts\\python.exe -m src.extended_scoring
Outputs: config.yaml paths.extended_scoring_csv (one row per run/condition/case) and paths.extended_scoring_report.
"""

import json
import tempfile
from pathlib import Path

import pandas as pd

from src.bpmn_graph import BPMNGraph
from src.config import load_config, project_path
from src.evaluate import Evaluator, split_sentences

NOT_DEFINED = "not defined"


class ExtendedScorer:
    """Scores generated models against the PMo reference extended with the silver reference's expected steps."""

    def __init__(self, evaluator: Evaluator, frozen_cases: dict, silver_cases: dict):
        self.ev = evaluator
        self.frozen = frozen_cases      # "cases" of frozen_retrieval.json
        self.silver = silver_cases      # "cases" of silver_reference.json

    def expected_requirements(self, case_id: str) -> dict[str, str]:
        """{id: label} of the required steps of rules labelled applicable (the silver file keeps required_steps
        only for applicable rules; the label is checked again here)."""
        applicable = {p["passage_id"] for p in self.silver[case_id]["passages"] if p["label"] == "applicable"}
        steps = [s for s in self.silver[case_id]["required_steps"] if s["passage_id"] in applicable]
        return {f"req:{i}": s["label"] for i, s in enumerate(steps)}

    def non_applicable_sentences(self, case_id: str) -> list[str]:
        """Sentences of the case's frozen passages whose silver label is not "applicable"."""
        labels = {p["passage_id"]: p["label"] for p in self.silver[case_id]["passages"]}
        texts = [p["text"] for p in self.frozen[case_id]["passages"] if labels.get(p["passage_id"]) != "applicable"]
        return [s for text in texts for s in split_sentences(text, self.ev.min_sentence_chars)]

    def score(self, case_id: str, model_path: Path | None, reference: BPMNGraph, description: str) -> dict:
        pmo = {f"pmo:{i}": label for i, label in reference.task_labels().items()}
        required = self.expected_requirements(case_id)
        result = {"n_pmo_tasks": len(pmo), "n_expected_requirements": len(required)}
        if model_path is None:   # failed or invalid model: nothing realised
            return result | {"n_generated_tasks": 0, "extended_precision": 0.0, "pmo_recall": 0.0,
                             "requirement_coverage": 0.0 if required else NOT_DEFINED, "over_application": 0,
                             "n_extra_tasks": 0, "over_application_tasks": []}
        generated = BPMNGraph.from_file(model_path, self.ev.message_flows_as_order).task_labels()
        matching = self.ev.matcher.match(generated, {**pmo, **required})
        matched = matching["matched"]
        matched_pmo = sum(m["reference_id"].startswith("pmo:") for m in matched)
        matched_req = sum(m["reference_id"].startswith("req:") for m in matched)
        extra = [e["generated_label"] for e in matching["extra"]]
        law = self.ev.matcher.best_similarity(extra, self.non_applicable_sentences(case_id))
        own = self.ev.matcher.best_similarity(extra, split_sentences(description, self.ev.min_sentence_chars))
        over = [label for label, k, d in zip(extra, law, own) if k >= self.ev.trace_threshold and k > d]
        return result | {
            "n_generated_tasks": len(generated),
            "extended_precision": round(len(matched) / len(generated), 4) if generated else 0.0,
            "pmo_recall": round(matched_pmo / len(pmo), 4) if pmo else 0.0,
            "requirement_coverage": round(matched_req / len(required), 4) if required else NOT_DEFINED,
            "over_application": len(over), "n_extra_tasks": len(extra), "over_application_tasks": over,
        }

    def score_run_case(self, run: dict, condition: str, case_id: str) -> dict:
        """One CSV row: scores of one case of one run (model chosen exactly as in the main evaluation)."""
        paths = self.ev.config["paths"]
        case_dir = run["path"] / condition / case_id
        validation_path = case_dir / paths["validation_file"]
        validation = (json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists()
                      else {"generation_succeeded": False, "valid": False})
        reference = BPMNGraph.from_file(self.ev.cases_dir / case_id / paths["case_reference_file"],
                                        self.ev.message_flows_as_order)
        description = (self.ev.cases_dir / case_id / paths["case_description_file"]).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as work_dir:
            model_path, di_stripped = self.ev.scored_model(validation, case_dir / paths["generated_bpmn_file"],
                                                           Path(work_dir))
            scores = self.score(case_id, model_path, reference, description)
        return {"run_id": run["run_id"], "repetition": run["repetition"], "condition": condition,
                "case_id": case_id, "di_stripped": di_stripped,
                **{k: v for k, v in scores.items() if k != "over_application_tasks"},
                "over_application_tasks": " | ".join(scores["over_application_tasks"])}


def report(table: pd.DataFrame, evaluation: pd.DataFrame, status: str) -> str:
    """Markdown comparison of the original scores (evaluation.csv) with the extended scores, per condition."""
    merged = table.merge(evaluation[["run_id", "condition", "case_id", "precision", "recall"]],
                         on=["run_id", "condition", "case_id"], how="left")
    lines = [f"# Extended-reference scoring, Study 1 ({status})", "",
             "Reference = PMo tasks + required steps of rules the silver annotator labelled applicable "
             "(src/extended_scoring.py). A NEW, separate output: evaluation.csv, the summaries and the statistics "
             "are unchanged. Values are means over all cases and repetitions (n per condition below).", "",
             "| Condition | n | precision (old) | extended precision | recall (old) | PMo recall | "
             "cases with expected requirements | requirement coverage | over-application (sum) | "
             "over-application (mean) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for condition, g in merged.groupby("condition"):
        defined = g[g["requirement_coverage"] != NOT_DEFINED]
        coverage = (f"{pd.to_numeric(defined['requirement_coverage']).mean():.4f}" if len(defined)
                    else NOT_DEFINED)
        lines.append(f"| {condition} | {len(g)} | {g['precision'].mean():.4f} | {g['extended_precision'].mean():.4f} | "
                     f"{g['recall'].mean():.4f} | {g['pmo_recall'].mean():.4f} | {len(defined)} | {coverage} | "
                     f"{int(g['over_application'].sum())} | {g['over_application'].mean():.4f} |")
    same_p = (merged["precision"].round(4) == merged["extended_precision"].round(4))
    same_r = (merged["recall"].round(4) == merged["pmo_recall"].round(4))
    n_req = int((merged["n_expected_requirements"] > 0).sum())
    lines += ["", f"- Rows with at least one expected requirement: {n_req} of {len(merged)}.",
              f"- Rows where extended precision = old precision: {int(same_p.sum())} of {len(merged)}; "
              f"PMo recall = old recall: {int(same_r.sum())} of {len(merged)}.",
              "- With no applicable rule the extended reference is the PMo model, so both must be equal there.",
              "- Over-application: extra tasks law-traceable to a rule NOT labelled applicable (trace check, "
              "threshold from config). The silver labels are AI-made and provisional.", ""]
    return "\n".join(lines)


def main() -> None:
    config = load_config()
    paths = config["paths"]
    csv_path, report_path = project_path(paths["extended_scoring_csv"]), project_path(paths["extended_scoring_report"])
    existing = [str(p) for p in (csv_path, report_path) if p.exists()]
    if existing:
        raise SystemExit(f"Not started: {existing} already exist; outputs are never overwritten.")
    evaluator = Evaluator(config)
    frozen = json.loads(project_path(paths["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
    silver = json.loads(project_path(paths["silver_reference"]).read_text(encoding="utf-8"))["cases"]
    scorer = ExtendedScorer(evaluator, frozen, silver)
    rows = [scorer.score_run_case(run, condition, case_id)
            for run in evaluator.runs() for condition in config["conditions"] if condition in run["conditions"]
            for case_id in config["cases"]["ids"]]
    table = pd.DataFrame(rows)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(csv_path, index=False)
    evaluation = pd.read_csv(project_path(paths["evaluation"]), dtype={"case_id": str})
    report_path.write_text(report(table, evaluation, config["evaluation"]["extended_scoring_status"]),
                           encoding="utf-8")
    print(report_path.read_text(encoding="utf-8"))
    print(f"Saved {csv_path}\nSaved {report_path}")


if __name__ == "__main__":
    main()
