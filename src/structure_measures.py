"""StructureMeasures: actors, decisions and start/end events of a generated model, matched against the reference
(fix D1, 19 Oct 2026). A NEW, separate output: the main F1 and behavioural scores are not changed.

Per case (generated vs PMo reference):
  actors     lane names of a model, or its pool (participant) names when it has no lanes (BPMNGen draws one pool
             per actor, the PMo references use lanes). Matched one-to-one by label meaning with the evaluation's
             TaskMatcher and similarity threshold. Most PMo references have no actors at all: then "not defined".
  decisions  diverging gateways (gateways with more than one outgoing flow, loop-back flows included), per gateway type
             (exclusive, parallel, inclusive, event-based, complex); matched = per type the smaller of the two counts.
  start_events / end_events   counts; matched = the smaller count.
For each family: n_generated, n_reference, n_matched, precision = matched / generated, recall = matched / reference;
a ratio with a zero denominator is "not defined" (never 0 or 1). An invalid model is treated as in the main
evaluation (bpmndi rescue only, else nothing generated: precision 0, recall 0 where defined).

Run from the project root (refuses to overwrite its outputs):  .venv\\Scripts\\python.exe -m src.structure_measures
"""

import json
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd
from lxml import etree

from src.bpmn_graph import BPMNGraph
from src.config import load_config, project_path
from src.evaluate import Evaluator

NOT_DEFINED = "not defined"
FAMILIES = ["actors", "decisions", "start_events", "end_events"]


def ratio(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else NOT_DEFINED


def read_structure(path: Path, message_flows_as_order: bool) -> dict:
    """Actor names, decision (split gateway) types and start/end event counts of one model."""
    root = etree.parse(str(path)).getroot()
    named = {"participant": [], "lane": []}
    for element in root.iter():
        if isinstance(element.tag, str) and etree.QName(element).localname in named:
            named[etree.QName(element).localname].append(element.get("name") or "")
    graph = BPMNGraph.from_file(path, message_flows_as_order)
    types = Counter(graph.types.values())
    return {"actors": named["lane"] or named["participant"],
            # all outgoing flows count (out_degree), so a loop decision (one branch jumps back) is a decision too
            "decisions": Counter(graph.types[n] for n in graph.gateways if graph.out_degree(n) >= 2),
            "start_events": types["startEvent"], "end_events": types["endEvent"]}


class StructureMeasures:
    """Compares the structure of a generated model with the reference."""

    def __init__(self, evaluator: Evaluator):
        self.ev = evaluator

    def compare(self, generated: dict | None, reference: dict) -> dict:
        """generated: read_structure() of the scored model, or None for a failed / invalid model."""
        empty = {"actors": [], "decisions": Counter(), "start_events": 0, "end_events": 0}
        gen = generated or empty
        actor_matches = (self.ev.matcher.match(dict(enumerate(gen["actors"])), dict(enumerate(reference["actors"])))
                         ["matched"] if gen["actors"] and reference["actors"] else [])
        counts = {
            "actors": (len(gen["actors"]), len(reference["actors"]), len(actor_matches)),
            "decisions": (sum(gen["decisions"].values()), sum(reference["decisions"].values()),
                          sum((gen["decisions"] & reference["decisions"]).values())),
            "start_events": (gen["start_events"], reference["start_events"],
                             min(gen["start_events"], reference["start_events"])),
            "end_events": (gen["end_events"], reference["end_events"], min(gen["end_events"], reference["end_events"])),
        }
        row = {}
        for family, (n_gen, n_ref, n_matched) in counts.items():
            precision = ratio(n_matched, n_gen)
            if generated is None:             # failed model: scored 0 by rule, as in the main evaluation
                precision = 0.0 if n_ref else NOT_DEFINED
            row |= {f"{family}_generated": n_gen, f"{family}_reference": n_ref, f"{family}_matched": n_matched,
                    f"{family}_precision": precision, f"{family}_recall": ratio(n_matched, n_ref)}
        if not reference["actors"]:           # the reference defines no actors: nothing to evaluate
            row["actors_precision"] = NOT_DEFINED
        row["decision_types_generated"] = json.dumps(dict(sorted(gen["decisions"].items())))
        row["decision_types_reference"] = json.dumps(dict(sorted(reference["decisions"].items())))
        return row

    def score_run_case(self, run: dict, condition: str, case_id: str) -> dict:
        paths = self.ev.config["paths"]
        case_dir = run["path"] / condition / case_id
        validation_path = case_dir / paths["validation_file"]
        validation = (json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists()
                      else {"generation_succeeded": False, "valid": False})
        flows = self.ev.message_flows_as_order
        reference = read_structure(self.ev.cases_dir / case_id / paths["case_reference_file"], flows)
        with tempfile.TemporaryDirectory() as work_dir:
            model_path, di_stripped = self.ev.scored_model(validation, case_dir / paths["generated_bpmn_file"],
                                                           Path(work_dir))
            generated = read_structure(model_path, flows) if model_path else None
        return {"run_id": run["run_id"], "repetition": run["repetition"], "condition": condition,
                "case_id": case_id, "di_stripped": di_stripped, **self.compare(generated, reference)}


def summary(table: pd.DataFrame) -> str:
    """Markdown: per condition and family, mean precision / recall over the rows where they are defined."""
    lines = ["# Structure measures (actors, decisions, start/end events), Study 1", "",
             "A NEW, separate output (src/structure_measures.py); the main F1 and behavioural scores are unchanged. "
             "Means over the rows where the value is defined; n = number of such rows.", "",
             "| Condition | Family | precision (mean, n) | recall (mean, n) |", "|---|---|---|---|"]
    for condition, g in table.groupby("condition"):
        for family in FAMILIES:
            cells = []
            for kind in ("precision", "recall"):
                values = pd.to_numeric(g[f"{family}_{kind}"].replace(NOT_DEFINED, None), errors="coerce").dropna()
                cells.append(f"{values.mean():.4f} (n={len(values)})" if len(values) else f"{NOT_DEFINED} (n=0)")
            lines.append(f"| {condition} | {family} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    config = load_config()
    paths = config["paths"]
    outputs = [project_path(paths["structure_measures_csv"]), project_path(paths["structure_measures_report"])]
    existing = [str(p) for p in outputs if p.exists()]
    if existing:
        raise SystemExit(f"Not started: {existing} already exist; outputs are never overwritten.")
    evaluator = Evaluator(config)
    measures = StructureMeasures(evaluator)
    rows = [measures.score_run_case(run, condition, case_id)
            for run in evaluator.runs() for condition in config["conditions"] if condition in run["conditions"]
            for case_id in config["cases"]["ids"]]
    table = pd.DataFrame(rows)
    outputs[0].parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(outputs[0], index=False)
    outputs[1].write_text(summary(table), encoding="utf-8")
    print(outputs[1].read_text(encoding="utf-8"))
    print(f"Saved {outputs[0]}\nSaved {outputs[1]}")


if __name__ == "__main__":
    main()
