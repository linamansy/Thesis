"""Study 2: evaluation of the GDPR development smoke run, written ONLY into results/diagnostics/gdpr_dev_smoke/.

The smoke run (src/run_gdpr_dev_smoke.py, run id study2_gdpr.smoke_run_id) is scored with Study 1's own Evaluator
(src/evaluate.py), unchanged: validity, task precision / recall / F1 against the PMo reference, behavioural
similarity, extra and knowledge-traceable tasks, failure types, token counts and BPMNGen's auto-repairs.
Two things differ, both through the Study 2 config view (src/study2_config.py) and nothing else:
  - only the GDPR development cases and the smoke run are read
  - the legal-step scores use the GDPR silver labels (data/silver_gdpr/silver_reference_dev.json), restricted to
    the passages of the chosen retrieval version (study2_gdpr.retrieval_version), never Study 1's silver file
Nothing is written into the run folder (no evaluation.json) or into results/evaluation.csv.

inputString length check: for every case and condition, the text that BPMNGen's server route would receive as
inputString (description + blank line + knowledge label + the exact knowledge_block.txt of the case, built by
BPMNGenServerGenerator.input_string) is measured in characters against BPMNGen's limit
(bpmngen_server.input_string_max_chars, 30 000). Next to it: the harness prompt tokens counted by Ollama (meta.json)
against preflight.max_prompt_share_of_num_ctx (80%) of model.num_ctx.

Outputs in paths.gdpr_dev_smoke_dir (existing files are not overwritten unless --force):
  evaluation.csv          one row per condition per case (the columns of results/evaluation.csv)
  summary.csv             one row per condition: counts and means over the cases
  input_string_check.csv  one row per condition per case: characters, limit, prompt tokens, token limit, ok
  report.md               the tables above in readable form, plus C3's mediation labels

Run from the project root:  .venv\\Scripts\\python.exe -m src.evaluate_gdpr_dev_smoke
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.bpmngen_server_generator import BPMNGenServerGenerator
from src.config import load_config, project_path
from src.evaluate import Evaluator
from src.run_folder import RunFolder
from src.run_gdpr_dev_smoke import smoke_run_id
from src.study2_config import study2_view

OUTPUT_FILES = ("evaluation.csv", "summary.csv", "input_string_check.csv", "report.md")
SUMMARY_MEANS = ["precision", "recall", "f1", "behavioral_similarity", "n_generated_tasks", "n_extra_tasks",
                 "n_extra_knowledge_traceable", "requirement_coverage", "precision_adjusted",
                 "n_unjustified_knowledge_additions", "prompt_tokens", "output_tokens"]


def silver_for_version(silver: dict, version: str) -> dict:
    """Silver cases in the Evaluator's form ({case: {"required_steps": [...]}}), keeping only the required steps of
    the passages in this retrieval version's top 5 (the silver file labels the union of both versions)."""
    cases = {}
    for case_id, case in silver["cases"].items():
        passages = set(silver["case_versions"][case_id][version])
        cases[case_id] = {"required_steps": [s for s in case["required_steps"] if s["passage_id"] in passages]}
    return cases


def check_silver_matches_retrieval(silver: dict, frozen_path: Path, version: str) -> None:
    """The silver labels must belong to the frozen file the smoke run used (same SHA-256)."""
    key = {"hybrid": "frozen_retrieval_sha256", "rerank": "frozen_retrieval_rerank_sha256"}[version]
    actual = hashlib.sha256(frozen_path.read_bytes()).hexdigest()
    if silver[key] != actual:
        raise ValueError(f"the GDPR silver file was made for another {version} frozen file "
                         f"({key} {silver[key]} vs {actual})")


def markdown_table(table: pd.DataFrame) -> str:
    """A pandas table as a Markdown table (empty cells for missing values)."""
    cells = table.astype(object).where(table.notna(), "")
    lines = ["| " + " | ".join(map(str, table.columns)) + " |", "|" + "---|" * len(table.columns)]
    return "\n".join(lines + ["| " + " | ".join(map(str, row)) + " |" for row in cells.itertuples(index=False)])


def input_string_length(description: str, label: str, knowledge: str) -> int:
    """Characters of the inputString BPMNGen's server would receive (BPMNGenServerGenerator's own layout)."""
    return len(BPMNGenServerGenerator.input_string(SimpleNamespace(knowledge_label=label), description, knowledge))


