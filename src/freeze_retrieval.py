"""Freeze retrieval: run hybrid retrieval ONCE for every case and save the result.

C2 and C3 never run retrieval themselves; they only read the frozen file. This guarantees
that both conditions get exactly the same 5 passages per case, and that the passages do
not change between runs (for example after a library update).

For every case in config.yaml:
  queries  = QueryBuilder(description)          (full description + each sentence)
  passages = HybridRetriever.search_case(queries) (RRF summed over all queries, top 5)

Saved to data/retrieval/frozen_retrieval.json:
  created_at        when the file was made (UTC)
  retrieval_config  the retrieval and chunking settings from config.yaml
  reproducibility   passages file + checksum, dense index fingerprint, stopword list checksum,
                    library versions
  cases             per case: its queries and its 5 passages (rank, passage id, fused score, full text)

An existing file is never overwritten unless --force is given.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.freeze_retrieval
  .venv\\Scripts\\python.exe -m src.freeze_retrieval --force     (replace an existing file on purpose)
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from src.config import load_config, project_path
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.passage import load_passages
from src.retrieval.query_builder import QueryBuilder
from src.retrieval.sparse_retriever import BM25Retriever

LIBRARIES = ["sentence-transformers", "torch", "faiss-cpu", "rank-bm25", "nltk"]


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RetrievalFreezer:
    """Runs case-level retrieval for all cases and writes the frozen file."""

    def __init__(self, config: dict):
        paths = config["paths"]
        self.config = config
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.description_file = paths["case_description_file"]
        self.passages_path = project_path(paths["passages"])
        self.output_path = project_path(paths["frozen_retrieval"])

        passages = load_passages(self.passages_path)
        self.dense = DenseRetriever.from_config(config, passages)
        self.sparse = BM25Retriever.from_config(config, passages)
        self.hybrid = HybridRetriever.from_config(config, self.dense, self.sparse)
        self.query_builder = QueryBuilder()

    def retrieve_case(self, case_id: str) -> dict:
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        queries = self.query_builder.build(description)
        results = self.hybrid.search_case(queries)
        return {
            "queries": queries,
            "passages": [{"rank": r.rank, "passage_id": r.passage.id, "fused_score": r.score,
                          "text": r.passage.text} for r in results],
        }

    def freeze(self) -> dict:
        """The complete content of the frozen file."""
        return {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "retrieval_config": {
                "retrieval": self.config["retrieval"],
                "chunking": self.config["chunking"],
            },
            "reproducibility": {
                "passages_file": self.config["paths"]["passages"],
                "passages_sha256": sha256_of_file(self.passages_path),
                "n_passages": len(self.dense.passages),
                "dense_index_fingerprint": self.dense.fingerprint(),
                "stopwords_count": len(self.sparse.stopwords),
                "stopwords_sha256": hashlib.sha256("\n".join(sorted(self.sparse.stopwords)).encode()).hexdigest(),
                "library_versions": {name: version(name) for name in LIBRARIES},
            },
            "cases": {case_id: self.retrieve_case(case_id) for case_id in self.case_ids},
        }


def save(frozen: dict, path: Path, force: bool) -> None:
    """Write the frozen file; refuse to replace an existing one unless force is True."""
    path = Path(path)
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists. Use --force to replace it on purpose.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval once for all cases and freeze the result.")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen file")
    args = parser.parse_args()

    config = load_config()
    output_path = project_path(config["paths"]["frozen_retrieval"])
    if output_path.exists() and not args.force:  # check before the slow work
        sys.exit(f"Refusing to overwrite {output_path}. Use --force to replace it on purpose.")

    frozen = RetrievalFreezer(config).freeze()
    save(frozen, output_path, force=args.force)

    print(f"{'case':<6}{'queries':>8}  passages (rank 1 to 5)")
    for case_id, case in frozen["cases"].items():
        print(f"{case_id:<6}{len(case['queries']):>8}  " + "  ".join(p["passage_id"] for p in case["passages"]))
    print(f"\nSaved {output_path}")


if __name__ == "__main__":
    main()
