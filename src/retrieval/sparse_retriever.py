"""BM25Retriever: finds passages that share (rare) WORDS with the query.

BM25 scores a passage higher when it contains query words often, when those words are
rare in the whole collection, and (less strongly) when the passage is short:
  k1 = 1.5  how quickly repeating a word stops adding to the score
  b  = 0.75 how strongly long passages are penalised (0 = not at all, 1 = fully)
Passages and queries are both cleaned with src/retrieval/text_processing.py.
Only passages with a score above 0 (sharing at least one word with the query) are returned.
"""

from rank_bm25 import BM25Okapi

from src.config import project_path
from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult
from src.retrieval.text_processing import load_stopwords, tokenize


class BM25Retriever:
    """Keyword-based search over the passages."""

    def __init__(self, passages: list[Passage], k1: float, b: float, stopwords: frozenset[str]):
        self.passages = passages
        self.stopwords = stopwords
        self.bm25 = BM25Okapi([tokenize(p.text, stopwords) for p in passages], k1=k1, b=b)

    @classmethod
    def from_config(cls, config: dict, passages: list[Passage]) -> "BM25Retriever":
        settings = config["retrieval"]
        stopwords = load_stopwords(settings["stopwords_language"], project_path(config["paths"]["nltk_data"]))
        return cls(passages, settings["bm25_k1"], settings["bm25_b"], stopwords)

    def search(self, query: str, k: int) -> list[SearchResult]:
        """The k passages with the highest BM25 score (ties: earlier passage first)."""
        scores = self.bm25.get_scores(tokenize(query, self.stopwords))
        order = sorted(range(len(self.passages)), key=lambda i: (-scores[i], i))
        order = [i for i in order if scores[i] > 0][:k]
        return [SearchResult(passage=self.passages[i], score=float(scores[i]), rank=r)
                for r, i in enumerate(order, start=1)]
