"""Study 2: split the GDPR into passages, with exactly the same rules as Study 1.

Input:  data/knowledge_gdpr/raw/GDPR_2016_679.html, described in data/knowledge_gdpr/sources.json
Output: data/knowledge_gdpr/passages.jsonl        all 99 articles, one Passage per line
        data/knowledge_gdpr/passages_ch1-5.jsonl  only the articles of the included chapters
                                                  (config.yaml study2_gdpr.included_chapters: I-V = Art 1-50)

This file only points the unchanged DirectiveChunker (src/retrieval/chunker.py) at the GDPR paths in the
config.yaml study2_gdpr section. The passage size limit is Study 1's chunking.max_passage_chars. Study 1's
files (data/knowledge/) are never read or written here.

The restricted file is the full file with the passages of the other chapters left out; every kept line is
byte-identical to its line in the full file. The chapter of each article is read from the official XHTML,
where every chapter is a block <div class="eli-subdivision" id="cpt_IV"> that contains its articles.
Reason for the restriction (decided 24 Oct 2026 on development cases, same for C2 and C3): Chapters VI-XI
address supervisory authorities, remedies, specific national situations and final provisions, not an
organisation's process.

Run from the project root:  .venv\\Scripts\\python.exe -m src.chunk_gdpr
"""

import json
import re
from pathlib import Path

from lxml import html

from src.config import load_config, project_path
from src.retrieval.chunker import DirectiveChunker, write_jsonl
from src.retrieval.passage import Passage

CHAPTER_ID = re.compile(r"cpt_([IVXLC]+)")   # e.g. "cpt_IV" = Chapter IV (not "cpt_IV.sct_1", a section)


def gdpr_chunker(config: dict) -> DirectiveChunker:
    """A DirectiveChunker that reads the GDPR source instead of the Study 1 directives."""
    paths = config["study2_gdpr"]
    sources = json.loads(project_path(paths["knowledge_sources"]).read_text(encoding="utf-8"))
    return DirectiveChunker(project_path(paths["knowledge_raw"]), sources, config["chunking"]["max_passage_chars"])


def article_chapters(xhtml_path: Path) -> dict[int, str]:
    """{article number: chapter number as a Roman numeral}, read from the chapter blocks of the XHTML."""
    doc = html.fromstring(Path(xhtml_path).read_bytes())
    chapters = {}
    for chapter in doc.xpath('//div[starts-with(@id, "cpt_")]'):
        match = CHAPTER_ID.fullmatch(chapter.get("id"))
        if not match:
            continue
        for article in chapter.xpath('.//div[@class="eli-subdivision"][starts-with(@id, "art_")]'):
            chapters[int(article.get("id").removeprefix("art_"))] = match.group(1)
    return chapters


def restrict_to_chapters(passages: list[Passage], chapters: dict[int, str], included: list[str]) -> list[Passage]:
    """The passages whose article lies in one of the included chapters, in their original order."""
    missing = sorted({p.article for p in passages} - set(chapters))
    if missing:
        raise ValueError(f"No chapter found for articles {missing}")
    return [p for p in passages if chapters[p.article] in included]


def main() -> None:
    config = load_config()
    settings = config["study2_gdpr"]
    chunker = gdpr_chunker(config)
    passages = chunker.chunk_all()
    output = project_path(settings["passages"])
    write_jsonl(passages, output)

    sizes = sorted(p.n_chars for p in passages)
    over = [p.id for p in passages if p.n_chars > config["chunking"]["max_passage_chars"]]
    print(f"GDPR: {len(passages)} passages from {len({p.article for p in passages})} articles "
          f"(characters: min {sizes[0]}, median {sizes[len(sizes) // 2]}, max {sizes[-1]})")
    print(f"Longer than chunking.max_passage_chars: {over or 'none'}")
    print(f"Written to {output}")

    source = chunker.sources["directives"][0]
    chapters = article_chapters(chunker.raw_dir / source["file"])
    restricted = restrict_to_chapters(passages, chapters, settings["included_chapters"])
    restricted_output = project_path(settings["passages_restricted"])
    write_jsonl(restricted, restricted_output)
    articles = sorted({p.article for p in restricted})
    print(f"Chapters {', '.join(settings['included_chapters'])}: {len(restricted)} passages from "
          f"{len(articles)} articles (Art {articles[0]}-{articles[-1]}), written to {restricted_output}")


if __name__ == "__main__":
    main()
