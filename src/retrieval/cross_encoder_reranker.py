"""CrossEncoderReranker: re-scores the candidates of the hybrid retriever with a cross-encoder.

STUDY 2 only, for a development comparison (src/freeze_retrieval_gdpr.py). Study 1 never uses it, and it is off
by default (config.yaml reranker.enabled: false).

The hybrid retriever (dense + BM25 + RRF) compares a query and a passage only through separate vectors or word
counts. A cross-encoder reads the query and the passage TOGETHER in one model input and outputs one relevance
score for the pair, which is usually more precise but too slow to run over all passages. So it only re-scores
the hybrid retriever's best candidates (top 20), and the best top_k (5) of these are kept.

For one case:
  1. the queries come from the hybrid retriever's list (QueryBuilder: full description, then each sentence).
     With config reranker.queries: sentences, only the SENTENCE queries are used (the full description is left
     out; a one-line description is its own sentence). With "all", every query is used.
  2. every (query, candidate passage) pair gets a cross-encoder score
  3. a passage's score is the MEAN over those queries (config reranker.aggregation: mean), so every step of the
     process counts equally ("max" is also allowed)
  4. sort by that score (ties: passage id) and keep top_k

Why sentences and mean (changed 24 Oct 2026): in a first try with "max" over all queries, the full description
gave the maximum for all 35 kept passages, so the sentence queries never mattered (the model gives long queries
higher scores).

The model is local (cross-encoder/ms-marco-MiniLM-L-6-v2 from Hugging Face, no API key), pinned to one commit
(config reranker.revision), and runs on the CPU. Tests pass a fake model, so they never load or download it.
"""

from statistics import fmean

from src.retrieval.search_result import SearchResult

AGGREGATIONS = {"max": max, "mean": fmean}
QUERY_SETS = ("all", "sentences")


class CrossEncoderReranker:
    """Re-scores hybrid candidates with a cross-encoder and keeps the best ones."""

    def __init__(self, model_name: str, revision: str, max_length: int, batch_size: int, aggregation: str,
                 queries: str, model=None):
        if aggregation not in AGGREGATIONS:
            raise ValueError(f"Unknown reranker aggregation {aggregation!r}; allowed: {sorted(AGGREGATIONS)}")
        if queries not in QUERY_SETS:
            raise ValueError(f"Unknown reranker query set {queries!r}; allowed: {list(QUERY_SETS)}")
        self.model_name = model_name
        self.revision = revision
        self.max_length = max_length
        self.batch_size = batch_size
        self.aggregation = aggregation
        self.queries = queries
        if model is None:
            from sentence_transformers import CrossEncoder  # loaded only when a real model is needed
            model = CrossEncoder(model_name, revision=revision, max_length=max_length, device="cpu")
        self.model = model

    @classmethod
    def from_config(cls, config: dict, model=None) -> "CrossEncoderReranker":
        settings = config["reranker"]
        return cls(settings["model"], settings["revision"], settings["max_length"], settings["batch_size"],
                   settings["aggregation"], settings["queries"], model=model)

    def select_queries(self, queries: list[str]) -> list[str]:
        """The queries the reranker uses, from the QueryBuilder list [full description, sentence 1, ...]."""
        if self.queries == "sentences":
            return queries[1:] or queries  # a one-line description: its only query is its sentence
        return queries

    def score(self, queries: list[str], candidates: list[SearchResult]) -> dict[str, float]:
        """{passage id: aggregated cross-encoder score over the selected queries}."""
        queries = self.select_queries(queries)
        pairs = [(query, c.passage.text) for c in candidates for query in queries]
        raw = self.model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False)
        combine = AGGREGATIONS[self.aggregation]
        n = len(queries)
        return {c.passage.id: float(combine(raw[i * n:(i + 1) * n])) for i, c in enumerate(candidates)}

    def rerank(self, queries: list[str], candidates: list[SearchResult], top_k: int) -> list[SearchResult]:
        """The top_k candidates by cross-encoder score, as SearchResults with the new score and rank.

        queries: the case's full QueryBuilder list; select_queries picks the ones that are scored.
        """
        if not queries or not candidates:
            return []
        scores = self.score(queries, candidates)
        by_id = {c.passage.id: c for c in candidates}
        order = sorted(scores, key=lambda pid: (-scores[pid], pid))[:top_k]
        return [SearchResult(passage=by_id[pid].passage, score=scores[pid], rank=rank)
                for rank, pid in enumerate(order, start=1)]
