"""Study 2 (more EU laws): freeze the reranked retrieval on the combined corpus, development cases only.

Corpus:  data/knowledge_study2/passages_combined_dev.jsonl (GDPR Chapters I-V + the kept articles of ECD, TPWC, CCD,
         OSH; src/chunk_study2_laws.py), with its own dense index folder data/retrieval_study2/dense_index_combined
         (built on first use by Study 1's DenseRetriever).
Method:  exactly the Study 2 setup of data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json: Study 1's hybrid
         retrieval (e5-small-v2, BM25, RRF k 60), its top 20 (reranker.candidates) re-scored by the
         CrossEncoderReranker (sentence queries, mean score), best 5 (reranker.top_k) kept. This file reuses
         GdprDevFreezer (src/freeze_retrieval_gdpr.py) unchanged; only its corpus and index paths are pointed at
         the combined corpus.
Output:  data/retrieval_study2/frozen_retrieval_dev_combined_rerank.json (config.yaml study2_laws), same format as
         the GDPR-only rerank file, plus both sources files and their SHA-256.

Only the cases in study2_gdpr.development_ids are retrieved. No file of Study 1 or of data/retrieval_gdpr/ is
written. An existing output file is never overwritten unless --force is given.

Run from the project root:  .venv\\Scripts\\python.exe -m src.freeze_retrieval_study2_laws
"""

import argparse
import copy
import sys

from src.config import load_config, project_path
from src.freeze_retrieval import save, sha256_of_file
from src.freeze_retrieval_gdpr import GdprDevFreezer


def combined_view(config: dict) -> dict:
    """A copy of the config in which the GDPR freezer's corpus and index point to the combined corpus."""
    view = copy.deepcopy(config)
    laws = config["study2_laws"]
    view["study2_gdpr"]["passages_restricted"] = laws["passages_combined"]
    view["study2_gdpr"]["dense_index_dir_restricted"] = laws["dense_index_dir_combined"]
    return view


def freeze_combined(config: dict, reranker=None) -> dict:
    """The content of the frozen file: the rerank version of GdprDevFreezer on the combined corpus."""
    _, rerank = GdprDevFreezer(combined_view(config), reranker).freeze_both()
    sources = [config["study2_gdpr"]["knowledge_sources"], config["study2_laws"]["knowledge_sources"]]
    rerank["study2"].update(
        study="Study 2 (GDPR Chapters I-V + ECD, TPWC, CCD, OSH), development cases only",
        corpus="combined",
        knowledge_sources=sources,
        knowledge_sources_sha256=[sha256_of_file(project_path(path)) for path in sources],
        article_selection=config["study2_laws"]["article_selection"],
        article_selection_sha256=sha256_of_file(project_path(config["study2_laws"]["article_selection"])),
        note="included_chapters applies to the GDPR passages only; the new laws follow article_selection")
    return rerank


def main(config: dict | None = None, argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Freeze reranked retrieval on the combined Study 2 corpus.")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen file")
    args = parser.parse_args(argv)

    config = config or load_config()
    output = project_path(config["study2_laws"]["frozen_dev_combined_rerank"])
    if output.exists() and not args.force:  # check before the slow work
        sys.exit(f"Refusing to overwrite {output}. Use --force to replace it on purpose.")

    frozen = freeze_combined(config)
    save(frozen, output, force=args.force)
    print(f"{'case':<6}passages (rank 1 to 5)")
    for case_id, case in frozen["cases"].items():
        print(f"{case_id:<6}" + "  ".join(p["passage_id"] for p in case["passages"]))
    print(f"\nSaved {output}")


if __name__ == "__main__":
    main()
