"""RAG v3 (Study 2), EXPLORATORY: options E, F, G of docs/RAG_V2_CRITERIA.md section 8.

Every option is RagV2Retriever (src/rag_v2.py) with sibling expansion OFF, the same corpus (289 passages), BM25,
RRF (k 60), pool 20, queries (full description + each sentence; the reranker uses the sentences, mean score) and
top 5, plus (config.yaml rag_v2.v3.options):

  bge (E, G)     dense model BAAI/bge-m3 (BgeDenseRetriever, own index folder) and reranker BAAI/bge-reranker-v2-m3
                 (CrossEncoderReranker with the v3 model and revision; reranker.max_length, batch size, queries and
                 aggregation unchanged), both pinned to their Hugging Face commit, on the CPU in fp32 (section 8.2 note).
                 Without bge: e5-small-v2 and ms-marco-MiniLM-L-6-v2, exactly as the current freeze.
  enrich (F, G)  index text = passage text + newline + its qwen3:8b enrichment (section 8.3; passage text only if the
                 enrichment is empty). Used for BM25, the dense index (own folder) and the reranker.

C2 and C3 always get the ORIGINAL passage text from the corpus file: the "text" of a result passage is the corpus
text, never the index text. No query rewriting.

The enrichment is made ONCE, before any retrieval run with it (section 8.2):
  .venv\\Scripts\\python.exe -m src.rag_v3 --enrich
runs PassageEnricher over the 289 passages (one file per passage in rag_v2.v3.enrichment_dir, every call logged),
then writes rag_v2.v3.enrichment_file (passage id -> enrichment) and its manifest with the SHA-256. Neither file is
ever overwritten. F and G read the enrichment only through load_enrichment(), which checks that SHA-256.

Retrieval is run by src/evaluate_retrieval_v2.py --v3 E|F|G (build() below). Nothing is frozen by this module.
"""

import argparse
import json
from datetime import datetime, timezone

import httpx

from src.config import load_config, project_path
from src.freeze_retrieval import save, sha256_of_file
from src.rag_v2 import RagV2Retriever, corpus_view
from src.retrieval.bge_dense_retriever import BgeDenseRetriever
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.passage import Passage, load_passages
from src.retrieval.query_rewriter import sha256_text
from src.retrieval.sparse_retriever import BM25Retriever

LABEL = "EXPLORATORY (docs/RAG_V2_CRITERIA.md section 8)"


# ---------- enrichment (option F, G) ----------

def check_corpus(config: dict) -> list[Passage]:
    """The Study 2 corpus passages; stops if the file's SHA-256 is not the corpus manifest's (d30eea57...)."""
    path = project_path(config["study2_corpus"]["passages"])
    manifest = json.loads(project_path(config["study2_corpus"]["manifest"]).read_text(encoding="utf-8"))
    if sha256_of_file(path) != manifest["passages_sha256"]:
        raise RuntimeError(f"Study 2 corpus changed: {sha256_of_file(path)} != manifest {manifest['passages_sha256']}")
    return load_passages(path)


