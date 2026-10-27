"""Retrieval evaluation for RAG v2 (Study 2): are the target passages of a case retrieved?

Input: a JSON file with a list of items, each a case (or variant case, e.g. "01.1") and its target passage ids:
  {"items": [{"case_id": "01.1", "targets": ["GDPR-Art13-1"]}, ...]}
The case's description is read from data/cases/<case_id>/ (config.yaml paths.cases).

Every (case, target passage) pair is one evaluated item:
  in_top_k        the target is one of the top 5 (reranker.top_k) passages
  rank            its rank among ALL reranked candidates (1 = best), or None if it is not a candidate
  in_candidates   it is in the candidate set (hybrid top 20, plus siblings if sibling expansion is ON)
  via_expansion   it entered the candidates through sibling expansion (None when expansion is OFF)
Summary: hit rate @5 = items with in_top_k / all items.

evaluate() only counts (no model; tested in tests/test_rag_v2.py). main() runs RagV2Retriever (src/rag_v2.py) on the
Study 2 corpus and writes report.json into a new folder under rag_v2.evaluation_dir. Nothing is frozen.

Run from the project root (not run yet; the retrieval test set and criteria come first):
  .venv\\Scripts\\python.exe -m src.evaluate_retrieval_v2 --items <items.json> [--expansion on|off]
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config, project_path


def evaluate(retrievals: dict[str, dict], items: list[dict], top_k: int) -> dict:
    """retrievals: case id -> the case result of RagV2Retriever.retrieve (keys "passages", "candidates").
    Returns {"items": [one row per (case, target)], "summary": {...}}."""
    rows = []
    for item in items:
        case = retrievals[item["case_id"]]
        top = [p["passage_id"] for p in case["passages"]][:top_k]
        by_id = {c["passage_id"]: c for c in case["candidates"]}
        for target in item["targets"]:
            candidate = by_id.get(target)
            rows.append({"case_id": item["case_id"], "target": target,
                         "in_top_k": target in top,
                         "rank": candidate["rank"] if candidate else None,
                         "in_candidates": candidate is not None,
                         "via_expansion": candidate.get("via_expansion") if candidate else None})
    hits = sum(r["in_top_k"] for r in rows)
    summary = {"n_items": len(rows), "n_in_top_k": hits,
               "n_in_candidates": sum(r["in_candidates"] for r in rows),
               f"hit_rate_at_{top_k}": round(hits / len(rows), 4) if rows else None}
    return {"items": rows, "summary": summary}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG v2 retrieval against target passages.")
    parser.add_argument("--items", required=True, help="JSON file with the items (case_id + targets)")
    parser.add_argument("--expansion", choices=["on", "off"], help="sibling expansion (default: config.yaml)")
    args = parser.parse_args(argv)

    from src.rag_v2 import RagV2Retriever, corpus_view   # loads the models only when really run

    config = load_config()
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))["items"]
    expansion = None if args.expansion is None else args.expansion == "on"
    retriever = RagV2Retriever(corpus_view(config), sibling_expansion=expansion)
    case_ids = list(dict.fromkeys(item["case_id"] for item in items))
    retrievals = {case_id: retriever.retrieve_case_reranked(case_id) for case_id in case_ids}
    top_k = config["reranker"]["top_k"]
    report = evaluate(retrievals, items, top_k)
    report["settings"] = {"items_file": args.items, "sibling_expansion": retriever.sibling_expansion,
                          "corpus": config["study2_corpus"]["passages"], "retrieval": config["retrieval"],
                          "reranker": config["reranker"]}
    report["retrievals"] = retrievals

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = project_path(config["rag_v2"]["evaluation_dir"]) / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in report["items"]:
        print(f"{row['case_id']:<6}{row['target']:<20}top{top_k}={'yes' if row['in_top_k'] else 'no ':<4}"
              f"rank={row['rank']}  candidate={'yes' if row['in_candidates'] else 'no'}")
    print(f"\nhit rate @{top_k}: {report['summary'][f'hit_rate_at_{top_k}']}  ->  {out_dir / 'report.json'}")


if __name__ == "__main__":
    main()
