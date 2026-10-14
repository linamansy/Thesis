"""DenseRetriever: finds passages whose MEANING is close to the query.

  1. Every passage is turned into a vector by the embedding model (intfloat/e5-small-v2).
     e5 models were trained with prefixes, so passages are embedded as "passage: <text>"
     and queries as "query: <text>".
  2. Vectors are normalised to length 1, so the inner product of two vectors equals their
     cosine similarity.
  3. The vectors are stored in a FAISS IndexFlatIP, which compares the query vector with
     every passage vector exactly (no approximation) and returns the highest inner products.

The index is saved to data/retrieval/dense_index/ with a fingerprint of the model, the
prefixes and the passages. It is reused only if the fingerprint still matches; if the
passages or settings change, it is rebuilt automatically.
"""

import hashlib
import json
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from src.config import project_path
from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult

INDEX_FILE = "index.faiss"
META_FILE = "index_meta.json"


class DenseRetriever:
    """Embedding-based search over the passages."""

    def __init__(self, passages: list[Passage], model_name: str, passage_prefix: str,
                 query_prefix: str, index_dir: Path):
        self.passages = passages
        self.model_name = model_name
        self.passage_prefix = passage_prefix
        self.query_prefix = query_prefix
        self.index_dir = Path(index_dir)
        self.model = SentenceTransformer(model_name)
        self.index = self._load_or_build()

    @classmethod
    def from_config(cls, config: dict, passages: list[Passage]) -> "DenseRetriever":
        settings = config["retrieval"]
        return cls(passages, settings["dense_model"], settings["passage_prefix"],
                   settings["query_prefix"], project_path(config["paths"]["dense_index_dir"]))

    def embed(self, texts: list[str]) -> np.ndarray:
        """Normalised embedding vectors (one row per text) as float32, the type FAISS needs."""
        vectors = self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return np.asarray(vectors, dtype="float32")

    def search(self, query: str, k: int) -> list[SearchResult]:
        """The k passages with the highest cosine similarity to the query."""
        k = min(k, self.index.ntotal)
        scores, indices = self.index.search(self.embed([self.query_prefix + query]), k)
        return [SearchResult(passage=self.passages[i], score=float(s), rank=r)
                for r, (s, i) in enumerate(zip(scores[0], indices[0]), start=1)]

    # ---------- building and saving the index ----------

    def fingerprint(self) -> str:
        """A short code that changes whenever the model, prefixes or passages change."""
        h = hashlib.sha256()
        for part in [self.model_name, self.passage_prefix] + [p.id + "\n" + p.text for p in self.passages]:
            h.update(part.encode("utf-8") + b"\0")
        return h.hexdigest()

    def _load_or_build(self) -> faiss.Index:
        index_path, meta_path = self.index_dir / INDEX_FILE, self.index_dir / META_FILE
        if index_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("fingerprint") == self.fingerprint():
                return faiss.read_index(str(index_path))

        vectors = self.embed([self.passage_prefix + p.text for p in self.passages])
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(index, str(index_path))
        meta_path.write_text(json.dumps({
            "model": self.model_name,
            "passage_prefix": self.passage_prefix,
            "query_prefix": self.query_prefix,
            "dimension": int(vectors.shape[1]),
            "n_passages": len(self.passages),
            "fingerprint": self.fingerprint(),
            "passage_ids": [p.id for p in self.passages],  # row i of the index = passage_ids[i]
        }, indent=2), encoding="utf-8")
        return index
