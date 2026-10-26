"""Study 2: freeze GDPR retrieval for the synthetic variant cases (e.g. 01.1 = case 01 + one added text).

A variant case lives next to the development cases (data/cases/<id>/, with variant.json). Its retrieval is made with
exactly the code and settings of the frozen reranked development file (src/freeze_retrieval_gdpr.py,
GdprDevFreezer.retrieve_case_reranked): GDPR Chapters I-V, hybrid top 20, cross-encoder reranker, top 5 kept.

Proof that the setup is the same: the script first re-runs the 7 development cases and stops, without saving,
unless every one of them gives the same top 5 (ids and order) as data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json.
That file is only read, never changed. The variants go into their own file (study2_gdpr.frozen_variants_rerank).

Run from the project root:  .venv\\Scripts\\python.exe -m src.freeze_retrieval_gdpr_variants
"""

import argparse
import json
import sys

from src.config import load_config, project_path
from src.freeze_retrieval import save, sha256_of_file
from src.freeze_retrieval_gdpr import GdprDevFreezer


def top5(case: dict) -> list[str]:
    return [p["passage_id"] for p in case["passages"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze reranked GDPR retrieval for the variant cases.")
    parser.add_argument("--force", action="store_true", help="replace an existing frozen variants file")
    args = parser.parse_args()

    config = load_config()
    gdpr = config["study2_gdpr"]
    output_path = project_path(gdpr["frozen_variants_rerank"])
    if output_path.exists() and not args.force:  # check before the slow work
        sys.exit(f"Refusing to overwrite {output_path}. Use --force to replace it on purpose.")

    frozen_dev_path = project_path(gdpr["frozen_dev_rerank_restricted"])
    frozen_dev = json.loads(frozen_dev_path.read_text(encoding="utf-8"))

    freezer = GdprDevFreezer(config)
    _, rerank = freezer.freeze_both()
    mismatches = [c for c in freezer.case_ids if top5(rerank["cases"][c]) != top5(frozen_dev["cases"][c])]
    if mismatches:
        sys.exit(f"Not saved: development cases {mismatches} do not reproduce the frozen top 5 of {frozen_dev_path}.")
    print(f"Reproduced the frozen top 5 of all {len(freezer.case_ids)} development cases.")

    variant_ids = list(gdpr["variant_ids"])
    variants = {key: value for key, value in rerank.items() if key != "cases"}
    variants["study2"] = dict(rerank["study2"], case_ids=variant_ids,
                              study="Study 2 (GDPR), synthetic variant cases",
                              same_setup_as=gdpr["frozen_dev_rerank_restricted"],
                              same_setup_as_sha256=sha256_of_file(frozen_dev_path),
                              development_top5_reproduced=freezer.case_ids)
    variants["cases"] = {case_id: freezer.retrieve_case_reranked(case_id) for case_id in variant_ids}
    save(variants, output_path, force=args.force)
    print(f"Saved {output_path}")

    for case_id, case in variants["cases"].items():
        meta = json.loads((freezer.cases_dir / case_id / "variant.json").read_text(encoding="utf-8"))
        ids = top5(case)
        target = meta["target_passage_id"]
        where = f"rank {ids.index(target) + 1}" if target in ids else "NOT in top 5"
        print(f"{case_id}: top 5 = {ids}; target {target}: {where}")


if __name__ == "__main__":
    main()
