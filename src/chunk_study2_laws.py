"""Study 2 (more EU laws): split the four new laws into passages and build the combined development corpus.

Input:  data/knowledge_study2/raw/*.html, described in data/knowledge_study2/sources.json
        data/knowledge_study2/article_selection.json   keep/drop decision + reason for every article
        data/knowledge_gdpr/passages_ch1-5.jsonl       the GDPR-only corpus of Study 2 (not changed)
Output: data/knowledge_study2/passages_new_laws_all.jsonl  every article of the 4 laws, one Passage per line
        data/knowledge_study2/passages_combined_dev.jsonl  the GDPR ch1-5 lines (byte-identical, same order),
                                                            then the passages of the kept articles
(paths in config.yaml study2_laws)

Chunking is Study 1's unchanged DirectiveChunker with Study 1's chunking.max_passage_chars. Passage ids get the
prefixes of sources.json: ECD-, TPWC-, CCD-, OSH-. The two old laws (ECD 2000, OSH 1989) exist on CELLAR only as
legacy HTML without article markup; src/legacy_html_study2_laws.py adds that markup in a temporary folder first
(the raw file is never changed), and a word check proves that no word of an article is lost on the way.

The article rule (docs/C3_V2_DEVELOPMENT.md section 5) keeps or drops whole articles; the decisions are in
article_selection.json, which must name every article of every law exactly once.

Existing output files are never overwritten unless --force is given.

Run from the project root:  .venv\\Scripts\\python.exe -m src.chunk_study2_laws
"""

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from src.config import load_config, project_path
from src.legacy_html_study2_laws import FOOTNOTE, Conversion, convert, leaf_lines, split_articles, to_bytes
from src.retrieval.chunker import DirectiveChunker, write_jsonl
from src.retrieval.passage import Passage, load_passages

WORD = re.compile(r"\w+")


def load_sources(config: dict) -> dict:
    return json.loads(project_path(config["study2_laws"]["knowledge_sources"]).read_text(encoding="utf-8"))


def chunk_law(source: dict, raw_dir: Path, max_chars: int) -> tuple[list[Passage], Conversion | None]:
    """All passages of one law (and, for a legacy HTML law, what the conversion removed)."""
    if source["format"] == "xhtml":
        return DirectiveChunker(raw_dir, {"directives": [source]}, max_chars).chunk_directive(source), None
    if source["format"] != "legacy_html":
        raise ValueError(f"{source['id_prefix']}: unknown format {source['format']!r}")
    conversion = convert(raw_dir / source["file"])
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder) / source["file"]).write_bytes(to_bytes(conversion))
        passages = DirectiveChunker(Path(folder), {"directives": [source]}, max_chars).chunk_directive(source)
    return passages, conversion


def lost_words(source: dict, raw_dir: Path, passages: list[Passage]) -> dict[int, list[str]]:
    """{article: words of the legacy text that are in none of its passages} (footnote markers excepted)."""
    articles = split_articles(leaf_lines(raw_dir / source["file"]), Conversion(document=None))
    passage_words = {}
    for p in passages:
        passage_words.setdefault(p.article, set()).update(WORD.findall(p.text))
    lost = {}
    for number, lines in articles:
        words = {w for line in lines for w in WORD.findall(FOOTNOTE.sub("", line))}
        missing = sorted(words - passage_words.get(number, set()))
        if missing:
            lost[number] = missing
    return lost


def check_selection(selection: dict, passages_by_law: dict[str, list[Passage]]) -> None:
    """Every article of every law must have exactly one decision, with its title as the chunker reads it."""
    for prefix, passages in passages_by_law.items():
        titles = {p.article: p.title for p in passages}
        decisions = selection["laws"][prefix]
        numbers = [d["article"] for d in decisions]
        if sorted(numbers) != sorted(titles) or len(numbers) != len(set(numbers)):
            raise ValueError(f"{prefix}: article_selection.json must name articles {sorted(titles)} once each")
        for d in decisions:
            if d["decision"] not in ("keep", "drop") or not d["reason"]:
                raise ValueError(f"{prefix} Art{d['article']}: decision must be keep/drop with a reason")
            if d["title"] != titles[d["article"]]:
                raise ValueError(f"{prefix} Art{d['article']}: title {d['title']!r} != {titles[d['article']]!r}")


