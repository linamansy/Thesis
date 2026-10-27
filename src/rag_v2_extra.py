"""RAG v2 extra round (Study 2): the four pre-declared configurations A, B, C, D of docs/RAG_V2_CRITERIA.md section 7.

Each config is RagV2Retriever (src/rag_v2.py) with sibling expansion OFF, the same corpus, embedding model and
reranker, plus (config.yaml rag_v2.extra_round.configs):

  index_prefix (A, D)  every passage is indexed as "<law name> <number>, Article <n>: <title>." + newline + its text,
                       e.g. "Late Payment Directive 2011/7/EU, Article 3: Transactions between undertakings."
                       This index text is embedded (own dense index folder), BM25-indexed and given to the reranker.
                       The passage text in the result (what C2/C3 would get) is the unchanged corpus text.
  rewrite (B, D)       QueryRewriter (src/retrieval/query_rewriter.py) adds qwen3:8b's legal-concept queries AFTER the
                       original queries [full description, sentence 1, ...]; queries already in the list are not
                       added twice. The reranker scores the sentence queries and the rewritten queries (all but
                       the full description, reranker.queries: sentences).
  pool (C, D)          50 instead of 20: top 50 from each retriever, top 50 after RRF go to the reranker.

The best reranker.top_k (5) are kept, as before. No file is frozen by this module (src/freeze_rag_v2_extra.py does).
"""

import json

from src.config import project_path
from src.rag_v2 import RagV2Retriever, corpus_view
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.passage import Passage
from src.retrieval.sparse_retriever import BM25Retriever


def law_names(config: dict) -> dict[str, str]:
    """Passage id prefix -> "<short name> <number>", from the Study 2 corpus sources file."""
    sources = json.loads(project_path(config["study2_corpus"]["sources"]).read_text(encoding="utf-8"))
    return {d["id_prefix"]: f"{d['short_name']} {d['number']}" for d in sources["directives"]}


def index_text(passage: Passage, names: dict[str, str]) -> str:
    """Config A: the text that is indexed and reranked (law name + article number + article title, then the text)."""
    law = names[passage.id.split("-", 1)[0]]
    return f"{law}, Article {passage.article}: {passage.title}.\n{passage.text}"


