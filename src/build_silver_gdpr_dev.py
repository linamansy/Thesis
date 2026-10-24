"""Study 2: silver labels for the GDPR development cases, with exactly Study 1's silver setup.

Study 1's SilverReferenceBuilder (src/build_silver_reference.py) is used unchanged: the same SilverAnnotator
(openai/gpt-oss-120b on Groq, temperature 0, config.yaml silver section), the same prompt
(prompts/silver_annotation_prompt.txt), the same guards (every answer must come from silver.model, a saved file
made by another model or from other frozen retrieval is refused), the same quote check, and the same resuming
(finished cases are kept and skipped). Only the inputs and the output differ:

  cases     study2_gdpr.development_ids (01, 06, 11, 13, 17, 19, 45)
  passages  per case, the UNION of the top 5 of the two frozen versions
            (frozen_retrieval_dev_ch1-5_hybrid.json and frozen_retrieval_dev_ch1-5_rerank.json):
            the hybrid passages first (by rank), then the rerank-only passages (by rank). A passage in both
            versions is labelled once and its label counts for both.
  output    data/silver_gdpr/silver_reference_dev.json (never data/silver/). The file also stores the paths and
            SHA-256 of both frozen files, and per case which passage ids are in which version.
  logs      results/logs/SILVER_gdpr_dev_silver_<UTC time>.jsonl (one file per start)

Labels are SILVER (AI-made, not human-checked): provisional, never gold. They are used to choose the retrieval
version with the rule in docs/C3_V2_DEVELOPMENT.md section 4 (python -m src.build_silver_gdpr_dev prints it).

Run from the project root:  .venv\\Scripts\\python.exe -m src.build_silver_gdpr_dev
"""

import copy
import json
from datetime import datetime, timezone

from src.agents.silver_annotator import SilverAnnotator
from src.build_silver_reference import (STATUS, ModelMismatchError, SilverReferenceBuilder, create_annotator_llm,
                                        sha256)
from src.config import load_config, project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger

VERSIONS = ("hybrid", "rerank")
LABELS = ("applicable", "indeterminate", "not_applicable", "irrelevant")


def gdpr_silver_view(config: dict) -> dict:
    """A copy of the config in which Study 1's cases and frozen retrieval point to the GDPR development setup."""
    view = copy.deepcopy(config)
    gdpr = config["study2_gdpr"]
    view["cases"]["ids"] = list(gdpr["development_ids"])
    view["paths"]["frozen_retrieval"] = gdpr["frozen_dev_hybrid_restricted"]
    return view


def version_passages(frozen_paths: dict) -> dict[str, dict[str, list[dict]]]:
    """{version: {case id: its top-5 passages (rank, passage_id, text, ...)}} from the frozen files."""
    result = {}
    for version, path in frozen_paths.items():
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        result[version] = {case_id: sorted(case["passages"], key=lambda p: p["rank"]) for case_id, case in cases.items()}
    return result


def union_passages(per_version: dict[str, dict[str, list[dict]]], case_id: str) -> list[dict]:
    """The case's passages of all versions, each once: hybrid first, then the new ones of rerank; ranked 1, 2, ..."""
    union, seen = [], set()
    for version in VERSIONS:
        for p in per_version[version][case_id]:
            if p["passage_id"] not in seen:
                seen.add(p["passage_id"])
                union.append({"rank": len(union) + 1, "passage_id": p["passage_id"], "text": p["text"]})
    return union


class GdprDevSilverBuilder(SilverReferenceBuilder):
    """Study 1's SilverReferenceBuilder on the union of the two GDPR development retrieval versions."""

    def __init__(self, config: dict, annotator: SilverAnnotator, expected_model: str | None = None):
        gdpr = config["study2_gdpr"]
        super().__init__(gdpr_silver_view(config), annotator, project_path(gdpr["silver_reference_dev"]),
                         expected_model)
        self.frozen_files = {"hybrid": gdpr["frozen_dev_hybrid_restricted"],
                             "rerank": gdpr["frozen_dev_rerank_restricted"]}
        self.frozen_paths = {v: project_path(f) for v, f in self.frozen_files.items()}
        self.per_version = version_passages(self.frozen_paths)
        if any(set(cases) != set(self.case_ids) for cases in self.per_version.values()):
            raise ValueError("the frozen files must contain exactly the development cases")
        # What the parent's annotate_case reads: per case, the passages to label (each pair once).
        self.frozen = {case_id: {"passages": union_passages(self.per_version, case_id)} for case_id in self.case_ids}

    def load(self) -> dict:
        """The parent's load (checks the hybrid file and the model), plus the same check for the rerank file."""
        data = super().load()
        rerank_sha = sha256(self.frozen_paths["rerank"])
        if data.setdefault("frozen_retrieval_rerank_sha256", rerank_sha) != rerank_sha:
            raise ValueError("the rerank frozen retrieval changed since the silver labels were made; "
                             "build a new file instead of mixing them")
        data["study"] = "Study 2 (GDPR), development cases only"
        data["frozen_retrieval_files"] = self.frozen_files  # frozen_retrieval_sha256 = hybrid file
        data["case_versions"] = {case_id: {v: [p["passage_id"] for p in self.per_version[v][case_id]] for v in VERSIONS}
                                 for case_id in self.case_ids}
        return data


