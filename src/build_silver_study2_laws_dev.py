"""Study 2 (more EU laws): silver labels for the combined-corpus retrieval, with exactly Study 1's silver setup.

Study 1's SilverReferenceBuilder (src/build_silver_reference.py) is used unchanged: the same SilverAnnotator
(openai/gpt-oss-120b on Groq, temperature 0, config.yaml silver section), the same prompt
(prompts/silver_annotation_prompt.txt), the same guards (every answer must come from silver.model; a saved file made
by another model or from other frozen retrieval is refused), the same quote check and the same resuming (finished
cases are kept and skipped). Only the inputs and the output differ:

  cases     study2_gdpr.development_ids (01, 06, 11, 13, 17, 19, 45)
  passages  per case, the top 5 of data/retrieval_study2/frozen_retrieval_dev_combined_rerank.json
  reuse     a case-passage pair already labelled in data/silver_gdpr/silver_reference_dev.json (same case, same
            passage id, same passage text) is NOT sent again: its record is copied unchanged and gets
            "label_source" = that file. Every other record gets "label_source" = "new". The copied records were
            made by the same annotator and prompt (checked: annotator_model and prompt_sha256 must be equal).
  output    data/silver_study2/silver_reference_dev_combined.json (never data/silver/ or data/silver_gdpr/)
  logs      results/logs/SILVER_study2_laws_dev_silver_<UTC time>.jsonl (one file per start)

Labels are SILVER (AI-made, not human-checked): provisional, never gold. They decide, with the rule in
docs/C3_V2_DEVELOPMENT.md section 5, whether the combined corpus replaces GDPR-only (printed at the end).

Run from the project root:  .venv\\Scripts\\python.exe -m src.build_silver_study2_laws_dev
"""

import copy
import json
from datetime import datetime, timezone

from src.agents.silver_annotator import SilverAnnotator
from src.build_silver_gdpr_dev import LABELS
from src.build_silver_reference import (STATUS, ModelMismatchError, SilverReferenceBuilder, create_annotator_llm,
                                        sha256)
from src.config import load_config, project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

NEW = "new"


def combined_silver_view(config: dict) -> dict:
    """A copy of the config in which Study 1's cases and frozen retrieval point to the combined development setup."""
    view = copy.deepcopy(config)
    view["cases"]["ids"] = list(config["study2_gdpr"]["development_ids"])
    view["paths"]["frozen_retrieval"] = config["study2_laws"]["frozen_dev_combined_rerank"]
    return view


def passage_texts(frozen_path) -> dict[tuple[str, str], str]:
    """{(case id, passage id): passage text} over every passage of a frozen file (top 5 and, if any, candidates)."""
    texts = {}
    for case_id, case in json.loads(frozen_path.read_text(encoding="utf-8"))["cases"].items():
        for p in case["passages"]:
            texts[(case_id, p["passage_id"])] = p["text"]
    return texts


class CombinedDevSilverBuilder(SilverReferenceBuilder):
    """Study 1's SilverReferenceBuilder on the combined top 5, reusing the labels of the GDPR-only silver file."""

    def __init__(self, config: dict, annotator: SilverAnnotator, expected_model: str | None = None):
        laws, gdpr = config["study2_laws"], config["study2_gdpr"]
        super().__init__(combined_silver_view(config), annotator,
                         project_path(laws["silver_reference_dev_combined"]), expected_model)
        if set(self.frozen) != set(self.case_ids):
            raise ValueError("the frozen file must contain exactly the development cases")
        self.reuse_file = gdpr["silver_reference_dev"]
        self.reusable = self.reusable_records(gdpr)

    def reusable_records(self, gdpr: dict) -> dict[tuple[str, str], dict]:
        """{(case, passage): record} of the GDPR-only silver file whose passage text equals the text here."""
        old = json.loads(project_path(self.reuse_file).read_text(encoding="utf-8"))
        if old["prompt_sha256"] != sha256(self.prompt_path):
            raise ValueError(f"{self.reuse_file} was made with another silver prompt; its labels cannot be reused")
        if self.expected_model and old["annotator_model"] != self.expected_model:
            raise ModelMismatchError(f"{self.reuse_file} was made by {old['annotator_model']!r}, not "
                                     f"{self.expected_model!r}; its labels cannot be reused")
        old_texts = {}
        for key in ("frozen_dev_hybrid_restricted", "frozen_dev_rerank_restricted"):
            old_texts.update(passage_texts(project_path(gdpr[key])))
        reusable = {}
        for case_id, case in old["cases"].items():
            for record in case["passages"]:
                key = (case_id, record["passage_id"])
                new = next((p for p in self.frozen.get(case_id, {}).get("passages", [])
                            if p["passage_id"] == record["passage_id"]), None)
                if new is not None and old_texts.get(key) == new["text"] and record["label"] != "annotation_failed":
                    reusable[key] = dict(record, label_source=self.reuse_file,
                                         copied_annotated_at=case["annotated_at"])
        return reusable

    def annotate_case(self, case_id: str) -> dict:
        """Label only the passages without a reusable label (parent code), then merge in rank order."""
        all_passages = sorted(self.frozen[case_id]["passages"], key=lambda p: p["rank"])
        to_label = [p for p in all_passages if (case_id, p["passage_id"]) not in self.reusable]
        self.frozen[case_id] = {"passages": to_label}
        try:
            case = super().annotate_case(case_id)
        finally:
            self.frozen[case_id] = {"passages": all_passages}
        labelled = {r["passage_id"]: dict(r, label_source=NEW) for r in case["passages"]}
        records = [labelled.get(p["passage_id"]) or self.reusable[(case_id, p["passage_id"])] for p in all_passages]
        case["passages"] = records
        case["required_steps"] = [{"passage_id": r["passage_id"], **s} for r in records for s in r["required_steps"]]
        case["possible_steps"] = [{"passage_id": r["passage_id"], **s} for r in records for s in r["possible_steps"]]
        case["n_new"], case["n_copied"] = len(to_label), len(all_passages) - len(to_label)
        return case

    def load(self) -> dict:
        data = super().load()
        data["study"] = "Study 2 (GDPR Chapters I-V + ECD, TPWC, CCD, OSH), development cases only"
        data["frozen_retrieval_file"] = self.config["paths"]["frozen_retrieval"]
        data["labels_reused_from"] = self.reuse_file
        return data


