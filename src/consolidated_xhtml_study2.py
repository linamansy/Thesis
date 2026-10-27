"""Study 2 corpus: read a CONSOLIDATED EUR-Lex text (e.g. the CRD 02011L0083-20220528) with the Study 1 chunker rules.

A consolidated text (the law with all its amendments worked in) is marked up differently from the Official Journal
XHTML that DirectiveChunker (src/retrieval/chunker.py) reads:

  Official Journal XHTML                       consolidated XHTML
  <div id="009.001"> 1. text ... </div>         <div class="norm"><span class="no-parag">1.</span>
                                                  <div class="norm inline-element">text ...</div></div>
  point table  <table><tr><td>(a)</td>...       <div class="grid-container grid-list"> label | text </div>
  -                                             <p class="modref">▼M2</p>  (marks where an amendment starts)
  footnote link around "oj-note-tag"            footnote link <a href="#E0006"><span class="superscript">6</span></a>
  subparagraph inside the paragraph div         <p class="norm"> after the paragraph's div (same article)

and inserted articles or paragraphs have a letter: Article 6a, paragraph 1a.

to_oj_markup() rewrites a copy of the document in memory into the Official Journal markup (the raw file is never
changed): amendment markers and footnote links are removed, every point list becomes a point table, every numbered paragraph becomes a
paragraph div whose first line starts with its number ("1a. ..."), and a subparagraph is moved into the paragraph
before it. ConsolidatedChunker is DirectiveChunker with one difference: article and paragraph numbers may carry a
letter (ids CRD-Art6a-1, CRD-Art9-1a). A number without a letter stays an int, so CRD-Art9-1 is built exactly like
Study 1's CRD-Art9-1. Splitting long paragraphs by their points is DirectiveChunker's, unchanged.

lost_words() is the word check: every word of a kept article's raw text (amendment markers and footnote links
excepted) must be in one of its passages.
"""

import re
from pathlib import Path

from lxml import etree, html

from src.retrieval.chunker import SKIPPED_CLASSES, DirectiveChunker, clean, render
from src.retrieval.passage import Passage

ARTICLE_ID = re.compile(r"art_(\d+[a-z]?)")   # "art_6a"; not "art_6a.tit_1" (the title block)
NUMBER = re.compile(r"(\d+[a-z]?)\.")         # the paragraph number in <span class="no-parag">1a. </span>
WORD = re.compile(r"\w+")
BLOCKS = {"p", "div", "table"}


def number_value(text: str) -> int | str:
    """"9" -> 9 (as in Study 1), "6a" -> "6a"."""
    return int(text) if text.isdigit() else text


def has_class(element, name: str) -> bool:
    return name in (element.get("class") or "").split()


def point_table(grid) -> etree._Element:
    """<div class="grid-container grid-list"> (label column + text column) -> <table><tr><td>(a)</td><td>..."""
    label_cell, text_cell = etree.Element("td"), etree.Element("td")
    label_cell.text = clean(grid.xpath('./div[contains(@class, "grid-list-column-1")]')[0].text_content())
    column = grid.xpath('./div[contains(@class, "grid-list-column-2")]')[0]
    if column.text and column.text.strip():               # text directly in the column: give it its own line
        line = etree.SubElement(text_cell, "p")
        line.text = column.text
    for child in list(column):
        text_cell.append(point_table(child) if has_class(child, "grid-list") else child)
    row = etree.Element("tr")
    row.extend([label_cell, text_cell])
    table = etree.Element("table")
    table.append(row)
    return table


def replace_point_lists(root) -> None:
    """Every point list in root becomes a point table (innermost lists are handled inside point_table)."""
    for grid in root.xpath('.//div[contains(@class, "grid-list")][contains(@class, "grid-container")]'):
        if grid.getparent() is not None and not grid.xpath('ancestor::div[contains(@class, "grid-container")]'):
            grid.getparent().replace(grid, point_table(grid))


