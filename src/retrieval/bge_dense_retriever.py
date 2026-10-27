"""BgeDenseRetriever: DenseRetriever with BAAI/bge-m3 (STUDY 2, RAG v3 option E and G, EXPLORATORY).

Same search and index as DenseRetriever (normalised vectors, FAISS IndexFlatIP, index reused only if its fingerprint
matches), with the settings docs/RAG_V2_CRITERIA.md section 8.2 fixes for bge-m3:
  - dense vectors only, no query/passage prefix (the model card uses none)
  - pinned to one Hugging Face commit (config.yaml rag_v2.v3.dense_revision), which is part of the fingerprint
  - max input length 8192 tokens
  - on the CPU in fp32 (section 8.2 note: the project's PyTorch is CPU-only)
DenseRetriever itself (e5-small-v2, used by Study 1 and the current freezes) is not changed.
Tests pass a fake model, so they never load or download bge-m3.
"""

import hashlib
from pathlib import Path

from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.passage import Passage


class BgeDenseRetriever(DenseRetriever):
    """DenseRetriever for bge-m3: no prefixes, a pinned revision, a set max length and device."""

    def __init__(self, passages: list[Passage], model_name: str, revision: str, max_length: int, device: str,
                 index_dir: Path, model=None):
        self.passages = passages
        self.model_name = model_name
        self.revision = revision
        self.passage_prefix = ""
        self.query_prefix = ""
        self.index_dir = Path(index_dir)
        if model is None:
            from sentence_transformers import SentenceTransformer   # loaded only when a real model is needed
            model = SentenceTransformer(model_name, revision=revision, device=device)
        model.max_seq_length = max_length
        self.model = model
        self.index = self._load_or_build()

    def fingerprint(self) -> str:
        """Like DenseRetriever's, with the model revision included."""
        h = hashlib.sha256()
        for part in [f"{self.model_name}@{self.revision}", self.passage_prefix] + \
                    [p.id + "\n" + p.text for p in self.passages]:
            h.update(part.encode("utf-8") + b"\0")
        return h.hexdigest()