def kept_passages(selection: dict, passages_by_law: dict[str, list[Passage]]) -> list[Passage]:
    """The passages of the kept articles, law by law in sources.json order, in article order."""
    kept = []
    for prefix, passages in passages_by_law.items():
        keep = {d["article"] for d in selection["laws"][prefix] if d["decision"] == "keep"}
        kept += [p for p in passages if p.article in keep]
    return kept


def write_combined(gdpr_path: Path, new_passages: list[Passage], output: Path) -> None:
    """GDPR lines copied byte for byte, then one JSON line per new passage (written like write_jsonl).

    The new lines end like the GDPR file's lines (CRLF in a Windows working copy, LF in git), so the file never
    mixes line endings; its SHA-256 is recorded by the freezer.
    """
    gdpr_ids = {p.id for p in load_passages(gdpr_path)}
    clash = gdpr_ids & {p.id for p in new_passages}
    if clash:
        raise ValueError(f"passage ids used twice: {sorted(clash)}")
    gdpr_bytes = gdpr_path.read_bytes()
    if not gdpr_bytes.endswith(b"\n"):
        raise ValueError(f"{gdpr_path} must end with a line break")
    ending = "\r\n" if gdpr_bytes.endswith(b"\r\n") else "\n"
    lines = b"".join((json.dumps(p.to_dict(), ensure_ascii=False) + ending).encode("utf-8") for p in new_passages)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(gdpr_bytes + lines)


def main(config: dict | None = None, argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Chunk the four Study 2 laws and build the combined corpus.")
    parser.add_argument("--force", action="store_true", help="replace existing output files")
    args = parser.parse_args(argv)

    config = config or load_config()
    settings = config["study2_laws"]
    outputs = [project_path(settings["passages_new_laws_all"]), project_path(settings["passages_combined"])]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.force:
        sys.exit(f"Refusing to overwrite {existing}. Use --force to replace them on purpose.")

    sources = load_sources(config)
    raw_dir = project_path(settings["knowledge_raw"])
    max_chars = config["chunking"]["max_passage_chars"]
    passages_by_law = {}
    for source in sources["directives"]:
        passages, conversion = chunk_law(source, raw_dir, max_chars)
        passages_by_law[source["id_prefix"]] = passages
        over = [p.id for p in passages if p.n_chars > max_chars]
        print(f"{source['id_prefix']} {source['number']} ({source['format']}): {len(passages)} passages from "
              f"{len({p.article for p in passages})} articles; longer than {max_chars}: {over or 'none'}")
        if conversion:
            lost = lost_words(source, raw_dir, passages)
            if lost:
                raise ValueError(f"{source['id_prefix']}: words lost in conversion: {lost}")
            print(f"  legacy HTML: no word lost; removed footnote markers {conversion.removed_footnotes or 'none'}; "
                  f"dropped headings {conversion.dropped_headings}; untitled articles "
                  f"{conversion.untitled_articles or 'none'}")

    selection = json.loads(project_path(settings["article_selection"]).read_text(encoding="utf-8"))
    check_selection(selection, passages_by_law)
    all_new = [p for passages in passages_by_law.values() for p in passages]
    write_jsonl(all_new, outputs[0])
    kept = kept_passages(selection, passages_by_law)
    gdpr_path = project_path(config["study2_gdpr"]["passages_restricted"])
    write_combined(gdpr_path, kept, outputs[1])

    print(f"\n{'law':<6}{'articles kept':>15}{'dropped':>9}{'passages added':>16}")
    for prefix, passages in passages_by_law.items():
        decisions = selection["laws"][prefix]
        n_keep = sum(d["decision"] == "keep" for d in decisions)
        print(f"{prefix:<6}{n_keep:>15}{len(decisions) - n_keep:>9}"
              f"{sum(p.id.startswith(prefix + '-') for p in kept):>16}")
    n_gdpr = len(load_passages(gdpr_path))
    print(f"\nWritten {outputs[0]} ({len(all_new)} passages)")
    print(f"Written {outputs[1]} ({n_gdpr} GDPR + {len(kept)} new = {n_gdpr + len(kept)} passages)")


if __name__ == "__main__":
    main()
