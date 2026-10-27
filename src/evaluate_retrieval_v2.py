"""Retrieval evaluation for RAG v2 (Study 2): are the target passages of a case retrieved?

Input: a JSON file with a list of items, each a case (or variant case, e.g. "01.1") and its target passage ids:
  {"items": [{"case_id": "01.1", "targets": ["GDPR-Art13-1"]}, ...]}
The case's description is read from data/cases/<case_id>/ (config.yaml paths.cases).

Every (case, target passage) pair is one evaluated item:
  in_top_k        the target is one of the top 5 (reranker.top_k) passages
  rank            its rank among ALL reranked candidates (1 = best), or None if it is not a candidate
  in_candidates   it is in the candidate set (hybrid top 20, plus siblings if sibling expansion is ON)
  via_expansion   it entered the candidates through sibling expansion (None when expansion is OFF)
Summary: hit rate @5 = items with in_top_k / all items (M1 of docs/RAG_V2_CRITERIA.md section 2).
Per variant (variant_hits): a hit if ANY of its targets (accepted target ids) is in the top 5, and the best rank;
for the 8 variants (one target each) this equals the item count; the held-out set (section 7.8) may accept several.

M2, expected-law share (criteria section 2): for each real case given with --m2-cases, the share of its top 5
passages whose law (passage id prefix, e.g. "CRD") is an expected law of the case (config.yaml rag_v2.expected_laws),
and the mean over those cases.

evaluate() and expected_law_share() only count (no model; tested in tests/test_rag_v2.py). main() runs RagV2Retriever
(src/rag_v2.py) on the Study 2 corpus, or with --frozen only reads a frozen file (no model), and writes report.json
into a new folder under rag_v2.evaluation_dir. Nothing is frozen here.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.evaluate_retrieval_v2 --items <items.json> --m2-cases 01 06 ... [--expansion on|off]
  .venv\\Scripts\\python.exe -m src.evaluate_retrieval_v2 --frozen <frozen.json> --m2-cases 03 05 ...
  .venv\\Scripts\\python.exe -m src.evaluate_retrieval_v2 --config A|B|C|D --items <items.json> --m2-cases ...
    (extra round, criteria section 7: src/rag_v2_extra.py; B and D call qwen3:8b once per new description)
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


def variant_hits(report: dict) -> dict:
    """Per variant: hit = any of its targets in the top k; best rank over its targets. Plus the number of hits."""
    per_variant = {}
    for row in report["items"]:
        v = per_variant.setdefault(row["case_id"], {"hit": False, "best_rank": None, "targets": {}})
        v["hit"] = v["hit"] or row["in_top_k"]
        v["targets"][row["target"]] = row["rank"]
        if row["rank"] is not None and (v["best_rank"] is None or row["rank"] < v["best_rank"]):
            v["best_rank"] = row["rank"]
    return {"per_variant": per_variant, "n_variants": len(per_variant),
            "n_hit": sum(v["hit"] for v in per_variant.values())}


def law_of(passage_id: str) -> str:
    """The law of a passage = its id prefix ("CRD-Art9-1" -> "CRD")."""
    return passage_id.split("-", 1)[0]


def expected_law_share(retrievals: dict[str, dict], expected_laws: dict[str, list[str]], case_ids: list[str],
                       top_k: int) -> dict:
    """M2: per case, the share of its top_k passages from an expected law; and the mean over the cases."""
    per_case = {}
    for case_id in case_ids:
        top = [p["passage_id"] for p in retrievals[case_id]["passages"]][:top_k]
        laws = [law_of(pid) for pid in top]
        n_expected = sum(law in expected_laws[case_id] for law in laws)
        per_case[case_id] = {"top_k": top, "laws": laws, "expected_laws": expected_laws[case_id],
                             "n_expected": n_expected, "share": round(n_expected / len(top), 4)}
    shares = [c["n_expected"] / len(c["top_k"]) for c in per_case.values()]
    return {"per_case": per_case, "mean": round(sum(shares) / len(shares), 4) if shares else None}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG v2 retrieval against target passages.")
    parser.add_argument("--items", help="JSON file with the items (case_id + targets), for M1")
    parser.add_argument("--m2-cases", nargs="+", default=[], help="real case ids for M2 (expected-law share)")
    parser.add_argument("--expansion", choices=["on", "off"], help="sibling expansion (default: config.yaml)")
    parser.add_argument("--frozen", help="read the retrievals from this frozen file instead of running retrieval")
    parser.add_argument("--config", choices=["A", "B", "C", "D"], help="extra-round config (criteria section 7)")
    args = parser.parse_args(argv)
    if not args.items and not args.m2_cases:
        parser.error("give --items and/or --m2-cases")

    config = load_config()
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))["items"] if args.items else []
    case_ids = list(dict.fromkeys([item["case_id"] for item in items] + args.m2_cases))
    if args.frozen:
        frozen = json.loads(Path(args.frozen).read_text(encoding="utf-8"))
        retrievals = {case_id: frozen["cases"][case_id] for case_id in case_ids}
        expansion = frozen["rag_v2"]["sibling_expansion"]
        extra = None
    elif args.config:
        from src.rag_v2_extra import build   # loads the models (and qwen3:8b for B, D) only when really run
        retriever = build(config, args.config)
        expansion, extra = False, retriever.describe()
        retrievals = {case_id: retriever.retrieve_case_reranked(case_id) for case_id in case_ids}
    else:
        from src.rag_v2 import RagV2Retriever, corpus_view   # loads the models only when really run
        expansion = None if args.expansion is None else args.expansion == "on"
        retriever = RagV2Retriever(corpus_view(config), sibling_expansion=expansion)
        expansion, extra = retriever.sibling_expansion, None
        retrievals = {case_id: retriever.retrieve_case_reranked(case_id) for case_id in case_ids}
    top_k = config["reranker"]["top_k"]
    report = evaluate(retrievals, items, top_k)
    report["variants"] = variant_hits(report)
    if args.m2_cases:
        report["m2"] = expected_law_share(retrievals, config["rag_v2"]["expected_laws"], args.m2_cases, top_k)
    report["settings"] = {"items_file": args.items, "m2_cases": args.m2_cases, "frozen_file": args.frozen,
                          "sibling_expansion": expansion, "extra_round_config": extra, "corpus": config["study2_corpus"]["passages"],
                          "retrieval": config["retrieval"], "reranker": config["reranker"]}
    report["retrievals"] = retrievals

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = project_path(config["rag_v2"]["evaluation_dir"]) / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in report["items"]:
        print(f"{row['case_id']:<6}{row['target']:<20}top{top_k}={'yes' if row['in_top_k'] else 'no ':<4}"
              f"rank={row['rank']}  candidate={'yes' if row['in_candidates'] else 'no'}")
    if items:
        for case_id, v in report["variants"]["per_variant"].items():
            print(f"variant {case_id:<6}hit={'yes' if v['hit'] else 'no '} best rank={v['best_rank']}")
        print(f"\nM1 variants hit @{top_k}: {report['variants']['n_hit']}/{report['variants']['n_variants']}")
        print(f"M1 hit rate @{top_k}: {report['summary']['n_in_top_k']}/{report['summary']['n_items']} "
              f"({report['summary'][f'hit_rate_at_{top_k}']})")
    if args.m2_cases:
        for case_id, row in report["m2"]["per_case"].items():
            print(f"M2 {case_id:<4}{row['share']:<6}{' '.join(row['top_k'])}")
        print(f"M2 mean: {report['m2']['mean']}")
    print(f"config: {args.config or '-'}  sibling expansion: {expansion}  ->  {out_dir / 'report.json'}")


if __name__ == "__main__":
    main()
