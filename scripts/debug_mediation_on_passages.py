"""Mediation of GIVEN passages for ONE case (variant 01.1), no retrieval and no BPMN.

It uses scripts/debug_single_case.py by import (debug_run, make_llm, load_answer_key, ...), so every passage goes through
OrchestratorV2.mediate_passage with the same agents, prompts, settings and digest check as debug_single_case.py. The only
difference: the passages are looked up by ID in the frozen Study 2 corpus (its SHA-256 must equal the corpus manifest)
instead of being read from the frozen retrieval. Files 01-03 of a run folder therefore only say that the passages were given.

Output: results/debug/01.1/med_<label>_run_<n>/ with the same stage files as debug_single_case.py.

    .venv\\Scripts\\python.exe -m scripts.debug_mediation_on_passages --variant 01.1 --label oracle --passages GDPR-Art13-1 --runs 3
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from scripts.debug_single_case import debug_run, load_answer_key, make_llm
from src.config import load_config, project_path


def load_corpus_passages(config: dict, ids: list[str]) -> tuple[list[dict], str]:
    """The passages with these IDs (in the given order) from the frozen corpus, and the corpus SHA-256."""
    path = project_path(config["study2_corpus"]["passages"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads(project_path(config["study2_corpus"]["manifest"]).read_text(encoding="utf-8"))
    if sha != manifest["passages_sha256"]:
        raise RuntimeError(f"{path} differs from its manifest (frozen corpus changed): {sha}")
    by_id = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_id[row["id"]] = row
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"not in the corpus: {missing}")
    return [{"rank": n, "passage_id": i, "text": by_id[i]["text"], "rerank_score": None, "hybrid_rank": None}
            for n, i in enumerate(ids, 1)], sha


def given_case(passages: list[dict], description: str) -> dict:
    """A 'case' in the shape debug_run expects, with the given passages and no retrieval lists."""
    return {"queries": [description], "reranker_queries": [description], "candidates": [], "passages": passages}


def next_med_dir(case_dir: Path, label: str) -> Path:
    """results/debug/<case>/med_<label>_run_<n> with the next free n."""
    prefix = f"med_{label}_run_"
    numbers = [int(p.name[len(prefix):]) for p in case_dir.glob(prefix + "*") if p.name[len(prefix):].isdigit()]
    return case_dir / f"{prefix}{max(numbers, default=0) + 1}"


def reason(record: dict) -> str:
    """Why a passage did not end Applicable (empty for Applicable)."""
    if record["label"] == "Applicable":
        return ""
    if record["failed_step"]:
        return f"failed at {record['failed_step']}"
    if record["label"] == "Irrelevant":
        return str((record["relevance"] or {}).get("reason") or "not relevant")
    return str((record["resolution"] or {}).get("reason") or "")


def summary_text(label: str, runs: list[dict]) -> str:
    lines = [f"MEDIATION ON GIVEN PASSAGES, set {label}, case 01.1", ""]
    for run in runs:
        lines.append(f"{run['run']}:")
        for r in run["records"]:
            why = reason(r)
            lines.append(f"  {r['passage_id']:<16} {r['label']}" + (f"  ({why})" if why else ""))
            if r["requirement"] is not None and r["label"] == "Applicable":
                lines.append(f"      requirement: {r['requirement'].get('requirement')}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mediate given passages of variant 01.1 (no retrieval).")
    parser.add_argument("--variant", required=True, help="only 01.1 is supported")
    parser.add_argument("--passages", required=True, help="comma-separated passage IDs")
    parser.add_argument("--label", required=True, help="name of the set, used in the folder names")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    if args.variant != "01.1":
        parser.error("only variant 01.1 is supported")
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    config = load_config()
    ids = [i.strip() for i in args.passages.split(",") if i.strip()]
    passages, corpus_sha = load_corpus_passages(config, ids)
    key = load_answer_key(config)
    description = (project_path(config["paths"]["cases"]) / args.variant / config["paths"]["case_description_file"]
                   ).read_text(encoding="utf-8")
    try:
        llm, llm_info = make_llm(config)
    except Exception as e:
        sys.exit(f"Not started: {e}")
    run_info = {"case_id": args.variant, "mode": "mediation on given passages (no retrieval)", "label": args.label,
                "given_passage_ids": ids, "corpus_file": config["study2_corpus"]["passages"],
                "corpus_sha256": corpus_sha, "c3_version": "v2", **llm_info}

    case_dir = project_path(config["paths"]["runs"]).parent / "debug" / args.variant
    case = given_case(passages, description)
    runs = []
    for _ in range(args.runs):
        run_dir = next_med_dir(case_dir, args.label)
        print(f"{run_dir} ...", flush=True)
        runs.append(debug_run(config, case, description, key, llm, run_dir, run_info))
    text = summary_text(args.label, runs)
    for run in runs:
        (case_dir / run["run"] / "summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
