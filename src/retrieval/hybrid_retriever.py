"""HybridRetriever: combines dense (meaning) and BM25 (words) search with Reciprocal Rank Fusion.

For one query:
  1. take the top 20 passages from the DenseRetriever and the top 20 from the BM25Retriever
  2. give every passage the score  sum over both lists of  1 / (k + rank),  with k = 60
     (rank 1 = best; a passage missing from a list gets nothing from that list)
  3. sort by that fused score

RRF only uses ranks, not the raw scores, so the very different score scales of cosine
similarity and BM25 do not need to be made comparable. A passage ranked high by both
retrievers ends up on top. The constant k = 60 (Cormack et al., 2009) keeps the gap
between rank 1 and rank 2 from dominating.

For one case (search_case), every query of the case contributes its two lists (dense and
BM25 top 20), and the RRF scores are summed over ALL these lists. A passage found by many
queries and by both retrievers therefore gets the highest score. Each passage appears once
in the result (duplicates are merged by summing), and the top 5 are kept, without any
relevance threshold.
"""

from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.search_result import SearchResult
from src.retrieval.sparse_retriever import BM25Retriever


def reciprocal_rank_fusion(rankings: list[list[str]], k: int) -> dict[str, float]:
    """rankings: lists of passage ids, best first. Returns {passage id: fused score}."""
    fused = {}
    for ranking in rankings:
        for rank, passage_id in enumerate(ranking, start=1):
            fused[passage_id] = fused.get(passage_id, 0.0) + 1.0 / (k + rank)
    return fused


class HybridRetriever:
    """Dense + BM25 search, fused with RRF."""

    def __init__(self, dense: DenseRetriever, sparse: BM25Retriever, top_k_per_retriever: int, rrf_k: int,
                 final_top_k: int):
        self.dense = dense
        self.sparse = sparse
        self.top_k_per_retriever = top_k_per_retriever
        self.rrf_k = rrf_k
        self.final_top_k = final_top_k

    @classmethod
    def from_config(cls, config: dict, dense: DenseRetriever, sparse: BM25Retriever) -> "HybridRetriever":
        settings = config["retrieval"]
        return cls(dense, sparse, settings["top_k_per_retriever"], settings["rrf_k"], settings["final_top_k"])

    def search_case(self, queries: list[str]) -> list[SearchResult]:
        """Top final_top_k passages for all queries of one case, by RRF score summed over every list."""
        rankings, passages = [], {}
        for query in queries:
            for results in (self.dense.search(query, self.top_k_per_retriever),
                            self.sparse.search(query, self.top_k_per_retriever)):
                rankings.append([r.passage.id for r in results])
                passages.update({r.passage.id: r.passage for r in results})

        fused = reciprocal_rank_fusion(rankings, self.rrf_k)  # one entry per passage: no duplicates
        order = sorted(fused, key=lambda pid: (-fused[pid], pid))[:self.final_top_k]
        return [SearchResult(passage=passages[pid], score=fused[pid], rank=rank)
                for rank, pid in enumerate(order, start=1)]

    def search(self, query: str, top_n: int | None = None) -> list[SearchResult]:
        """All fused passages (or the best top_n), highest RRF score first; ties broken by passage id."""
        dense_results = self.dense.search(query, self.top_k_per_retriever)
        sparse_results = self.sparse.search(query, self.top_k_per_retriever)
        dense_rank = {r.passage.id: r.rank for r in dense_results}
        sparse_rank = {r.passage.id: r.rank for r in sparse_results}
        passages = {r.passage.id: r.passage for r in dense_results + sparse_results}

        fused = reciprocal_rank_fusion([[r.passage.id for r in dense_results],
                                        [r.passage.id for r in sparse_results]], self.rrf_k)
        order = sorted(fused, key=lambda pid: (-fused[pid], pid))[:top_n]
        return [SearchResult(passage=passages[pid], score=fused[pid], rank=rank,
                             dense_rank=dense_rank.get(pid), sparse_rank=sparse_rank.get(pid))
                for rank, pid in enumerate(order, start=1)]
