"""Offline test of parent-document expansion on saved RAG step routing (SR) runs. NO LLM, NO retrieval.

For each run it reads the saved S3 step lists (results/debug/<variant>/rag_sr_run_<n>/03_step_rankings.json), builds
the CombMAX order (scripts/compare_sr_fusion.combmax_order, unchanged) and takes its top 10. Then:
  1. the articles present in that top 10, ordered by each article's best CombMAX score (= the rank of its best
     paragraph in the top 10);
  2. ALL paragraphs of these articles, from the corpus (data/knowledge_study2_corpus/passages.jsonl), article by
     article in that order, the paragraphs of one article in corpus order;
  3. the list is cut at 20 passages (CAP); the paragraphs that did not fit are reported as cut.

PASS RULE (fixed before the first run of this script): the variant's target (its answer key) is in the expanded set
in every post-F1 run.

Run from the project root:
    .venv\\Scripts\\python.exe -m scripts.parent_expansion_sr --variant 01.1 --runs 4,5,6
"""

import argparse
import json

from scripts.compare_sr_fusion import combmax_order, step_lists
from src.config import load_config, project_path
from src.rag_v3_steps import article_id_of
from src.retrieval.passage import load_passages

TOP_K = 10   # the CombMAX top list that is expanded
CAP = 20     # the most passages after expansion


def expand(top_ids: list[str], corpus_ids: list[str], cap: int = CAP) -> dict:
    """The expanded set of one run: articles in order of their best paragraph in top_ids, all their paragraphs."""
    articles = list(dict.fromkeys(article_id_of(pid) for pid in top_ids))
    full = [pid for article in articles for pid in corpus_ids if article_id_of(pid) == article]
    return {"articles": articles, "passages": full[:cap], "cut": full[cap:]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Parent-document expansion of the SR CombMAX top 10 (no LLM).")
    parser.add_argument("--variant", default="01.1", help="case variant (default 01.1); target = its answer key")
    parser.add_argument("--runs", required=True, help="comma-separated SR run numbers, e.g. 4,5,6")
    args = parser.parse_args()
    config = load_config()
    from scripts.debug_single_case import load_answer_key
    target = load_answer_key(config, args.variant)["target_passage_id"]
    corpus_ids = [p.id for p in load_passages(project_path(config["study2_corpus"]["passages"]))]
    debug_dir = project_path(config["paths"]["runs"]).parent / "debug" / args.variant

    print(f"Parent-document expansion, case {args.variant}. Target {target}. CombMAX top {TOP_K} -> all paragraphs "
          f"of its articles, cap {CAP}.\n")
    print(f"{'run':<15}{'n':<4}{'target':<8}{'cut':<5}articles (cut passages)")
    for n in args.runs.split(","):
        run_dir = debug_dir / f"rag_sr_run_{n.strip()}"
        s3 = json.loads((run_dir / "03_step_rankings.json").read_text(encoding="utf-8"))
        top = [row["passage_id"] for row in combmax_order(step_lists(s3), config["retrieval"]["rrf_k"])[:TOP_K]]
        out = expand(top, corpus_ids)
        cut = f" (cut: {', '.join(out['cut'])})" if out["cut"] else ""
        print(f"{run_dir.name:<15}{len(out['passages']):<4}{'yes' if target in out['passages'] else 'no':<8}"
              f"{'yes' if out['cut'] else 'no':<5}{', '.join(out['articles'])}{cut}")


if __name__ == "__main__":
    main()