def make_enricher(config: dict):
    """The real PassageEnricher (qwen3:8b on Ollama). Stops before any call if the Ollama version is not
    study2_gdpr.ollama_version (0.40.11), the model digest is not model.ollama_model_digest, or the Ollama server
    settings differ from config.yaml. With the mock provider (tests) it refuses: tests pass their own enricher."""
    from run_experiment import ollama_settings
    from src.llm.ollama_llm import OllamaLLM
    from src.logger import RunLogger
    from src.retrieval.passage_enricher import PassageEnricher

    if config["model"]["provider"] != "ollama":
        raise ValueError(f"enrichment needs model.provider ollama, not {config['model']['provider']!r}")
    settings = ollama_settings(config)   # model digest and server settings, checked
    expected = str(config["study2_gdpr"]["ollama_version"])
    if settings.get("ollama_version") != expected:
        raise ValueError(f"Ollama is {settings.get('ollama_version')!r}, study2_gdpr.ollama_version is {expected!r}")
    v3 = config["rag_v2"]["v3"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    template = project_path(v3["enrichment_prompt"]).read_text(encoding="utf-8")
    return PassageEnricher(OllamaLLM.from_config(config), template, project_path(v3["enrichment_dir"]),
                           lambda: RunLogger(project_path(config["paths"]["logs"]), v3["enrichment_log_condition"], stamp),
                           run_facts={"ollama_version": settings["ollama_version"],
                                      "ollama_server_env": settings["ollama_server_env"]})


def run_enrichment(config: dict, enricher) -> dict:
    """Enrich every corpus passage (saved ones are reused), then write the enrichment file and its manifest.
    Returns the manifest. Refuses if either file exists already."""
    v3 = config["rag_v2"]["v3"]
    out_path, manifest_path = project_path(v3["enrichment_file"]), project_path(v3["enrichment_manifest"])
    if out_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite {out_path} / {manifest_path}.")
    passages = check_corpus(config)
    records = []
    for i, passage in enumerate(passages, start=1):
        record = enricher.enrich(passage)
        records.append(record)
        print(f"{i:>3}/{len(passages)} {passage.id:<22}{record['finish_reason']}  {record['enrichment'][:90]!r}")
    lines = [json.dumps({"passage_id": r["passage_id"], "enrichment": r["enrichment"],
                         "finish_reason": r["finish_reason"]}, ensure_ascii=False) for r in records]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    template = project_path(v3["enrichment_prompt"]).read_text(encoding="utf-8")
    manifest = {
        "label": LABEL,
        "description": "qwen3:8b passage enrichment for RAG v3 options F and G (src/rag_v3.py --enrich); made once, "
                       "never changed. Input = the passage text only.",
        "file": v3["enrichment_file"], "sha256": sha256_of_file(out_path),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_file": v3["enrichment_prompt"], "prompt_sha256": sha256_text(template),
        "corpus_file": config["study2_corpus"]["passages"],
        "corpus_sha256": sha256_of_file(project_path(config["study2_corpus"]["passages"])),
        "model": records[0]["model"], "model_digest": records[0]["model_digest"],
        "ollama_version": records[0].get("ollama_version"), "settings": records[0]["settings"],
        "n_passages": len(records),
        "n_empty": sum(not r["enrichment"] for r in records),
        "n_max_tokens": sum(r["finish_reason"] == "MAX_TOKENS" for r in records),
        "finish_reasons": sorted({str(r["finish_reason"]) for r in records}),
        "per_passage_dir": v3["enrichment_dir"],
        "log_files": sorted({r["log_file"] for r in records}),
    }
    save(manifest, manifest_path, force=False)
    return manifest


def load_enrichment(config: dict) -> dict[str, str]:
    """passage id -> enrichment, after checking the file's SHA-256 against its manifest and the corpus."""
    v3 = config["rag_v2"]["v3"]
    path = project_path(v3["enrichment_file"])
    manifest = json.loads(project_path(v3["enrichment_manifest"]).read_text(encoding="utf-8"))
    if sha256_of_file(path) != manifest["sha256"]:
        raise RuntimeError(f"{path} changed: {sha256_of_file(path)} != manifest {manifest['sha256']}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    enrichment = {r["passage_id"]: r["enrichment"] for r in rows}
    corpus_ids = [p.id for p in check_corpus(config)]
    if sorted(enrichment) != sorted(corpus_ids):
        raise RuntimeError(f"{path} does not cover exactly the {len(corpus_ids)} corpus passages")
    return enrichment


def index_text(passage: Passage, enrichment: dict[str, str]) -> str:
    """Option F, G: the text that is indexed and reranked (passage text, newline, enrichment)."""
    extra = enrichment.get(passage.id, "")
    return f"{passage.text}\n{extra}" if extra else passage.text


# ---------- retrieval (option E, F, G) ----------

def bge_reranker(config: dict, model=None) -> CrossEncoderReranker:
    """CrossEncoderReranker with bge-reranker-v2-m3 (pinned revision, CPU); all other reranker settings unchanged."""
    v3, settings = config["rag_v2"]["v3"], config["reranker"]
    return CrossEncoderReranker(v3["reranker_model"], v3["reranker_revision"], settings["max_length"],
                                settings["batch_size"], settings["aggregation"], settings["queries"], model=model)


class RagV3Retriever(RagV2Retriever):
    """RagV2Retriever (expansion OFF) with option E, F or G."""

    def __init__(self, config: dict, option: str, reranker=None, enrichment: dict[str, str] | None = None,
                 dense_model=None, dense_index_dir=None):
        """config: the full config (corpus_view is applied here). reranker / dense_model: fakes in tests (with
        bge, a missing reranker is the real bge-reranker-v2-m3). enrichment: passage id -> text (F, G; default:
        load_enrichment). dense_index_dir: replaces rag_v2.v3.dense_index_dirs[option] (tests)."""
        v3 = config["rag_v2"]["v3"]
        settings = v3["options"][option]
        if settings["bge"] and reranker is None:
            reranker = bge_reranker(config)
        super().__init__(corpus_view(config), reranker, sibling_expansion=False)
        self.option = option
        self.settings = dict(settings)
        self.original = {p.id: p for p in self.dense.passages}   # the corpus passages (text given to C2/C3)

        indexed = self.dense.passages
        if settings["enrich"]:
            enrichment = load_enrichment(config) if enrichment is None else enrichment
            indexed = [Passage(**dict(p.to_dict(), text=index_text(p, enrichment),
                                      n_chars=len(index_text(p, enrichment)))) for p in indexed]
        retrieval = config["retrieval"]
        index_dir = dense_index_dir or project_path(v3["dense_index_dirs"][option])
        if settings["bge"]:
            self.dense = BgeDenseRetriever(indexed, v3["dense_model"], v3["dense_revision"], v3["dense_max_length"],
                                           v3["device"], index_dir, model=dense_model)
        elif settings["enrich"]:
            self.dense = DenseRetriever(indexed, retrieval["dense_model"], retrieval["passage_prefix"],
                                        retrieval["query_prefix"], index_dir)
        self.sparse = BM25Retriever(indexed, retrieval["bm25_k1"], retrieval["bm25_b"], self.sparse.stopwords)
        self.candidate_retriever = HybridRetriever(self.dense, self.sparse, retrieval["top_k_per_retriever"],
                                                   retrieval["rrf_k"], final_top_k=self.reranker_settings["candidates"])

    def retrieve(self, description: str) -> dict:
        """Hybrid top 20, re-scored by the reranker; the best top_k are the passages (with the corpus text)."""
        queries = self.query_builder.build(description)
        candidates = self.candidate_retriever.search_case(queries)
        hybrid = {c.passage.id: c for c in candidates}
        reranked = self.reranker.rerank(queries, candidates, top_k=len(candidates))  # all, best first
        rows = [{"rank": r.rank, "passage_id": r.passage.id, "rerank_score": r.score,
                 "hybrid_rank": hybrid[r.passage.id].rank, "fused_score": hybrid[r.passage.id].score}
                for r in reranked]
        top = rows[:self.reranker_settings["top_k"]]
        return {
            "label": LABEL,
            "option": self.option,
            "queries": queries,
            "reranker_queries": self.reranker.select_queries(queries),
            "passages": [dict(row, text=self.original[row["passage_id"]].text) for row in top],
            "candidates": rows,  # all candidates, in reranker order
        }

    def describe(self) -> dict:
        """The option's settings, for reports and a frozen file."""
        return {"label": LABEL, "option": self.option, **self.settings, "sibling_expansion": False,
                "dense_model": self.dense.model_name, "dense_revision": getattr(self.dense, "revision", None),
                "dense_index_dir": str(self.dense.index_dir), "dense_index_fingerprint": self.dense.fingerprint(),
                "reranker_model": self.reranker.model_name, "reranker_revision": self.reranker.revision}


def check_ollama_idle(config: dict, client=None) -> None:
    """Section 8.2: no Ollama model may be loaded while retrieval runs. Stops if /api/ps lists a model;
    an unreachable Ollama counts as idle."""
    client = client or httpx.Client(timeout=10)
    try:
        loaded = client.get(f"{config['model']['ollama_url'].rstrip('/')}/api/ps").json().get("models", [])
    except httpx.TransportError:
        return
    if loaded:
        raise RuntimeError(f"Ollama still has a model loaded ({[m.get('name') for m in loaded]}); "
                           f"unload it first (ollama stop <model>)")


def build(config: dict, option: str) -> RagV3Retriever:
    """The real retriever of option E, F or G (checks first that Ollama runs no model)."""
    check_ollama_idle(config)
    return RagV3Retriever(config, option)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="RAG v3 (exploratory): make the passage enrichment once.")
    parser.add_argument("--enrich", action="store_true", help="enrich the 289 passages with qwen3:8b (REAL RUN)")
    args = parser.parse_args(argv)
    if not args.enrich:
        parser.error("nothing to do: use --enrich (retrieval is run by src/evaluate_retrieval_v2.py --v3)")
    config = load_config()
    manifest = run_enrichment(config, make_enricher(config))
    print(f"\n{LABEL}\nSaved {manifest['file']}\nsha256 {manifest['sha256']}\n"
          f"passages {manifest['n_passages']}, empty {manifest['n_empty']}, MAX_TOKENS {manifest['n_max_tokens']}")


if __name__ == "__main__":
    main()