class ExtraRoundRetriever(RagV2Retriever):
    """RagV2Retriever (expansion OFF) with one of the configs A, B, C, D."""

    def __init__(self, config: dict, name: str, reranker=None, rewriter=None, dense_index_dir=None):
        """config: the full config (corpus_view is applied here). rewriter: a QueryRewriter (B, D only).
        dense_index_dir: replaces rag_v2.extra_round.prefixed_dense_index_dir (tests)."""
        settings = config["rag_v2"]["extra_round"]["configs"][name]
        super().__init__(corpus_view(config), reranker, sibling_expansion=False)
        self.name = name
        self.settings = dict(settings)
        self.pool = settings["pool"]
        if settings["rewrite"] and rewriter is None:
            raise ValueError(f"config {name} rewrites the queries: a QueryRewriter is needed")
        self.rewriter = rewriter if settings["rewrite"] else None
        self.original = {p.id: p for p in self.dense.passages}   # the corpus passages (text given to C2/C3)

        retrieval = config["retrieval"]
        if settings["index_prefix"]:
            names = law_names(config)
            indexed = [Passage(**dict(p.to_dict(), text=index_text(p, names), n_chars=len(index_text(p, names))))
                       for p in self.dense.passages]
            index_dir = dense_index_dir or project_path(config["rag_v2"]["extra_round"]["prefixed_dense_index_dir"])
            self.dense = DenseRetriever(indexed, retrieval["dense_model"], retrieval["passage_prefix"],
                                        retrieval["query_prefix"], index_dir)
            self.sparse = BM25Retriever(indexed, retrieval["bm25_k1"], retrieval["bm25_b"], self.sparse.stopwords)
        self.candidate_retriever = HybridRetriever(self.dense, self.sparse, self.pool, retrieval["rrf_k"],
                                                   final_top_k=self.pool)

    def retrieve_case_reranked(self, case_id: str) -> dict:
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        return self.retrieve(description, case_id)

    def queries(self, description: str, case_id: str | None) -> tuple[list[str], list[str]]:
        """(all queries, the rewritten ones). Without rewriting: the QueryBuilder queries only."""
        queries = self.query_builder.build(description)
        if self.rewriter is None:
            return queries, []
        rewritten = self.rewriter.rewrite(case_id, description)
        return queries + [q for q in dict.fromkeys(rewritten) if q not in queries], rewritten

    def retrieve(self, description: str, case_id: str | None = None) -> dict:
        """Hybrid top `pool`, re-scored by the reranker; the best top_k are the passages (with the corpus text)."""
        queries, rewritten = self.queries(description, case_id)
        candidates = self.candidate_retriever.search_case(queries)
        hybrid = {c.passage.id: c for c in candidates}
        reranked = self.reranker.rerank(queries, candidates, top_k=len(candidates))  # all, best first
        rows = [{"rank": r.rank, "passage_id": r.passage.id, "rerank_score": r.score,
                 "hybrid_rank": hybrid[r.passage.id].rank, "fused_score": hybrid[r.passage.id].score}
                for r in reranked]
        top = rows[:self.reranker_settings["top_k"]]
        return {
            "config": self.name,
            "queries": queries,
            "rewritten_queries": rewritten if self.rewriter else None,
            "reranker_queries": self.reranker.select_queries(queries),
            "passages": [dict(row, text=self.original[row["passage_id"]].text) for row in top],
            "candidates": rows,  # all candidates, in reranker order
        }

    def describe(self) -> dict:
        """The config's settings, for reports and the frozen file."""
        return {"config": self.name, **self.settings, "sibling_expansion": False,
                "dense_index_dir": str(self.dense.index_dir), "dense_index_fingerprint": self.dense.fingerprint()}



def make_rewriter(config: dict):
    """The real QueryRewriter (qwen3:8b on Ollama). Stops before any call if the Ollama version is not
    study2_gdpr.ollama_version (0.40.11), the model digest is not model.ollama_model_digest, or the Ollama server
    settings differ from config.yaml. With the mock provider (tests) it refuses: tests pass their own rewriter."""
    from datetime import datetime, timezone

    from run_experiment import ollama_settings
    from src.llm.ollama_llm import OllamaLLM
    from src.logger import RunLogger
    from src.retrieval.query_rewriter import QueryRewriter

    if config["model"]["provider"] != "ollama":
        raise ValueError(f"query rewriting needs model.provider ollama, not {config['model']['provider']!r}")
    settings = ollama_settings(config)   # model digest and server settings, checked
    expected = str(config["study2_gdpr"]["ollama_version"])
    if settings.get("ollama_version") != expected:
        raise ValueError(f"Ollama is {settings.get('ollama_version')!r}, study2_gdpr.ollama_version is {expected!r}")
    extra = config["rag_v2"]["extra_round"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    template = project_path(extra["rewrite_prompt"]).read_text(encoding="utf-8")
    return QueryRewriter(OllamaLLM.from_config(config), template, project_path(extra["rewrite_dir"]),
                         lambda: RunLogger(project_path(config["paths"]["logs"]), extra["rewrite_log_condition"], stamp),
                         run_facts={"ollama_version": settings["ollama_version"],
                                    "ollama_server_env": settings["ollama_server_env"]})


def build(config: dict, name: str) -> ExtraRoundRetriever:
    """The retriever of config `name`, with the real QueryRewriter if the config rewrites."""
    rewrite = config["rag_v2"]["extra_round"]["configs"][name]["rewrite"]
    return ExtraRoundRetriever(config, name, rewriter=make_rewriter(config) if rewrite else None)