def label_counts(data: dict) -> dict[str, dict[str, int]]:
    """{case id: {label: number of its top-5 passages with that label}} (other labels, e.g. failed, as 'other')."""
    counts = {}
    for case_id, case in sorted(data["cases"].items()):
        labels = [p["label"] for p in case["passages"]]
        counts[case_id] = {label: labels.count(label) for label in LABELS}
        other = len(labels) - sum(counts[case_id].values())
        if other:
            counts[case_id]["other"] = other
    return counts


def decide(data: dict, gdpr_only_applicable: int) -> tuple[str, str]:
    """The rule of docs/C3_V2_DEVELOPMENT.md section 5: (corpus Study 2 uses, reason)."""
    applicable = sum(c["applicable"] for c in label_counts(data).values())
    if applicable > gdpr_only_applicable:
        return "combined", f"combined has {applicable} silver-applicable passages, higher than {gdpr_only_applicable}"
    return "gdpr_only", (f"combined has {applicable} silver-applicable passages, "
                         f"{'equal to' if applicable == gdpr_only_applicable else 'lower than'} "
                         f"{gdpr_only_applicable} (not higher)")


def report(data: dict, gdpr_only_applicable: int) -> str:
    counts = label_counts(data)
    lines = [f"{'case':<6}" + "".join(f"{label:>16}" for label in LABELS)]
    for case_id, case_counts in counts.items():
        lines.append(f"{case_id:<6}" + "".join(f"{case_counts[label]:>16}" for label in LABELS))
    totals = {label: sum(c.get(label, 0) for c in counts.values()) for label in LABELS + ("other",)}
    lines.append(f"{'total':<6}" + "".join(f"{totals[label]:>16}" for label in LABELS)
                 + (f"   other: {totals['other']}" if totals["other"] else ""))
    corpus, reason = decide(data, gdpr_only_applicable)
    lines.append(f"\nRule (docs/C3_V2_DEVELOPMENT.md section 5): Study 2 uses {corpus}; {reason}")
    return "\n".join(lines)


def main(config: dict | None = None, argv: list[str] | None = None) -> None:
    config = config or load_config()
    laws = config["study2_laws"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = RunLogger(project_path(config["paths"]["logs"]), laws["silver_log_condition"], f"silver_{stamp}")
    llm = create_annotator_llm(config)
    expected_model = None if config["model"]["provider"] == "mock" else config["silver"]["model"]
    try:
        builder = CombinedDevSilverBuilder(config, SilverAnnotator(llm, logger), expected_model)
        data = builder.build()
    except LLMUnavailableError as e:
        raise SystemExit(f"Stopped (API error): {e}\nFinished cases are saved; run the same command again later.")
    except ModelMismatchError as e:
        raise SystemExit(f"Stopped (model mismatch, this case was NOT saved): {e}")
    builder.save(data)
    n_new = sum(c.get("n_new", 0) for c in data["cases"].values())
    n_copied = sum(c.get("n_copied", 0) for c in data["cases"].values())
    print(f"Combined development silver: {len(data['cases'])} cases, {n_new} pairs labelled now, {n_copied} copied "
          f"from {builder.reuse_file}; annotator {data.get('annotator_provider')}/{data['annotator_model']}, "
          f"annotated on {', '.join(data.get('annotation_dates') or [])}")
    print(report(data, laws["gdpr_only_applicable"]))
    print(f"\nSaved {builder.output_path}  ({STATUS})")


if __name__ == "__main__":
    main()