def label_counts(data: dict, version: str) -> dict[str, dict[str, int]]:
    """{case id: {label: number of that case's top-5 passages in this version with the label}}."""
    counts = {}
    for case_id, ids in sorted(data["case_versions"].items()):
        labels = {p["passage_id"]: p["label"] for p in data["cases"][case_id]["passages"]}
        version_labels = [labels[pid] for pid in ids[version]]
        counts[case_id] = {label: version_labels.count(label) for label in LABELS}
        other = len(version_labels) - sum(counts[case_id].values())
        if other:
            counts[case_id]["other"] = other  # e.g. annotation_failed
    return counts


def totals(counts: dict[str, dict[str, int]]) -> dict[str, int]:
    result = {}
    for case_counts in counts.values():
        for label, n in case_counts.items():
            result[label] = result.get(label, 0) + n
    return result


def choose_version(data: dict) -> tuple[str, str]:
    """The rule of docs/C3_V2_DEVELOPMENT.md section 4: (winning version, reason)."""
    t = {v: totals(label_counts(data, v)) for v in VERSIONS}
    applicable = {v: t[v]["applicable"] for v in VERSIONS}
    irrelevant = {v: t[v]["irrelevant"] for v in VERSIONS}
    if applicable["hybrid"] != applicable["rerank"]:
        winner = max(VERSIONS, key=lambda v: applicable[v])
        return winner, f"step 1: more silver-applicable passages ({applicable[winner]} vs " \
                       f"{min(applicable.values())})"
    if irrelevant["hybrid"] != irrelevant["rerank"]:
        winner = min(VERSIONS, key=lambda v: irrelevant[v])
        return winner, f"step 2: applicable tied at {applicable['hybrid']}; fewer silver-irrelevant passages " \
                       f"({irrelevant[winner]} vs {max(irrelevant.values())})"
    return "hybrid", f"step 3: tied on applicable ({applicable['hybrid']}) and irrelevant ({irrelevant['hybrid']})"


def report(data: dict) -> str:
    lines = []
    for version in VERSIONS:
        counts = label_counts(data, version)
        lines.append(f"\nVersion {version}")
        lines.append(f"{'case':<6}" + "".join(f"{label:>16}" for label in LABELS))
        for case_id, case_counts in counts.items():
            lines.append(f"{case_id:<6}" + "".join(f"{case_counts[label]:>16}" for label in LABELS))
        t = totals(counts)
        lines.append(f"{'total':<6}" + "".join(f"{t[label]:>16}" for label in LABELS)
                     + (f"   other: {t['other']}" if t.get("other") else ""))
    winner, reason = choose_version(data)
    lines.append(f"\nRule (docs/C3_V2_DEVELOPMENT.md section 4): {winner} wins, {reason}")
    return "\n".join(lines)


def main() -> None:
    config = load_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = RunLogger(project_path(config["paths"]["logs"]), config["study2_gdpr"]["silver_log_condition"],
                       f"silver_{stamp}")
    llm = create_annotator_llm(config)
    expected_model = None if config["model"]["provider"] == "mock" else config["silver"]["model"]
    try:
        builder = GdprDevSilverBuilder(config, SilverAnnotator(llm, logger), expected_model)
        data = builder.build()
    except LLMUnavailableError as e:
        raise SystemExit(f"Stopped (API error): {e}\nFinished cases are saved; run the same command again later.")
    except ModelMismatchError as e:
        raise SystemExit(f"Stopped (model mismatch, this case was NOT saved): {e}")
    builder.save(data)  # the header written by load() (versions, rerank checksum) also when nothing was new
    n_pairs = sum(len(c["passages"]) for c in data["cases"].values())
    print(f"GDPR development silver: {len(data['cases'])} cases, {n_pairs} case-passage pairs, annotator "
          f"{data.get('annotator_provider')}/{data['annotator_model']}, annotated on "
          f"{', '.join(data.get('annotation_dates') or [])}")
    print(report(data))
    print(f"\nSaved {builder.output_path}  ({STATUS})")


if __name__ == "__main__":
    main()
