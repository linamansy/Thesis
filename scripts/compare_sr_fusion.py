"""Compare four ways to merge the per-step lists of RAG step routing (SR) on 01.1. NO LLM, NO retrieval: it reads the
saved S3 lists (03_step_rankings.json) of results/debug/01.1/rag_sr_run_<n>/ and recomputes the top 5.

PASS RULE (fixed before the first run of this script): GDPR-Art13-1 is in the top 5 of the rule.

Fusion rules (top 5 = reranker.top_k):
  1 rrf          RRF over the step lists, k = retrieval.rrf_k (60). The current SR merge: it must reproduce the saved
                 04_merged_top5.json exactly (ids and scores); if it does not, the script stops.
  2 combmax      score of a paragraph = its highest reranker score over the steps whose list holds it; ties are
                 broken by the RRF score (rule 1), then by passage id.
  3 rrf_cap2     rule 1's order, but at most 2 paragraphs per article: a paragraph whose article already has 2
                 paragraphs above it is skipped.
  4 combmax_cap2 rule 2's order with the same cap.
The rank of GDPR-Art13-1 is its position in the full order of the rule (after the cap for rules 3 and 4); "-" = it is in
no step list, or was skipped by the cap. Reranker scores come from different step queries and are only roughly
comparable (rules 2 and 4).

Run from the project root:  .venv\\Scripts\\python.exe -m scripts.compare_sr_fusion
"""

import json

from src.config import load_config, project_path
from src.rag_v3_steps import article_id_of, merge_rankings

TARGET = "GDPR-Art13-1"
MAX_PER_ARTICLE = 2
RULES = ("rrf", "combmax", "rrf_cap2", "combmax_cap2")


def step_lists(s3: dict) -> dict[str, list[dict]]:
    """{step id: its ranked rows (passage_id, rerank_score), best first}."""
    return {step: v["ranking"] for step, v in s3["per_step"].items()}


def rrf_order(lists: dict[str, list[dict]], rrf_k: int) -> list[dict]:
    """Rule 1: the full RRF order as [{passage_id, rrf_score}]."""
    full = merge_rankings({s: [r["passage_id"] for r in rows] for s, rows in lists.items()}, rrf_k, 10 ** 6)
    return [{"passage_id": row["passage_id"], "rrf_score": row["rrf_score"]} for row in full]


def combmax_order(lists: dict[str, list[dict]], rrf_k: int) -> list[dict]:
    """Rule 2: highest reranker score over the steps; ties by RRF score, then passage id."""
    best = {}
    for rows in lists.values():
        for r in rows:
            best[r["passage_id"]] = max(best.get(r["passage_id"], r["rerank_score"]), r["rerank_score"])
    rrf = {row["passage_id"]: row["rrf_score"] for row in rrf_order(lists, rrf_k)}
    order = sorted(best, key=lambda pid: (-best[pid], -rrf[pid], pid))
    return [{"passage_id": pid, "max_rerank_score": best[pid], "rrf_score": rrf[pid]} for pid in order]


def cap_per_article(order: list[dict], limit: int = MAX_PER_ARTICLE) -> list[dict]:
    """Keep the order, skip a paragraph whose article already has `limit` paragraphs above it."""
    seen, kept = {}, []
    for row in order:
        article = article_id_of(row["passage_id"])
        if seen.get(article, 0) < limit:
            seen[article] = seen.get(article, 0) + 1
            kept.append(row)
    return kept


def fusion_orders(lists: dict[str, list[dict]], rrf_k: int) -> dict[str, list[dict]]:
    """The full order of every rule."""
    rrf, combmax = rrf_order(lists, rrf_k), combmax_order(lists, rrf_k)
    return {"rrf": rrf, "combmax": combmax, "rrf_cap2": cap_per_article(rrf), "combmax_cap2": cap_per_article(combmax)}


def evaluate(order: list[dict], top_k: int) -> dict:
    ids = [row["passage_id"] for row in order]
    rank = ids.index(TARGET) + 1 if TARGET in ids else None
    return {"top5": ids[:top_k], "rank": rank, "pass": TARGET in ids[:top_k]}


def check_reproduction(run_dir, orders: dict[str, list[dict]], top_k: int) -> None:
    """Rule 1 must equal the saved S4 result exactly (passage ids and RRF scores)."""
    saved = json.loads((run_dir / "04_merged_top5.json").read_text(encoding="utf-8"))["passages"]
    mine = orders["rrf"][:top_k]
    if [(s["passage_id"], s["rrf_score"]) for s in saved] != [(m["passage_id"], m["rrf_score"]) for m in mine]:
        raise SystemExit(f"STOP: rule 1 does not reproduce {run_dir.name}/04_merged_top5.json")


def run_dirs(debug_dir):
    dirs = [p for p in debug_dir.glob("rag_sr_run_*") if p.name.rsplit("_", 1)[-1].isdigit()]
    return sorted(dirs, key=lambda p: int(p.name.rsplit("_", 1)[-1]))


def table(results: dict) -> str:
    lines = [f"SR fusion comparison, case 01.1. Pass rule: {TARGET} in the top 5. Cap = {MAX_PER_ARTICLE} per article.",
             "", f"{'rule':<13}{'run':<6}{'top 5':<76}{'rank':<6}result", "-" * 107]
    for rule in RULES:
        for run, per_rule in results.items():
            r = per_rule[rule]
            lines.append(f"{rule:<13}{run.rsplit('_', 1)[-1]:<6}{', '.join(r['top5']):<76}{r['rank'] or '-':<6}"
                         f"{'PASS' if r['pass'] else 'FAIL'}")
        lines.append("")
    lines.append("Passes: " + ", ".join(f"{rule} {sum(per[rule]['pass'] for per in results.values())}/{len(results)}"
                                        for rule in RULES))
    return "\n".join(lines) + "\n"


def main() -> None:
    config = load_config()
    top_k, rrf_k = config["reranker"]["top_k"], config["retrieval"]["rrf_k"]
    debug_dir = project_path(config["paths"]["runs"]).parent / "debug" / "01.1"
    results = {}
    for run_dir in run_dirs(debug_dir):
        s3 = json.loads((run_dir / "03_step_rankings.json").read_text(encoding="utf-8"))
        orders = fusion_orders(step_lists(s3), rrf_k)
        check_reproduction(run_dir, orders, top_k)
        results[run_dir.name] = {rule: evaluate(order, top_k) for rule, order in orders.items()}
    if not results:
        raise SystemExit(f"No rag_sr_run_<n> folders in {debug_dir}")
    print("Rule 1 reproduces every saved 04_merged_top5.json exactly.\n")
    print(table(results))


if __name__ == "__main__":
    main()
