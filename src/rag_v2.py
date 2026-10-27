"""RAG v2 (Study 2): reranked retrieval on the Study 2 corpus, with optional sibling expansion. BUILD ONLY.

Same method and settings as the frozen GDPR development retrieval (data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json,
src/freeze_retrieval_gdpr.py GdprDevFreezer): Study 1's hybrid retrieval (e5-small-v2, BM25, RRF k 60), its top 20
(reranker.candidates) re-scored by the CrossEncoderReranker (sentence queries, mean score), best 5 (reranker.top_k)
kept. RagV2Retriever is GdprDevFreezer with one optional step between the two stages:

  sibling expansion (config.yaml rag_v2.sibling_expansion, default OFF): every other paragraph of the same article as
  a first-stage candidate is added to the candidates (SiblingExpander, src/retrieval/sibling_expander.py); all of them
  are reranked and the best 5 are kept. Each row then says whether it entered via expansion ("via_expansion"), and
  the case gets a "sibling_expansion" record (first-stage ids, added ids, which of the top 5 came via expansion).

With expansion OFF the result of a case is exactly GdprDevFreezer.retrieve_case_reranked's (same keys, same order),
so on the old GDPR corpus it reproduces the frozen GDPR development file (tests/test_rag_v2.py).

Corpus: corpus_view() points the freezer at the Study 2 corpus (study2_corpus.passages) and its own dense index
(rag_v2.dense_index_dir). Nothing is frozen by this module; no frozen retrieval file is read for writing.

Run from the project root (builds the dense index of the Study 2 corpus; no case is retrieved):
  .venv\\Scripts\\python.exe -m src.rag_v2 --build-index
"""

import argparse
import copy

from src.config import load_config, project_path
from src.freeze_retrieval_gdpr import GdprDevFreezer
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.passage import load_passages
from src.retrieval.sibling_expander import SiblingExpander


def corpus_view(config: dict) -> dict:
    """A copy of the config in which the GDPR freezer's corpus and index point to the Study 2 corpus."""
    view = copy.deepcopy(config)
    view["study2_gdpr"]["passages_restricted"] = config["study2_corpus"]["passages"]
    view["study2_gdpr"]["dense_index_dir_restricted"] = config["rag_v2"]["dense_index_dir"]
    return view


class RagV2Retriever(GdprDevFreezer):
    """GdprDevFreezer's reranked retrieval, plus optional sibling expansion before the reranker."""

    def __init__(self, config: dict, reranker=None, sibling_expansion: bool | None = None):
        super().__init__(config, reranker)
        if sibling_expansion is None:
            sibling_expansion = config["rag_v2"]["sibling_expansion"]
        self.sibling_expansion = sibling_expansion
        self.expander = SiblingExpander(self.dense.passages)

    def retrieve_case_reranked(self, case_id: str) -> dict:
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        return self.retrieve(description)

    def retrieve(self, description: str) -> dict:
        """Hybrid top 20 (+ siblings if ON), re-scored by the reranker; the best top_k are the passages."""
        queries = self.query_builder.build(description)
        candidates = self.candidate_retriever.search_case(queries)
        hybrid = {c.passage.id: c for c in candidates}
        added = self.expander.siblings(candidates) if self.sibling_expansion else []
        pool = candidates + added
        reranked = self.reranker.rerank(queries, pool, top_k=len(pool))  # all, best first
        rows = []
        for r in reranked:
            first = hybrid.get(r.passage.id)
            row = {"rank": r.rank, "passage_id": r.passage.id, "rerank_score": r.score,
                   "hybrid_rank": first.rank if first else None, "fused_score": first.score if first else None}
            if self.sibling_expansion:
                row["via_expansion"] = first is None
            rows.append(row)
        texts = {c.passage.id: c.passage.text for c in pool}
        top = rows[:self.reranker_settings["top_k"]]
        result = {
            "queries": queries,
            "reranker_queries": self.reranker.select_queries(queries),
            "passages": [dict(row, text=texts[row["passage_id"]]) for row in top],
            "candidates": rows,  # all candidates (first stage + siblings), in reranker order
        }
        if self.sibling_expansion:
            result["sibling_expansion"] = {
                "first_stage": [c.passage.id for c in candidates],
                "added": [a.passage.id for a in added],
                "top_k_via_expansion": [row["passage_id"] for row in top if row["via_expansion"]],
            }
        return result


def build_index(config: dict) -> DenseRetriever:
    """Build (or reuse, if its fingerprint matches) the dense index of the Study 2 corpus."""
    view = corpus_view(config)
    passages = load_passages(project_path(view["study2_gdpr"]["passages_restricted"]))
    index_view = copy.deepcopy(view)
    index_view["paths"]["dense_index_dir"] = view["study2_gdpr"]["dense_index_dir_restricted"]
    return DenseRetriever.from_config(index_view, passages)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RAG v2 on the Study 2 corpus (build only).")
    parser.add_argument("--build-index", action="store_true", help="build the dense index of the Study 2 corpus")
    args = parser.parse_args(argv)
    if not args.build_index:
        parser.error("nothing to do: use --build-index (retrieval is run by src/evaluate_retrieval_v2.py)")
    config = load_config()
    dense = build_index(config)
    print(f"Dense index of {len(dense.passages)} passages in {dense.index_dir} (fingerprint {dense.fingerprint()})")


if __name__ == "__main__":
    main()
