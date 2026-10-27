"""Freeze the winner of the RAG v2 extra round (docs/RAG_V2_CRITERIA.md section 7.4) into NEW files.

Used ONLY if the selected config's M1 is above rag_v2.extra_round.baseline_m1 (2 of 8); otherwise the current freeze
(rag_v2.frozen_retrieval) is kept and this script is not run. The current frozen file is never read for writing.

Runs ExtraRoundRetriever (src/rag_v2_extra.py) ONCE for the 13 real cases and the 8 variants (same case list as
src/freeze_rag_v2.py; the held-out variants are NOT frozen) and saves, with the same layout as frozen_retrieval_v2.json:
  rag_v2.extra_round.frozen_retrieval   data/retrieval_study2_corpus/frozen_retrieval_v2_round2.json
  rag_v2.extra_round.frozen_manifest    its SHA-256
The "rag_v2" block also names the config, its settings and the evaluation reports it was selected from. Existing
files are never overwritten. Configs B and D reuse the saved rewrites (results/rag_v2_rewrites/) and rewrite only the
cases not rewritten yet.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.freeze_rag_v2_extra --config <A|B|C|D> --reports <report.json> ...
"""

import argparse
import sys

from src.config import load_config, project_path
from src.freeze_rag_v2 import freeze
from src.freeze_retrieval import save, sha256_of_file
from src.rag_v2_extra import build


def freeze_extra(config: dict, retriever, reports: list[str]) -> dict:
    """freeze_rag_v2.freeze's content, with the config's index and settings in place of section 3's."""
    frozen = freeze(config, retriever)
    frozen["reproducibility"]["dense_index_dir"] = str(retriever.describe()["dense_index_dir"])
    frozen["rag_v2"].update({
        "decided_by": "docs/RAG_V2_CRITERIA.md section 7.4",
        "extra_round_config": retriever.describe(),
        "selected_from_reports": reports,
        "method": f"config {retriever.name}: hybrid top {retriever.pool}"
                  + (" (prefixed index text)" if retriever.settings["index_prefix"] else "")
                  + (" + rewritten queries" if retriever.settings["rewrite"] else "")
                  + f" re-scored by the cross-encoder, top {config['reranker']['top_k']} kept",
        "replaces": config["rag_v2"]["frozen_retrieval"],
    })
    return frozen


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Freeze the winner of the RAG v2 extra round into new files.")
    parser.add_argument("--config", required=True, choices=["A", "B", "C", "D"])
    parser.add_argument("--reports", nargs="+", required=True, help="the evaluation reports of the selection")
    args = parser.parse_args(argv)
    config = load_config()
    extra = config["rag_v2"]["extra_round"]
    out_path, manifest_path = project_path(extra["frozen_retrieval"]), project_path(extra["frozen_manifest"])
    if out_path.exists() or manifest_path.exists():   # check before the slow work
        sys.exit(f"Refusing to overwrite {out_path} / {manifest_path}.")

    retriever = build(config, args.config)
    frozen = freeze_extra(config, retriever, args.reports)
    save(frozen, out_path, force=False)
    manifest = {"description": "RAG v2 extra-round frozen retrieval (src/freeze_rag_v2_extra.py); never changed "
                               "after freezing. The earlier freeze is kept unchanged.",
                "file": extra["frozen_retrieval"], "sha256": sha256_of_file(out_path),
                "created_at": frozen["created_at"], "config": args.config, "sibling_expansion": False,
                "corpus_sha256": frozen["reproducibility"]["passages_sha256"], "n_cases": len(frozen["cases"])}
    save(manifest, manifest_path, force=False)
    print(f"Saved {out_path}\nsha256 {manifest['sha256']}")
    for case_id, case in frozen["cases"].items():
        print(f"{case_id:<6}{' '.join(p['passage_id'] for p in case['passages'])}")


if __name__ == "__main__":
    main()
