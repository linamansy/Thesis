"""Study 2: freeze GDPR retrieval for the 7 development cases, in two versions for comparison.

The corpus is the GDPR restricted to Chapters I-V (config.yaml study2_gdpr.included_chapters,
data/knowledge_gdpr/passages_ch1-5.jsonl), with its own dense index folder.

  (a) hybrid  data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_hybrid.json
      hybrid top 5, made by Study 1's own RetrievalFreezer (src/freeze_retrieval.py) with Study 1's settings
      (e5-small-v2, BM25, RRF k 60), only pointed at the restricted GDPR passages, a separate dense index folder
      and the development cases (config.yaml study2_gdpr).
  (b) rerank  data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json
      the same hybrid retrieval, but its top 20 (reranker.candidates) are re-scored by the CrossEncoderReranker
      (src/retrieval/cross_encoder_reranker.py) and the best 5 (reranker.top_k) are kept. The file also lists all
      20 candidates with their hybrid rank, RRF score and reranker score, the queries the reranker scored
      (reranker.queries: sentences, mean score), and the reranker model and commit.

The first comparison (all 99 articles, reranker max over all queries; frozen_retrieval_dev_hybrid.json and
frozen_retrieval_dev_rerank.json) is superseded and kept unchanged; this script no longer writes it.

Only the cases in study2_gdpr.development_ids are retrieved. Study 1's files (data/knowledge/, data/retrieval/)
are never read or written. Existing files are never overwritten unless --force is given.

Run from the project root:  .venv\\Scripts\\python.exe -m src.freeze_retrieval_gdpr
"""

import argparse
import copy
import sys
from importlib.metadata import version

from src.config import load_config, project_path
from src.freeze_retrieval import RetrievalFreezer, save, sha256_of_file
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.hybrid_retriever import HybridRetriever

RERANKER_LIBRARIES = ["sentence-transformers", "transformers", "torch"]


def gdpr_view(config: dict) -> dict:
    """A copy of the config in which Study 1's retrieval paths and cases point to the GDPR development setup."""
    view = copy.deepcopy(config)
    gdpr = config["study2_gdpr"]
    view["paths"]["passages"] = gdpr["passages_restricted"]
    view["paths"]["dense_index_dir"] = gdpr["dense_index_dir_restricted"]
    view["cases"]["ids"] = list(gdpr["development_ids"])
    return view


class GdprDevFreezer(RetrievalFreezer):
    """Study 1's RetrievalFreezer on the GDPR passages, plus a reranked second version."""

    def __init__(self, config: dict, reranker: CrossEncoderReranker | None = None):
        super().__init__(gdpr_view(config))
        self.sources_file = config["study2_gdpr"]["knowledge_sources"]
        self.sources_path = project_path(self.sources_file)
        self.included_chapters = list(config["study2_gdpr"]["included_chapters"])
        self.reranker_settings = config["reranker"]
        self.reranker = reranker or CrossEncoderReranker.from_config(config)
        settings = config["retrieval"]
        self.candidate_retriever = HybridRetriever(self.dense, self.sparse, settings["top_k_per_retriever"],
                                                   settings["rrf_k"], final_top_k=self.reranker_settings["candidates"])

    def retrieve_case_reranked(self, case_id: str) -> dict:
        """Hybrid top 20 for the case, re-scored by the reranker; the best top_k are the case's passages."""
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        queries = self.query_builder.build(description)
        candidates = self.candidate_retriever.search_case(queries)
        hybrid = {c.passage.id: c for c in candidates}
        reranked = self.reranker.rerank(queries, candidates, top_k=len(candidates))  # all, best first
        rows = [{"rank": r.rank, "passage_id": r.passage.id, "rerank_score": r.score,
                 "hybrid_rank": hybrid[r.passage.id].rank, "fused_score": hybrid[r.passage.id].score}
                for r in reranked]
        return {
            "queries": queries,
            "reranker_queries": self.reranker.select_queries(queries),
            "passages": [dict(row, text=hybrid[row["passage_id"]].passage.text)
                         for row in rows[:self.reranker_settings["top_k"]]],
            "candidates": rows,  # all hybrid candidates, in reranker order
        }

    def freeze_both(self) -> tuple[dict, dict]:
        """(hybrid file content, rerank file content). Both share the header of Study 1's frozen file."""
        hybrid = self.freeze()
        study = {"study": "Study 2 (GDPR), development cases only",
                 "case_ids": self.case_ids,
                 "included_chapters": self.included_chapters,
                 "knowledge_sources": self.sources_file,
                 "knowledge_sources_sha256": sha256_of_file(self.sources_path)}
        rerank = {key: value for key, value in hybrid.items() if key != "cases"}
        rerank["study2"] = dict(study, version="rerank",
                                method=f"hybrid top {self.reranker_settings['candidates']} re-scored by the "
                                       f"cross-encoder, top {self.reranker_settings['top_k']} kept")
        rerank["reranker"] = {
            "settings": self.reranker_settings,
            "class": type(self.reranker).__name__,
            "model": self.reranker.model_name,
            "revision": self.reranker.revision,
            "library_versions": {name: version(name) for name in RERANKER_LIBRARIES},
            "note": "reranker.enabled is false in config.yaml (off by default); it is switched on only for this file",
        }
        rerank["cases"] = {case_id: self.retrieve_case_reranked(case_id) for case_id in self.case_ids}
        hybrid["study2"] = dict(study, version="hybrid", method="hybrid top 5, exactly like Study 1")
        return hybrid, rerank


def side_by_side(hybrid: dict, rerank: dict) -> str:
    """A text table: per case and rank, the hybrid passage next to the reranked passage."""
    lines = [f"{'case':<5}{'rank':<5}{'(a) hybrid top 5':<22}{'(b) rerank top 5':<22}{'hybrid rank of (b)'}"]
    for case_id in hybrid["cases"]:
        for a, b in zip(hybrid["cases"][case_id]["passages"], rerank["cases"][case_id]["passages"]):
            mark = "" if b["passage_id"] in {p["passage_id"] for p in hybrid["cases"][case_id]["passages"]} else " *new"
            lines.append(f"{case_id:<5}{a['rank']:<5}{a['passage_id']:<22}{b['passage_id']:<22}{b['hybrid_rank']}{mark}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze GDPR retrieval (development cases) with and without reranker.")
    parser.add_argument("--force", action="store_true", help="replace existing frozen files")
    args = parser.parse_args()

    config = load_config()
    outputs = [project_path(config["study2_gdpr"][key])
               for key in ("frozen_dev_hybrid_restricted", "frozen_dev_rerank_restricted")]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.force:  # check before the slow work
        sys.exit(f"Refusing to overwrite {existing}. Use --force to replace them on purpose.")

    hybrid, rerank = GdprDevFreezer(config).freeze_both()
    for content, path in zip((hybrid, rerank), outputs):
        save(content, path, force=args.force)
        print(f"Saved {path}")
    print("\n" + side_by_side(hybrid, rerank))


if __name__ == "__main__":
    main()
