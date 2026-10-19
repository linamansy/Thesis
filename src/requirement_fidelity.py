"""RequirementFidelity: does each requirement C3 generated match the requirement the silver reference expects?
(fix C4, 19 Oct 2026; docs/ANALYSIS_PLAN.md section 4, RQ3 "requirement fidelity").

Only for rules that BOTH C3 (label "Applicable", with a RequirementAgent output) and the silver annotator (label
"applicable") call applicable; otherwise there is nothing to compare and the result is "not estimable". Study 1 has
no such rule (silver labelled none applicable), so this module is tested on synthetic data only.

Per pair (one C3 requirement vs the silver required_steps of the same passage):
  action_similarity   highest similarity of the requirement's action to any expected step label (same TaskMatcher
                      as the evaluation); action_faithful = action_similarity >= evaluation.similarity_threshold
  actor_similarity    requirement actor vs the actor of that best-matching step; None ("not comparable") when the
                      silver step names no actor; actor_faithful likewise
  timing_similarity   requirement ordering vs the step's timing; None when either side states none
Per run: number of pairs, share action-faithful, share actor-faithful (of the comparable ones), plus how many rules
only C3 or only silver called applicable (context; their agreement itself is RQ3, src/rq3_agreement.py).
"""

import json
from pathlib import Path

import pandas as pd

from src.config import load_config, project_path
from src.run_folder import RunFolder

NOT_ESTIMABLE = "not estimable"


class RequirementFidelity:
    """Compares C3 requirements with the silver reference's expected requirements."""

    def __init__(self, matcher, threshold: float, silver_cases: dict):
        self.matcher = matcher          # needs best_similarity(labels, texts)
        self.threshold = threshold
        self.silver = silver_cases

    def similarity(self, a: str | None, b: str | None) -> float | None:
        if not a or not b:
            return None
        return round(self.matcher.best_similarity([a], [b])[0], 4)

    def compare(self, requirement: dict, steps: list[dict]) -> dict:
        """One C3 requirement (actor, action, condition, ordering) vs the expected steps of the same rule."""
        # best step: the one whose label is most similar to the action
        per_step = [self.matcher.best_similarity([requirement["action"]], [s["label"]])[0] for s in steps]
        best = max(range(len(steps)), key=lambda i: per_step[i]) if steps else None
        step = steps[best] if best is not None else {}
        action = round(per_step[best], 4) if best is not None else 0.0
        actor = self.similarity(requirement.get("actor"), step.get("actor"))
        timing = self.similarity(requirement.get("ordering"), step.get("timing"))
        return {"expected_step": step.get("label"), "action_similarity": action,
                "action_faithful": action >= self.threshold,
                "actor_similarity": actor, "actor_faithful": None if actor is None else actor >= self.threshold,
                "timing_similarity": timing, "n_expected_steps": len(steps)}

    def pairs(self, case_id: str, mediation: dict) -> tuple[list[dict], int, int]:
        """Rows for every rule both call applicable, and the counts of rules only C3 / only silver call applicable."""
        silver = {p["passage_id"]: p["label"] for p in self.silver.get(case_id, {}).get("passages", [])}
        steps = self.silver.get(case_id, {}).get("required_steps", [])
        rows, c3_only, silver_only = [], 0, 0
        for record in mediation["passages"]:
            c3_applicable = record["label"] == "Applicable" and bool(record.get("requirement"))
            silver_applicable = silver.get(record["passage_id"]) == "applicable"
            if c3_applicable and silver_applicable:
                expected = [s for s in steps if s["passage_id"] == record["passage_id"]]
                result = self.compare(record["requirement"], expected)
                rows.append({"case_id": case_id, "passage_id": record["passage_id"],
                             "generated_action": record["requirement"]["action"],
                             "generated_actor": record["requirement"].get("actor"), **result})
            elif c3_applicable:
                c3_only += 1
            elif silver_applicable:
                silver_only += 1
        return rows, c3_only, silver_only

    def run_summary(self, rows: list[dict], c3_only: int, silver_only: int) -> dict:
        """Shares over a run's pairs; NOT_ESTIMABLE when there is no pair."""
        n = len(rows)
        actors = [r["actor_faithful"] for r in rows if r["actor_faithful"] is not None]
        return {"n_pairs": n,
                "action_faithful_share": round(sum(r["action_faithful"] for r in rows) / n, 4) if n else NOT_ESTIMABLE,
                "n_actor_comparable": len(actors),
                "actor_faithful_share": round(sum(actors) / len(actors), 4) if actors else NOT_ESTIMABLE,
                "n_applicable_c3_only": c3_only, "n_applicable_silver_only": silver_only}

    def analyse_mediation_dir(self, mediation_dir: Path, summary_file: str) -> tuple[list[dict], dict]:
        rows, c3_only, silver_only = [], 0, 0
        for path in sorted(mediation_dir.glob("*.json")):
            if path.name == summary_file:
                continue
            case_rows, c, s = self.pairs(path.stem, json.loads(path.read_text(encoding="utf-8")))
            rows += case_rows
            c3_only += c
            silver_only += s
        return rows, self.run_summary(rows, c3_only, silver_only)


def main() -> None:
    from src.task_matcher import TaskMatcher
    config = load_config()
    paths = config["paths"]
    outputs = [project_path(paths["requirement_fidelity_csv"]), project_path(paths["requirement_fidelity_summary"])]
    existing = [str(p) for p in outputs if p.exists()]
    if existing:
        raise SystemExit(f"Not started: {existing} already exist; outputs are never overwritten.")
    settings = config["evaluation"]
    silver = json.loads(project_path(paths["silver_reference"]).read_text(encoding="utf-8"))["cases"]
    fidelity = RequirementFidelity(TaskMatcher(settings["embedding_model"], settings["similarity_threshold"]),
                                   settings["similarity_threshold"], silver)
    all_rows, summaries = [], []
    for run in RunFolder.find_runs(config):
        if run["run_id"] not in config["statistics"]["runs"]:
            continue
        mediation_dir = run["path"] / "C3" / paths["mediation_dir"]
        if not mediation_dir.exists():
            continue
        rows, summary = fidelity.analyse_mediation_dir(mediation_dir, paths["mediation_summary_file"])
        all_rows += [{"run_id": run["run_id"], **r} for r in rows]
        summaries.append({"run_id": run["run_id"], **summary})
    outputs[0].parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(all_rows).to_csv(outputs[0], index=False)
    pd.DataFrame(summaries).to_csv(outputs[1], index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    print(f"Saved {outputs[0]}\nSaved {outputs[1]}")


if __name__ == "__main__":
    main()