def paragraph_div(norm, number: str) -> etree._Element:
    """<div class="norm"><span class="no-parag">1.</span><div class="norm inline-element">...</div></div>
    -> <div data-paragraph="1">  first line "1. text", then the other lines and point tables."""
    body = norm.xpath('./div[contains(@class, "inline-element")]')[0]
    new = etree.Element("div", {"data-paragraph": number})
    if not any(child.tag in BLOCKS for child in body):     # plain text only: one line
        first = etree.SubElement(new, "p")
        first.text = f"{number}. " + body.text_content()
        return new
    if body.text and body.text.strip():
        first = etree.SubElement(new, "p")
        first.text = body.text
    new.extend(list(body))
    if len(new) and new[0].tag == "p":
        new[0].text = f"{number}. " + (new[0].text or "")
    else:                                                   # the paragraph starts with a point list
        first = etree.Element("p")
        first.text = f"{number}."
        new.insert(0, first)
    return new


def read_without_markers(path: Path) -> html.HtmlElement:
    """The document without amendment markers (<p class="modref">▼M2</p>) and footnote links
    (<a href="#E0006"><span class="superscript">6</span></a>); drop_tree keeps the text that follows them."""
    doc = html.fromstring(Path(path).read_bytes())
    for marker in doc.xpath('//p[contains(@class, "modref")] | //a[starts-with(@href, "#")][span[@class="superscript"]]'):
        marker.drop_tree()
    return doc


def to_oj_markup(path: Path) -> html.HtmlElement:
    """The consolidated document rewritten into the markup DirectiveChunker reads (in memory)."""
    doc = read_without_markers(path)
    for article in doc.xpath('//div[@class="eli-subdivision"][starts-with(@id, "art_")]'):
        if not ARTICLE_ID.fullmatch(article.get("id")):
            continue
        for heading in article.xpath('./p[contains(@class, "title-article-norm")]'):
            heading.set("class", "oj-ti-art")             # the "Article 9" line, skipped like in the OJ text
        replace_point_lists(article)
        current = None                                       # the last numbered paragraph div
        for child in list(article):
            spans = child.xpath('./span[@class="no-parag"]') if child.tag == "div" else []
            if spans:
                current = paragraph_div(child, NUMBER.fullmatch(clean(spans[0].text_content())).group(1))
                article.replace(child, current)
            elif current is not None and child.get("class") not in SKIPPED_CLASSES:
                current.append(child)                        # a subparagraph belongs to the paragraph before it
    return doc


class ConsolidatedChunker(DirectiveChunker):
    """DirectiveChunker for to_oj_markup() documents: article and paragraph numbers may carry a letter."""

    def chunk_directive(self, source: dict) -> list[Passage]:
        doc = to_oj_markup(self.raw_dir / source["file"])
        passages = []
        for article in doc.xpath('//div[@class="eli-subdivision"][starts-with(@id, "art_")]'):
            match = ARTICLE_ID.fullmatch(article.get("id"))
            if not match:
                continue
            number = number_value(match.group(1))
            title_el = article.xpath('./div[@class="eli-title"]')
            title = clean(title_el[0].text_content()) if title_el else ""
            for paragraph, element, lines in self.split_article(article):
                passage = self.make_passage(source, number, paragraph, title, lines)
                if passage.n_chars > self.max_chars and element is not None:
                    passages += self.split_by_points(source, number, paragraph, title, element) or [passage]
                else:
                    passages.append(passage)
        return passages

    def split_article(self, article) -> list[tuple]:
        paragraphs = [child for child in article if child.get("data-paragraph")]
        if paragraphs:
            return [(number_value(div.get("data-paragraph")), div, render(div)) for div in paragraphs]
        return super().split_article(article)   # no numbered paragraphs: the whole article is one passage


def lost_words(raw_path: Path, passages: list[Passage]) -> dict:
    """{article: words of its raw consolidated text that are in none of its passages} (amendment markers, the
    "Article N" heading and the title excepted, as in every Study 1 passage heading)."""
    doc = read_without_markers(raw_path)
    passage_words = {}
    for p in passages:
        passage_words.setdefault(p.article, set()).update(WORD.findall(p.text))
    lost = {}
    for article in doc.xpath('//div[@class="eli-subdivision"][starts-with(@id, "art_")]'):
        match = ARTICLE_ID.fullmatch(article.get("id"))
        if not match or number_value(match.group(1)) not in passage_words:
            continue
        words = set(WORD.findall(article.text_content()))
        missing = sorted(words - passage_words[number_value(match.group(1))])
        if missing:
            lost[number_value(match.group(1))] = missing
    return lost
