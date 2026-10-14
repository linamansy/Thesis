"""SearchResult: one passage found by a retriever, with its score and rank."""

from dataclasses import dataclass

from src.retrieval.passage import Passage


@dataclass(frozen=True)
class SearchResult:
    passage: Passage
    score: float                    # dense: cosine similarity, sparse: BM25 score, hybrid: RRF score
    rank: int                       # 1 = best
    dense_rank: int | None = None   # hybrid only: rank in the dense list (None = not in its top k)
    sparse_rank: int | None = None  # hybrid only: rank in the BM25 list (None = not in its top k)
