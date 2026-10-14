"""DirectiveChunker: splits the two EU directives into passages for retrieval.

Input:  the official English XHTML of each directive (data/knowledge/raw/), described in
        data/knowledge/sources.json
Output: data/knowledge/passages.jsonl, one Passage per line

Rules (CLAUDE.md, RAG section):
  - Keep only the articles. Recitals, annexes and the signature part are dropped.
    The definitions article is kept.
  - One passage = one numbered paragraph ("1.", "2.", ...). Lettered points (a), (b), (c)
    stay inside the passage of their paragraph.
  - An article without numbered paragraphs becomes one passage.
    Exception: an article made of numbered points (1), (2), ... (the definitions article)
    gives one passage per numbered point, each starting with the article's introductory
    sentence. Otherwise the definitions would form one very long passage.
  - Every passage starts with the directive name and the article title.
  - Ids: <prefix>-Art<article>-<paragraph>, e.g. CRD-Art9-1 and LPD-Art3-1.

How the EUR-Lex XHTML marks the text:
  articles             <div class="eli-subdivision" id="art_9">
  article title        <div class="eli-title"><p class="oj-sti-art">Right of withdrawal</p></div>
  numbered paragraphs  <div id="009.001"> ... </div>
  (a), (b) or (1), (2) a two-column table: label | text (tables can be nested)
  footnote markers     a link around an element with class "oj-note-tag" (removed)

Run from the project root:  .venv\\Scripts\\python.exe -m src.retrieval.chunker
"""

import json
import re
from pathlib import Path

from lxml import html

from src.config import load_config, project_path
from src.retrieval.passage import Passage

PARAGRAPH_ID = re.compile(r"\d{3}\.\d{3}")   # e.g. "009.001" = article 9, paragraph 1
NUMBERED_POINT = re.compile(r"\((\d+)\)")      # e.g. "(1)" in the definitions article
SKIPPED_CLASSES = {"oj-ti-art", "eli-title"}   # the "Article 9" heading and the title block


def clean(text: str) -> str:
    """Collapse all whitespace (including non-breaking spaces and line breaks) into single spaces."""
    return " ".join(text.split())


class DirectiveChunker:
    """Turns the directives listed in sources.json into Passage objects."""

    def __init__(self, raw_dir: Path, sources: dict):
        self.raw_dir = Path(raw_dir)
        self.sources = sources

    @classmethod
    def from_config(cls, config: dict) -> "DirectiveChunker":
        paths = config["paths"]
        sources = json.loads(project_path(paths["knowledge_sources"]).read_text(encoding="utf-8"))
        return cls(project_path(paths["knowledge_raw"]), sources)

    def chunk_all(self) -> list[Passage]:
        passages = []
        for source in self.sources["directives"]:
            passages += self.chunk_directive(source)
        return passages

    def chunk_directive(self, source: dict) -> list[Passage]:
        """All passages of one directive, in article order."""
        doc = html.fromstring((self.raw_dir / source["file"]).read_bytes())
        # Footnote markers look like <a href="#ntr...">(<span class="oj-note-tag">1</span>)</a>.
        # Remove the whole link, brackets included; drop_tree keeps the text that follows it.
        for marker in doc.xpath('//a[.//*[contains(@class, "oj-note-tag")]] | //*[contains(@class, "oj-note-tag")]'):
            if marker.getparent() is not None:
                marker.drop_tree()

        passages = []
        for article in doc.xpath('//div[@class="eli-subdivision"][starts-with(@id, "art_")]'):
            number = int(article.get("id").removeprefix("art_"))
            title_el = article.xpath('./div[@class="eli-title"]')
            title = clean(title_el[0].text_content()) if title_el else ""
            for paragraph, lines in self.split_article(article):
                passages.append(self.make_passage(source, number, paragraph, title, lines))
        return passages

    def split_article(self, article) -> list[tuple[int, list[str]]]:
        """Split one article into (paragraph number, text lines) pieces."""
        paragraph_divs = [child for child in article
                          if child.tag == "div" and PARAGRAPH_ID.fullmatch(child.get("id") or "")]
        if paragraph_divs:
            return [(int(div.get("id").split(".")[1]), render(div)) for div in paragraph_divs]

        top_tables = [child for child in article if child.tag == "table"]
        if top_tables and all(NUMBERED_POINT.fullmatch(table_label(t)) for t in top_tables):
            # Definitions-style article: introductory sentence + one numbered point per passage.
            first_point = article.index(top_tables[0])
            intro, after = [], []
            for position, child in enumerate(article):
                if child.tag == "table" or child.get("class") in SKIPPED_CLASSES:
                    continue
                text = clean(child.text_content())
                if text:
                    # Text before the first point is the intro; text after the points is kept too.
                    (intro if position < first_point else after).append(text)
            pieces = []
            for table in top_tables:
                number = int(NUMBERED_POINT.fullmatch(table_label(table)).group(1))
                pieces.append((number, intro + render_table(table)))
            pieces[-1] = (pieces[-1][0], pieces[-1][1] + after)
            return pieces

        return [(1, render(article))]  # no numbered paragraphs: the whole article is one passage

    def make_passage(self, source: dict, article: int, paragraph: int, title: str, lines: list[str]) -> Passage:
        heading = f"{source['short_name']} ({source['number']}) - Article {article}: {title}"
        text = "\n".join([heading] + lines)
        return Passage(
            id=f"{source['id_prefix']}-Art{article}-{paragraph}",
            directive=source["number"],
            article=article,
            paragraph=paragraph,
            title=title,
            text=text,
            n_chars=len(text),
        )


def render(element) -> list[str]:
    """The text inside an element as a list of lines; each lettered point gets its own line."""
    lines = []
    for child in element:
        if not isinstance(child.tag, str) or child.get("class") in SKIPPED_CLASSES:
            continue
        if child.tag == "table":
            lines += render_table(child)
        elif child.tag == "div":
            lines += render(child)
        else:
            text = clean(child.text_content())
            if text:
                lines.append(text)
    return lines


def render_table(table) -> list[str]:
    """A two-column point table, e.g. "(a) | text", as lines "(a) text". Nested tables follow their point."""
    lines = []
    for row in table.xpath("./tr | ./tbody/tr"):
        cells = row.xpath("./td")
        label = clean(cells[0].text_content()) if len(cells) > 1 else ""
        body = render(cells[-1]) if cells else []
        if body:
            lines.append(f"{label} {body[0]}".strip())
            lines += body[1:]
        elif label:
            lines.append(label)
    return lines


def table_label(table) -> str:
    """The label in the first cell of a point table, e.g. "(1)" or "(a)"."""
    cells = table.xpath("./tr/td | ./tbody/tr/td")
    return clean(cells[0].text_content()) if cells else ""


def write_jsonl(passages: list[Passage], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for passage in passages:
            f.write(json.dumps(passage.to_dict(), ensure_ascii=False) + "\n")


def main() -> None:
    config = load_config()
    chunker = DirectiveChunker.from_config(config)
    passages = chunker.chunk_all()
    output = project_path(config["paths"]["passages"])
    write_jsonl(passages, output)

    for source in chunker.sources["directives"]:
        own = [p for p in passages if p.id.startswith(source["id_prefix"] + "-")]
        sizes = [p.n_chars for p in own]
        print(f"{source['id_prefix']} {source['number']}: {len(own)} passages from "
              f"{len({p.article for p in own})} articles "
              f"(characters: min {min(sizes)}, median {sorted(sizes)[len(sizes) // 2]}, max {max(sizes)})")
    print(f"Total: {len(passages)} passages written to {output}")


if __name__ == "__main__":
    main()
