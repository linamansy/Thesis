"""Study 2 law corpus (step 2): build and freeze the passages of the KEPT articles of the five laws.

Input:  data/knowledge_study2_corpus/sources.json   the five laws (GDPR, CRD, LPD, SGD, ECD) and their raw files
        docs/STUDY2_CORPUS_RULE.md section 3          the approved keep/exclude table of every law (read as is)
Output: data/knowledge_study2_corpus/passages.jsonl   one Passage per line, kept articles only
        data/knowledge_study2_corpus/manifest.json    passage count per law and the SHA-256 of passages.jsonl
(paths in config.yaml study2_corpus)

Unit (as in the GDPR corpus): one passage per article paragraph, lettered points kept with their paragraph, long
paragraphs split by their points (Study 1's DirectiveChunker and chunking.max_passage_chars, unchanged). Ids like
CRD-Art9-1. Each law is read the way the earlier corpora read it: Official Journal XHTML by DirectiveChunker (GDPR,
LPD, SGD), the legacy ECD HTML through src/legacy_html_study2_laws.py, the consolidated CRD through
src/consolidated_xhtml_study2.py (its inserted Article 6a and paragraphs 1a, 2a give ids CRD-Art6a-1, CRD-Art9-1a;
there "article" / "paragraph" are strings, everywhere else ints).

Checks before anything is written (the build stops if one fails):
  - every raw file has the SHA-256 of sources.json;
  - the table names every article of the law exactly once, with the title the chunker reads, keep or exclude;
  - no word of a kept article is lost (CRD and ECD, whose markup is rewritten first);
  - GDPR, LPD and ECD passages are identical to the same passages of the earlier corpora
    (data/knowledge_gdpr/passages.jsonl, data/knowledge/passages.jsonl, data/knowledge_study2/passages_new_laws_all.jsonl).
The Study 1 corpus and the GDPR-only corpus are only read, never written.

passages.jsonl is written with "\\n" line endings (and is marked -text in .gitattributes), so its SHA-256 is the same
in every checkout. An existing output is never overwritten unless --force is given.

Run from the project root:  .venv\\Scripts\\python.exe -m src.build_study2_corpus
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from src.chunk_study2_laws import chunk_law, lost_words as legacy_lost_words
from src.config import load_config, project_path
from src.consolidated_xhtml_study2 import ConsolidatedChunker, lost_words as consolidated_lost_words
from src.retrieval.passage import Passage, load_passages

ROW = re.compile(r"\| (\w+) \| (.+) \| (keep|exclude) \| (.+) \|")   # "| 9 | Right of withdrawal | keep | ... |"

# The passages of the earlier corpora that the same laws must reproduce exactly (built from the same raw files).
EARLIER_CORPORA = {"GDPR": "data/knowledge_gdpr/passages.jsonl", "LPD": "data/knowledge/passages.jsonl",
                   "ECD": "data/knowledge_study2/passages_new_laws_all.jsonl"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def article_key(article: int | str) -> str:
    return str(article)


def read_selection(doc_path: Path, heading: str) -> list[dict]:
    """The rows of one law's table in the rule document: [{"article", "title", "decision", "reason"}, ...]."""
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    if heading not in lines:
        raise ValueError(f"{doc_path}: no table heading {heading!r}")
    rows = []
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("#"):
            break
        match = ROW.fullmatch(line.strip())
        if match:
            rows.append(dict(zip(("article", "title", "decision", "reason"), match.groups())))
    return rows


def chunk(source: dict, max_chars: int) -> list[Passage]:
    """All passages of one law, in article order."""
    raw_dir = project_path(source["raw_dir"])
    if source["format"] == "consolidated_xhtml":
        return ConsolidatedChunker(raw_dir, {"directives": [source]}, max_chars).chunk_directive(source)
    return chunk_law(source, raw_dir, max_chars)[0]   # xhtml or legacy_html, as in the earlier Study 2 corpus


def check_raw_file(source: dict) -> None:
    path = project_path(source["raw_dir"]) / source["file"]
    if sha256_bytes(path.read_bytes()) != source["sha256"]:
        raise ValueError(f"{source['id_prefix']}: {path} does not have the SHA-256 of sources.json")


