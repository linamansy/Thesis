"""Freeze RAG v2 (Study 2): run RagV2Retriever ONCE for the 13 real cases and the 8 variants, and save the result.

The setting is the one decided by docs/RAG_V2_CRITERIA.md section 3 (config.yaml rag_v2.sibling_expansion). Study 2's
C2 and C3 will only read this file, exactly like Study 1 reads data/retrieval/frozen_retrieval.json.

Saved to rag_v2.frozen_retrieval (data/retrieval_study2_corpus/frozen_retrieval_v2.json):
  created_at        when the file was made (UTC)
  retrieval_config  the retrieval and chunking settings from config.yaml
  reproducibility   corpus file + SHA-256 (must equal study2_corpus.manifest), dense index fingerprint, embedding
                    model, library versions
  reranker          settings, model, revision, library versions
  rag_v2            sibling expansion setting, criteria file, case ids and variant ids
  cases             per case: the result of RagV2Retriever.retrieve (queries, top 5 passages with text, all candidates)
and its SHA-256 to rag_v2.frozen_manifest. An existing file is never overwritten (no --force). No LLM is called.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.freeze_rag_v2
"""

import json
import sys
from datetime import datetime, timezone
from importlib.metadata import version

from src.config import load_config, project_path
from src.freeze_retrieval import LIBRARIES, save, sha256_of_file
from src.freeze_retrieval_gdpr import RERANKER_LIBRARIES
from src.rag_v2 import RagV2Retriever, corpus_view


def variant_ids(config: dict) -> list[str]:
    items = json.loads(project_path(config["rag_v2"]["test_set"]).read_text(encoding="utf-8"))["items"]
    return [item["case_id"] for item in items]


def freeze(config: dict, retriever: RagV2Retriever) -> dict:
    """The complete content of the frozen file."""
    corpus_path = project_path(config["study2_corpus"]["passages"])
    corpus_sha = sha256_of_file(corpus_path)
    manifest = json.loads(project_path(config["study2_corpus"]["manifest"]).read_text(encoding="utf-8"))
    if corpus_sha != manifest["passages_sha256"]:
        raise RuntimeError(f"Study 2 corpus changed: {corpus_sha} != manifest {manifest['passages_sha256']}")
    case_ids = list(config["study2_cases"]["ids"])
    variants = variant_ids(config)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "retrieval_config": {"retrieval": config["retrieval"], "chunking": config["chunking"]},
        "reproducibility": {
            "passages_file": config["study2_corpus"]["passages"],
            "passages_sha256": corpus_sha,
            "n_passages": len(retriever.dense.passages),
            "dense_index_dir": config["rag_v2"]["dense_index_dir"],
            "dense_index_fingerprint": retriever.dense.fingerprint(),
            "dense_model": config["retrieval"]["dense_model"],
            "library_versions": {name: version(name) for name in LIBRARIES},
        },
        "reranker": {
            "settings": config["reranker"],
            "class": type(retriever.reranker).__name__,
            "model": retriever.reranker.model_name,
            "revision": retriever.reranker.revision,
            "library_versions": {name: version(name) for name in RERANKER_LIBRARIES},
        },
        "rag_v2": {
            "study": "Study 2, RAG v2 on the Study 2 corpus (GDPR, CRD, LPD, SGD, ECD)",
            "sibling_expansion": retriever.sibling_expansion,
            "decided_by": "docs/RAG_V2_CRITERIA.md section 3",
            "criteria_sha256": sha256_of_file(project_path("docs/RAG_V2_CRITERIA.md")),
            "case_ids": case_ids,
            "variant_ids": variants,
            "method": f"hybrid top {config['reranker']['candidates']}"
                      + (" + sibling paragraphs" if retriever.sibling_expansion else "")
                      + f" re-scored by the cross-encoder, top {config['reranker']['top_k']} kept",
        },
        "cases": {case_id: retriever.retrieve_case_reranked(case_id) for case_id in case_ids + variants},
    }


def main() -> None:
    config = load_config()
    out_path = project_path(config["rag_v2"]["frozen_retrieval"])
    manifest_path = project_path(config["rag_v2"]["frozen_manifest"])
    if out_path.exists() or manifest_path.exists():   # check before the slow work
        sys.exit(f"Refusing to overwrite {out_path} / {manifest_path}.")

    retriever = RagV2Retriever(corpus_view(config))   # sibling expansion from config.yaml
    frozen = freeze(config, retriever)
    save(frozen, out_path, force=False)
    manifest = {"description": "RAG v2 frozen retrieval (src/freeze_rag_v2.py); never changed after freezing.",
                "file": config["rag_v2"]["frozen_retrieval"], "sha256": sha256_of_file(out_path),
                "created_at": frozen["created_at"], "sibling_expansion": frozen["rag_v2"]["sibling_expansion"],
                "corpus_sha256": frozen["reproducibility"]["passages_sha256"],
                "n_cases": len(frozen["cases"])}
    save(manifest, manifest_path, force=False)
    print(f"Saved {out_path}\nsha256 {manifest['sha256']}")
    for case_id, case in frozen["cases"].items():
        print(f"{case_id:<6}{' '.join(p['passage_id'] for p in case['passages'])}")


if __name__ == "__main__":
    main()