class SmokeEvaluator:
    """Scores the Study 2 smoke run and checks the inputString length; writes only into the diagnostics folder."""

    def __init__(self, config: dict, evaluator: Evaluator | None = None):
        self.config = study2_view(config)
        gdpr, paths = self.config["study2_gdpr"], self.config["paths"]
        self.run_id = smoke_run_id(self.config)
        self.out_dir = project_path(paths["gdpr_dev_smoke_dir"])
        self.version = gdpr["retrieval_version"]
        silver = json.loads(project_path(gdpr["silver_reference_dev"]).read_text(encoding="utf-8"))
        check_silver_matches_retrieval(silver, project_path(paths["frozen_retrieval"]), self.version)
        self.evaluator = evaluator or Evaluator(self.config)
        self.evaluator.silver = silver_for_version(silver, self.version)   # never Study 1's silver file
        self.label = self.config["generator"]["knowledge_label"]
        self.max_chars = self.config["bpmngen_server"]["input_string_max_chars"]
        self.max_tokens = int(self.config["preflight"]["max_prompt_share_of_num_ctx"] * self.config["model"]["num_ctx"])

    def run(self) -> dict:
        runs = [r for r in RunFolder.find_runs(self.config) if r["run_id"] == self.run_id]
        if not runs:
            raise FileNotFoundError(f"smoke run {self.run_id!r} not found in {self.config['paths']['runs']}")
        return runs[0]

    def finished(self, run: dict) -> list[tuple[str, str]]:
        """(condition, case) pairs with a validation.json, in config order."""
        validation = self.config["paths"]["validation_file"]
        return [(condition, case_id) for condition in self.config["conditions"] if condition in run["conditions"]
                for case_id in self.config["cases"]["ids"]
                if (run["path"] / condition / case_id / validation).exists()]

    def evaluation(self, run: dict) -> pd.DataFrame:
        return pd.DataFrame([self.evaluator.evaluate_case(run, condition, case_id, save_details=False)
                             for condition, case_id in self.finished(run)])

    def length_check(self, run: dict) -> pd.DataFrame:
        paths = self.config["paths"]
        rows = []
        for condition, case_id in self.finished(run):
            case_dir = run["path"] / condition / case_id
            description = (project_path(paths["cases"]) / case_id / paths["case_description_file"]).read_text(
                encoding="utf-8")
            knowledge_path = case_dir / paths["knowledge_block_file"]
            chars = (input_string_length(description, self.label, knowledge_path.read_text(encoding="utf-8"))
                     if knowledge_path.exists() else None)
            validation = json.loads((case_dir / paths["validation_file"]).read_text(encoding="utf-8"))
            tokens = (validation.get("bpmngen") or {}).get("prompt_tokens")
            rows.append({"condition": condition, "case_id": case_id, "input_string_chars": chars,
                         "max_chars": self.max_chars, "chars_ok": None if chars is None else chars <= self.max_chars,
                         "prompt_tokens": tokens, "max_prompt_tokens": self.max_tokens,
                         "tokens_ok": None if tokens is None else tokens < self.max_tokens})
        return pd.DataFrame(rows)

    @staticmethod
    def summary(table: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for condition, group in table.groupby("condition", sort=True):
            row = {"condition": condition, "n_cases": len(group), "n_valid": int(group["valid"].sum()),
                   "n_di_stripped": int(group["di_stripped"].sum()),
                   "n_bpmnlint_valid": int(group["bpmnlint_valid"].fillna(False).astype(bool).sum())}
            for failure, count in group["failure_type"].value_counts().items():
                if failure != "none":
                    row[f"n_fail_{failure}"] = int(count)
            for column in SUMMARY_MEANS:
                values = pd.to_numeric(group[column], errors="coerce")
                row[f"mean_{column}"] = round(values.mean(), 4) if values.notna().any() else None
            row["auto_flows_added"] = int(pd.to_numeric(group["auto_flows_added"], errors="coerce").fillna(0).sum())
            rows.append(row)
        return pd.DataFrame(rows)

    def mediation_counts(self, run: dict) -> dict | None:
        path = run["path"] / "C3" / self.config["paths"]["mediation_dir"] / self.config["paths"]["mediation_summary_file"]
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def report(self, run: dict, table: pd.DataFrame, summary: pd.DataFrame, lengths: pd.DataFrame) -> str:
        shown = ["condition", "case_id", "valid", "di_stripped", "failure_type", "n_generated_tasks", "precision",
                 "recall", "f1", "behavioral_similarity", "n_extra_knowledge_traceable", "requirement_coverage",
                 "prompt_tokens", "output_tokens"]
        lines = [f"# GDPR development smoke run ({self.run_id})", "",
                 f"Generator: BPMNGen harness + {run['model']} (digest {run.get('generator_digest')}), "
                 f"Ollama {run.get('ollama_version')}. Retrieval: `{self.config['paths']['frozen_retrieval']}` "
                 f"({self.version}). Cases: {' '.join(self.config['cases']['ids'])} (development only).",
                 "Smoke run: not part of any Study 1 or Study 2 result. Silver-based columns are provisional (AI-made).",
                 "", "## Per condition", "", markdown_table(summary), "",
                 "## Per case", "", markdown_table(table[shown]), "",
                 f"## inputString length (limit {self.max_chars} characters) and prompt tokens "
                 f"(limit {self.max_tokens} = 80% of num_ctx)", "", markdown_table(lengths), ""]
        mediation = self.mediation_counts(run)
        if mediation:
            lines += ["## C3 mediation (agents v1)", "", "```json", json.dumps(mediation, indent=2), "```", ""]
        return "\n".join(lines)

    def write(self, force: bool = False) -> dict:
        existing = [f for f in OUTPUT_FILES if (self.out_dir / f).exists()]
        if existing and not force:
            raise FileExistsError(f"{self.out_dir} already has {existing}; use --force to replace them")
        run = self.run()
        table, lengths = self.evaluation(run), self.length_check(run)
        summary = self.summary(table)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        table.to_csv(self.out_dir / "evaluation.csv", index=False)
        summary.to_csv(self.out_dir / "summary.csv", index=False)
        lengths.to_csv(self.out_dir / "input_string_check.csv", index=False)
        (self.out_dir / "report.md").write_text(self.report(run, table, summary, lengths), encoding="utf-8")
        return {"evaluation": table, "summary": summary, "lengths": lengths}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the Study 2 GDPR development smoke run.")
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    args = parser.parse_args()
    try:
        result = SmokeEvaluator(load_config()).write(force=args.force)
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        sys.exit(f"Not started: {e}")
    pd.set_option("display.width", 200)
    print(result["summary"].to_string(index=False))
    print(result["lengths"].to_string(index=False))


if __name__ == "__main__":
    main()
