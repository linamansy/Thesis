"""MatcherSample: a random sample of task pairs for a MANUAL check of the task matcher (fix D4, 19 Oct 2026).
The matcher itself is not changed; it is only used to compute similarities.

Population (the study's runs, config.yaml statistics.runs, from the stored per-case evaluation.json files):
  matched     every pair the evaluation matched (generated task, reference task, similarity)
  unmatched   every generated task the evaluation left unmatched, paired with its MOST SIMILAR reference task of
              the same case (similarity computed with the same TaskMatcher, read only)
Sample: config.yaml diagnostics.matcher_sample_size of each kind (30), drawn with diagnostics.matcher_sample_seed
(42) from the populations in a fixed order, then shuffled together, so the order does not reveal the kind.
Output: paths.matcher_sample (results/diagnostics/matcher_sample.csv) with an EMPTY manual_judgement column to fill
in by hand. The command refuses to overwrite it.

Run from the project root:  .venv\\Scripts\\python.exe -m src.matcher_sample
"""

import json
import random

import pandas as pd

from src.config import load_config, project_path
from src.run_folder import RunFolder


class MatcherSample:
    """Builds the matched / unmatched populations and draws the sample."""

    def __init__(self, config: dict, matcher):
        self.config = config
        self.matcher = matcher              # needs similarity_matrix(generated_labels, reference_labels)

    def populations(self) -> tuple[list[dict], list[dict]]:
        paths, study = self.config["paths"], self.config["statistics"]["runs"]
        matched, unmatched = [], []
        for run in RunFolder.find_runs(self.config):
            if run["run_id"] not in study:
                continue
            for condition in self.config["conditions"]:
                for case_id in self.config["cases"]["ids"]:
                    details_path = run["path"] / condition / case_id / paths["evaluation_details_file"]
                    if not details_path.exists():
                        continue
                    semantic = json.loads(details_path.read_text(encoding="utf-8"))["semantic"]
                    where = {"run_id": run["run_id"], "condition": condition, "case_id": case_id}
                    matched += [{**where, "generated_label": m["generated_label"],
                                 "reference_label": m["reference_label"], "similarity": round(m["similarity"], 4),
                                 "matcher_decision": "matched"} for m in semantic["matched"]]
                    references = ([m["reference_label"] for m in semantic["matched"]]
                                  + [m["reference_label"] for m in semantic["missing"]])
                    extras = [e["generated_label"] for e in semantic["extra"]]
                    if extras and references:
                        similarity = self.matcher.similarity_matrix(extras, references)
                        for i, label in enumerate(extras):
                            best = max(range(len(references)), key=lambda j: similarity[i][j])
                            unmatched.append({**where, "generated_label": label,
                                              "reference_label": references[best],
                                              "similarity": round(float(similarity[i][best]), 4),
                                              "matcher_decision": "unmatched"})
        return matched, unmatched

    def sample(self, matched: list[dict], unmatched: list[dict]) -> pd.DataFrame:
        settings = self.config["diagnostics"]
        size, rng = settings["matcher_sample_size"], random.Random(settings["matcher_sample_seed"])
        rows = (rng.sample(matched, min(size, len(matched))) + rng.sample(unmatched, min(size, len(unmatched))))
        rng.shuffle(rows)
        threshold = self.config["evaluation"]["similarity_threshold"]
        return pd.DataFrame([{"sample_id": i + 1, **row, "threshold": threshold, "manual_judgement": ""}
                             for i, row in enumerate(rows)])


def main() -> None:
    from src.task_matcher import TaskMatcher
    config = load_config()
    output = project_path(config["paths"]["matcher_sample"])
    if output.exists():
        raise SystemExit(f"Not started: {output} already exists; outputs are never overwritten.")
    settings = config["evaluation"]
    sampler = MatcherSample(config, TaskMatcher(settings["embedding_model"], settings["similarity_threshold"]))
    matched, unmatched = sampler.populations()
    table = sampler.sample(matched, unmatched)
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)
    print(f"Population: {len(matched)} matched, {len(unmatched)} unmatched pairs; sample: "
          f"{(table['matcher_decision'] == 'matched').sum()} + {(table['matcher_decision'] == 'unmatched').sum()}")
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
