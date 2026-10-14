"""Tests for src/retrieval/chunker.py: on the real directives and on a tiny hand-written one."""

import json
import re

import pytest

from src.config import load_config, project_path
from src.retrieval.chunker import DirectiveChunker, write_jsonl

CONFIG = load_config()


@pytest.fixture(scope="module")
def passages():
    return DirectiveChunker.from_config(CONFIG).chunk_all()


# ---------- the real directives ----------

def test_every_passage_has_a_unique_id(passages):
    ids = [p.id for p in passages]
    assert len(ids) == len(set(ids))


def test_every_passage_has_non_empty_text(passages):
    for p in passages:
        heading, _, body = p.text.partition("\n")
        assert body.strip(), f"{p.id} has no text after its heading"
        assert p.n_chars == len(p.text)


def test_ids_and_headings_follow_the_format(passages):
    for p in passages:
        assert re.fullmatch(r"(CRD|LPD)-Art\d+-\d+", p.id)
        assert p.id == f"{p.id.split('-')[0]}-Art{p.article}-{p.paragraph}"
        assert p.text.startswith(f"Consumer Rights Directive (2011/83/EU) - Article {p.article}: {p.title}") or \
               p.text.startswith(f"Late Payment Directive (2011/7/EU) - Article {p.article}: {p.title}")


def test_only_articles_are_kept(passages):
    articles = {prefix: {p.article for p in passages if p.id.startswith(prefix)} for prefix in ("CRD", "LPD")}
    assert articles["CRD"] == set(range(1, 36))   # Articles 1-35
    assert articles["LPD"] == set(range(1, 16))   # Articles 1-15
    all_text = " ".join(p.text for p in passages)
    assert "Whereas" not in all_text               # recitals dropped
    assert "Model withdrawal form" not in all_text  # CRD Annex I dropped
    assert "Done at" not in all_text               # signature part dropped


def test_no_footnote_debris(passages):
    assert not [p.id for p in passages if "()" in p.text]


def test_lettered_points_stay_in_their_paragraph(passages):
    by_id = {p.id: p for p in passages}
    art9_2 = by_id["CRD-Art9-2"].text   # withdrawal period starts ... (a) services (b) sales contracts
    assert "\n(a) in the case of service contracts" in art9_2
    assert "\n(b) in the case of sales contracts" in art9_2


def test_definitions_are_split_with_their_intro(passages):
    by_id = {p.id: p for p in passages}
    consumer = by_id["CRD-Art2-1"].text
    assert "the following definitions shall apply" in consumer
    assert "(1) ‘consumer’ means" in consumer
    off_premises = by_id["CRD-Art2-8"].text   # definition (8) keeps its points (a) to (d)
    assert "(8) ‘off-premises contract’" in off_premises
    assert all(f"\n({letter}) " in off_premises for letter in "abcd")
    assert "‘commercial transactions’" in by_id["LPD-Art2-1"].text


def test_passages_file_matches_chunker(passages):
    path = project_path(CONFIG["paths"]["passages"])
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines == [p.to_dict() for p in passages]


# ---------- a tiny hand-written directive ----------

MINI_DIRECTIVE = """<html><body>
<div class="eli-subdivision" id="rct_1"><p class="oj-normal">(1) Whereas this is a recital.</p></div>
<div class="eli-subdivision" id="art_1">
  <p class="oj-ti-art">Article 1</p>
  <div class="eli-title"><p class="oj-sti-art">Subject matter</p></div>
  <p class="oj-normal">This Directive lays down rules<a href="#ntr1">(<span class="oj-super oj-note-tag">1</span>)</a> on payment.</p>
</div>
<div class="eli-subdivision" id="art_2">
  <p class="oj-ti-art">Article 2</p>
  <div class="eli-title"><p class="oj-sti-art">Definitions</p></div>
  <p class="oj-normal">The following definitions shall apply:</p>
  <table><tr><td><p class="oj-normal">(1)</p></td><td><p class="oj-normal">'buyer' means a person;</p></td></tr></table>
  <table><tr><td><p class="oj-normal">(2)</p></td><td><p class="oj-normal">'seller' means a person who:</p>
    <table><tr><td><p class="oj-normal">(a)</p></td><td><p class="oj-normal">sells goods; or</p></td></tr></table>
    <table><tr><td><p class="oj-normal">(b)</p></td><td><p class="oj-normal">sells services.</p></td></tr></table>
  </td></tr></table>
</div>
<div class="eli-subdivision" id="art_3">
  <p class="oj-ti-art">Article 3</p>
  <div class="eli-title"><p class="oj-sti-art">Payment</p></div>
  <div id="003.001"><p class="oj-normal">1. The buyer shall pay:</p>
    <table><tr><td><p class="oj-normal">(a)</p></td><td><p class="oj-normal">within 30 days; and</p></td></tr></table>
    <table><tr><td><p class="oj-normal">(b)</p></td><td><p class="oj-normal">in full.</p></td></tr></table>
  </div>
  <div id="003.002"><p class="oj-normal">2. Interest is due after the deadline.</p></div>
</div>
<div class="eli-container" id="anx_I"><p class="oj-normal">ANNEX text</p></div>
<div class="eli-subdivision" id="fnp_1"><p class="oj-normal">Done at Brussels.</p></div>
</body></html>"""

MINI_SOURCE = {"id_prefix": "TST", "short_name": "Test Directive", "number": "2000/1/EU", "file": "mini.html"}


@pytest.fixture
def mini_passages(tmp_path):
    (tmp_path / "mini.html").write_text(MINI_DIRECTIVE, encoding="utf-8")
    return {p.id: p for p in DirectiveChunker(tmp_path, {"directives": [MINI_SOURCE]}).chunk_all()}


def test_mini_ids(mini_passages):
    assert list(mini_passages) == ["TST-Art1-1", "TST-Art2-1", "TST-Art2-2", "TST-Art3-1", "TST-Art3-2"]


def test_mini_article_without_paragraphs_and_footnote(mini_passages):
    assert mini_passages["TST-Art1-1"].text == (
        "Test Directive (2000/1/EU) - Article 1: Subject matter\nThis Directive lays down rules on payment.")


def test_mini_definitions(mini_passages):
    assert mini_passages["TST-Art2-2"].text == (
        "Test Directive (2000/1/EU) - Article 2: Definitions\n"
        "The following definitions shall apply:\n"
        "(2) 'seller' means a person who:\n(a) sells goods; or\n(b) sells services.")
    assert mini_passages["TST-Art2-2"].paragraph == 2


def test_mini_numbered_paragraph_keeps_points(mini_passages):
    p = mini_passages["TST-Art3-1"]
    assert p.text.endswith("1. The buyer shall pay:\n(a) within 30 days; and\n(b) in full.")
    assert (p.article, p.paragraph, p.title) == (3, 1, "Payment")


def test_mini_drops_recitals_annex_and_signature(mini_passages):
    text = " ".join(p.text for p in mini_passages.values())
    assert "Whereas" not in text and "ANNEX" not in text and "Done at" not in text


def test_write_jsonl(tmp_path, mini_passages):
    path = tmp_path / "out" / "passages.jsonl"
    write_jsonl(list(mini_passages.values()), path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == list(mini_passages)
    assert set(rows[0]) == {"id", "directive", "article", "paragraph", "title", "text", "n_chars"}
