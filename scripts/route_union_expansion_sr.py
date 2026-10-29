"""Offline test of a two-view route union + parent-document expansion on saved RAG step routing (SR) runs.
NO LLM, NO retrieval.

Two routing views of the same steps: runs 4-6 = title-only routing, runs 7-9 = law + title + first-sentence routing
(commit 41a4248). They are paired (4,7), (5,8), (6,9). For each pair and variant:
  0. the S1 steps (01_steps.json "steps") of the two runs must be identical; if not, the script STOPS;
  1. per step, the two runs' S3 lists are merged: union of paragraphs, each with its best reranker score of the two,
     best first;
  2. CombMAX over the merged step lists (src/rag_v3_steps.combmax_order), top 10;
  3. parent expansion of that top 10 (src/rag_v3_steps.expand): all paragraphs of the included
     articles, ordered by the article's best score, cap 20.

PASS RULE (fixed before the first run of this script): the target (01.1 GDPR-Art13-1, 01.2 LPD-Art3-1, from the answer
keys) is in the expanded set in all 3 pairs of both variants.

Run from the project root:  .venv\\Scripts\\python.exe -m scripts.route_union_expansion_sr
"""

import json

from scripts.debug_single_case import load_answer_key
from src.config import load_config, project_path
from src.rag_v3_steps import COMBMAX_TOP as TOP_K
from src.rag_v3_steps import combmax_order, expand, step_lists
from src.retrieval.passage import load_passages

VARIANTS = ("01.1", "01.2")
PAIRS = ((4, 7), (5, 8), (6, 9))


def load_json(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def union_lists(a: dict[str, list[dict]], b: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Per step: the union of both lists, each paragraph with its best reranker score, best first."""
    merged = {}
    for step in list(dict.fromkeys([*a, *b])):
        best = {}
        for row in a.get(step, []) + b.get(step, []):
            pid, score = row["passage_id"], row["rerank_score"]
            best[pid] = max(best.get(pid, score), score)
        order = sorted(best, key=lambda pid: (-best[pid], pid))
        merged[step] = [{"passage_id": pid, "rerank_score": best[pid]} for pid in order]
    return merged


def main() -> None:
    config = load_config()
    corpus_ids = [p.id for p in load_passages(project_path(config["study2_corpus"]["passages"]))]
    rrf_k = config["retrieval"]["rrf_k"]
    debug_root = project_path(config["paths"]["runs"]).parent / "debug"

    rows, passes = [], []
    for variant in VARIANTS:
        target = load_answer_key(config, variant)["target_passage_id"]
        for a, b in PAIRS:
            dir_a, dir_b = debug_root / variant / f"rag_sr_run_{a}", debug_root / variant / f"rag_sr_run_{b}"
            if load_json(dir_a / "01_steps.json")["steps"] != load_json(dir_b / "01_steps.json")["steps"]:
                raise SystemExit(f"STOP: S1 steps differ between {variant} runs {a} and {b}")
            lists = union_lists(step_lists(load_json(dir_a / "03_step_rankings.json")),
                                step_lists(load_json(dir_b / "03_step_rankings.json")))
            top = [row["passage_id"] for row in combmax_order(lists, rrf_k)[:TOP_K]]
            out = expand(top, corpus_ids)
            hit = target in out["passages"]
            passes.append(hit)
            rows.append((variant, f"({a},{b})", target, out, hit))

    print(f"Route union + parent expansion. CombMAX top {TOP_K} of the merged step lists -> all paragraphs of its "
          f"articles, cap 20.\nS1 steps identical in every pair.\n")
    print(f"{'variant':<9}{'pair':<8}{'n':<4}{'target':<22}{'cut':<5}articles (cut passages)")
    for variant, pair, target, out, hit in rows:
        cut = f" (cut: {', '.join(out['cut'])})" if out["cut"] else ""
        print(f"{variant:<9}{pair:<8}{len(out['passages']):<4}{target + (' yes' if hit else ' no'):<22}"
              f"{'yes' if out['cut'] else 'no':<5}{', '.join(out['articles'])}{cut}")
    print(f"\nPASS RULE: target in the expanded set in all {len(passes)} pairs -> "
          f"{'PASS' if all(passes) else 'FAIL'} ({sum(passes)}/{len(passes)})")


if __name__ == "__main__":
    main()