def check_selection(prefix: str, rows: list[dict], passages: list[Passage]) -> None:
    """The table must name every article of the law once, with the title the chunker reads."""
    titles = {article_key(p.article): p.title for p in passages}
    numbers = [r["article"] for r in rows]
    if sorted(numbers) != sorted(titles) or len(numbers) != len(set(numbers)):
        raise ValueError(f"{prefix}: the table must name articles {sorted(titles)} once each, got {numbers}")
    for r in rows:
        if r["title"] != titles[r["article"]]:
            raise ValueError(f"{prefix} Art{r['article']}: title {r['title']!r} != {titles[r['article']]!r}")


def check_no_word_lost(source: dict, kept: list[Passage]) -> None:
    raw_dir = project_path(source["raw_dir"])
    if source["format"] == "consolidated_xhtml":
        lost = consolidated_lost_words(raw_dir / source["file"], kept)
    elif source["format"] == "legacy_html":
        lost = {a: w for a, w in legacy_lost_words(source, raw_dir, kept).items()
                if a in {p.article for p in kept}}
    else:
        return
    if lost:
        raise ValueError(f"{source['id_prefix']}: words lost in kept articles: {lost}")


def check_same_as_earlier(prefix: str, kept: list[Passage]) -> None:
    if prefix not in EARLIER_CORPORA:
        return
    earlier = {p.id: p for p in load_passages(project_path(EARLIER_CORPORA[prefix]))}
    different = [p.id for p in kept if earlier.get(p.id) != p]
    if different:
        raise ValueError(f"{prefix}: passages differ from {EARLIER_CORPORA[prefix]}: {different}")


def build(config: dict) -> tuple[list[Passage], dict]:
    """(kept passages of all five laws, in sources.json order; per-law counts)."""
    settings = config["study2_corpus"]
    sources = json.loads(project_path(settings["sources"]).read_text(encoding="utf-8"))
    doc_path = project_path(settings["selection_doc"])
    max_chars = config["chunking"]["max_passage_chars"]
    corpus, counts = [], {}
    for source in sources["directives"]:
        prefix = source["id_prefix"]
        check_raw_file(source)
        passages = chunk(source, max_chars)
        rows = read_selection(doc_path, source["selection_heading"])
        check_selection(prefix, rows, passages)
        keep = {r["article"] for r in rows if r["decision"] == "keep"}
        kept = [p for p in passages if article_key(p.article) in keep]
        check_no_word_lost(source, kept)
        check_same_as_earlier(prefix, kept)
        corpus += kept
        counts[prefix] = {"articles": len(rows), "articles_kept": len(keep), "passages": len(kept)}
    return corpus, counts


def to_bytes(passages: list[Passage]) -> bytes:
    """The corpus file: one JSON line per passage (as write_jsonl), always "\\n" line endings."""
    return b"".join((json.dumps(p.to_dict(), ensure_ascii=False) + "\n").encode("utf-8") for p in passages)


def manifest(config: dict, counts: dict, data: bytes) -> dict:
    settings = config["study2_corpus"]
    return {"description": "Study 2 law corpus, frozen (src/build_study2_corpus.py). Kept articles only "
                           "(docs/STUDY2_CORPUS_RULE.md section 3).",
            "passages_file": settings["passages"],
            "passages_sha256": sha256_bytes(data),
            "n_passages": sum(c["passages"] for c in counts.values()),
            "per_law": counts,
            "sources_sha256": sha256_bytes(project_path(settings["sources"]).read_bytes()),
            "max_passage_chars": config["chunking"]["max_passage_chars"]}


def main(config: dict | None = None, argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build and freeze the Study 2 law corpus.")
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    args = parser.parse_args(argv)

    config = config or load_config()
    settings = config["study2_corpus"]
    outputs = [project_path(settings["passages"]), project_path(settings["manifest"])]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.force:
        sys.exit(f"Refusing to overwrite {existing}. Use --force to replace them on purpose.")

    corpus, counts = build(config)
    data = to_bytes(corpus)
    outputs[0].parent.mkdir(parents=True, exist_ok=True)
    outputs[0].write_bytes(data)
    info = manifest(config, counts, data)
    outputs[1].write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{'law':<6}{'articles':>10}{'kept':>6}{'passages':>10}")
    for prefix, c in counts.items():
        print(f"{prefix:<6}{c['articles']:>10}{c['articles_kept']:>6}{c['passages']:>10}")
    print(f"total{sum(c['articles'] for c in counts.values()):>11}"
          f"{sum(c['articles_kept'] for c in counts.values()):>6}{info['n_passages']:>10}")
    print(f"Written {outputs[0]} (SHA-256 {info['passages_sha256']})")
    print(f"Written {outputs[1]}")


if __name__ == "__main__":
    main()
