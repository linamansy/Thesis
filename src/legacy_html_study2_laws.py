"""Study 2 (more EU laws): give an old EUR-Lex HTML text the article markup that DirectiveChunker reads.

Why: for the e-Commerce Directive (2000) and the OSH Framework Directive (1989), CELLAR holds no XHTML, only the
legacy EUR-Lex HTML (data/knowledge_study2/sources.json, format "legacy_html"). That HTML is a flat list of <p>
lines without article or paragraph markup, so the unchanged DirectiveChunker (src/retrieval/chunker.py) would
find no article in it. This file builds, in memory, the same markup as the modern XHTML:

  <div class="eli-subdivision" id="art_5">                    an article
    <div class="eli-title"><p class="oj-sti-art">Title</p></div>
    <div id="005.001"> <p>1. ...</p> <table><tr><td>(a)</td><td><p>...</p></td></tr></table> ... </div>

The chunker then splits it with exactly the Study 1 rules. The words are never changed; only:
  - lines are grouped into articles, numbered paragraphs and lettered points
  - a point label alone on a line, "(a)", is joined with the next line (the point's text)
  - a line that starts in lower case continues the line before it (the old HTML breaks some sentences)
  - chapter and section headings between articles are dropped (the XHTML keeps them outside the articles too)
  - footnote markers right after a word, e.g. "Directive 89/48/EEC(27)", are removed, as the chunker removes the
    XHTML's footnote markers; a reference after a digit, e.g. "Article 1(2)", is kept
  - everything from "Done at ..." on (signatures, footnotes, annex) is dropped, as the chunker drops annexes
Every removed footnote marker and dropped heading is returned, so it can be logged.

The raw file is only read, never changed.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree, html

ARTICLE = re.compile(r"Article (\d+)")
PARAGRAPH = re.compile(r"(\d+)\.\s")                    # "1. The employer shall ..."
POINT = re.compile(r"\(([a-z]{1,4})\)(?:\s|$)")         # "(a) ..." or "(a)" alone
FOOTNOTE = re.compile(r"(?<=[A-Za-z])\((\d+)\)")       # "EEC(27)", not "Article 1(2)"
GLUED_HEADING = re.compile(r"(?<=[.;:])((?:SECTION|CHAPTER) [IVX]+)$")   # "supervision.SECTION II"
SECTION_HEADING = re.compile(r"Section \d+: |SECTION [IVX]+$|CHAPTER [IVX]+$")
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


@dataclass
class Conversion:
    """The rebuilt document plus what was removed on the way (for the log)."""
    document: object
    removed_footnotes: list[str] = field(default_factory=list)
    dropped_headings: list[str] = field(default_factory=list)
    untitled_articles: list[int] = field(default_factory=list)


def leaf_lines(path: Path) -> list[str]:
    """The text of every innermost <p> of the legal text, whitespace collapsed (empty lines removed)."""
    doc = html.fromstring(Path(path).read_bytes())
    box = doc.xpath('//div[@id="TexteOnly"]')
    if not box:
        raise ValueError(f"{path}: no <div id='TexteOnly'> (not a legacy EUR-Lex HTML file?)")
    lines = [" ".join(p.text_content().split()) for p in box[0].iter("p") if p.find(".//p") is None]
    return [line for line in lines if line]


def is_heading(line: str) -> bool:
    """A chapter or section heading between articles: 'CHAPTER II', 'PRINCIPLES', 'Section 1: ...'."""
    return bool(SECTION_HEADING.match(line)) or not any(c.islower() for c in line)


def split_articles(lines: list[str], result: Conversion) -> list[tuple[int, list[str]]]:
    """[(article number, its lines)] from 'Article 1' up to 'Done at ...'; headings in between are dropped."""
    start = lines.index("Article 1")
    end = next(i for i, line in enumerate(lines) if line.startswith("Done at "))
    articles = []
    for line in lines[start:end]:
        glued = GLUED_HEADING.search(line)
        if glued:   # e.g. "... adequate controls and supervision.SECTION II"
            result.dropped_headings.append(glued.group(1))
            line = line[:glued.start()]
        match = ARTICLE.fullmatch(line)
        if match:
            articles.append((int(match.group(1)), []))
        elif is_heading(line):
            result.dropped_headings.append(line)
        else:
            articles[-1][1].append(line)
    return articles


def join_lines(lines: list[str]) -> list[str]:
    """Join a lone point label with its text, and a line starting in lower case with the line before."""
    joined = []
    for line in lines:
        if joined and POINT.fullmatch(joined[-1]):
            joined[-1] = f"{joined[-1]} {line}"
        elif joined and line[0].islower():
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return joined


def take_title(lines: list[str]) -> tuple[str, list[str]]:
    """The article title and the remaining lines. Some old articles have no title (then '')."""
    if not lines or PARAGRAPH.match(lines[0]) or POINT.match(lines[0]) or lines[0][-1] in ".:;":
        return "", lines
    title, rest = lines[0], lines[1:]
    while title.endswith("-") and rest:     # a title broken over two lines: "Individual Directives - Amendments -"
        title, rest = f"{title} {rest[0]}", rest[1:]
    return title, rest


def point_letter(line: str, previous: str | None, later: list[str]) -> str | None:
    """The letter of a lettered point, or None if the line is not one.

    "(i)" after "(h)" is the letter i only if no "(ii)" follows; otherwise it starts a list of Roman sub-points.
    Any other point must be the next letter (or "a"), so Roman sub-points (ii), (iii) stay inside their point.
    """
    match = POINT.match(line)
    if not match:
        return None
    label = match.group(1)
    expected = "a" if previous is None else chr(ord(previous) + 1)
    if label != expected:
        return None
    if label == "i" and any(other.startswith("(ii)") for other in later):
        return None
    return label


def build_block(parent, lines: list[str]) -> None:
    """Append one block of lines (an article without paragraphs, or one paragraph) as <p> and point tables."""
    previous = None
    for position, line in enumerate(lines):
        letter = point_letter(line, previous, lines[position + 1:])
        if letter:
            previous = letter
            table = etree.SubElement(parent, "table")
            row = etree.SubElement(table, "tr")
            etree.SubElement(row, "td").text = f"({letter})"
            etree.SubElement(etree.SubElement(row, "td"), "p").text = line[POINT.match(line).end():].strip()
        else:
            etree.SubElement(parent, "p").text = line


def build_article(body, number: int, lines: list[str], result: Conversion) -> None:
    title, rest = take_title(lines)
    if not title:
        result.untitled_articles.append(number)
    article = etree.SubElement(body, "div", {"class": "eli-subdivision", "id": f"art_{number}"})
    etree.SubElement(etree.SubElement(article, "div", {"class": "eli-title"}), "p", {"class": "oj-sti-art"}).text = title

    # Numbered paragraphs must count up 1, 2, 3, ...; a line like "11. Directive ..." inside a quote is not one.
    paragraphs, expected = [], 1
    for line in rest:
        match = PARAGRAPH.match(line)
        if match and int(match.group(1)) == expected:
            paragraphs.append((expected, [line]))
            expected += 1
        elif paragraphs:
            paragraphs[-1][1].append(line)
        else:
            paragraphs.append((0, [line]))      # text before any numbered paragraph
    if paragraphs and paragraphs[0][0] == 0 and len(paragraphs) > 1:
        raise ValueError(f"Article {number}: text before its first numbered paragraph: {paragraphs[0][1]}")

    if paragraphs and paragraphs[0][0] == 0:
        build_block(article, paragraphs[0][1])  # no numbered paragraphs: the article itself holds the text
    else:
        for paragraph, block in paragraphs:
            build_block(etree.SubElement(article, "div", {"id": f"{number:03d}.{paragraph:03d}"}), block)


def convert(path: Path) -> Conversion:
    """Read a legacy EUR-Lex HTML file and return the rebuilt document (see the module comment)."""
    result = Conversion(document=None)
    root = etree.Element("html")
    body = etree.SubElement(root, "body")
    for number, lines in split_articles(leaf_lines(path), result):
        cleaned = []
        for line in lines:
            result.removed_footnotes += [f"Art{number}: ...{line[max(0, m.start() - 30):m.end()]}"
                                         for m in FOOTNOTE.finditer(line)]
            cleaned.append(FOOTNOTE.sub("", line))
        build_article(body, number, join_lines(cleaned), result)
    result.document = root
    return result


def to_bytes(conversion: Conversion) -> bytes:
    """The rebuilt document as XHTML bytes, in the form DirectiveChunker reads."""
    return etree.tostring(conversion.document, encoding="utf-8", method="html")
