"""Tests of the frozen Study 2 law corpus (src/build_study2_corpus.py, src/consolidated_xhtml_study2.py). No model."""

import hashlib
import json

import pytest

from src.build_study2_corpus import build, check_selection, main, read_selection, to_bytes
from src.config import load_config, project_path
from src.consolidated_xhtml_study2 import ConsolidatedChunker, lost_words
from src.retrieval.passage import load_passages

CONFIG = load_config()
SETTINGS = CONFIG["study2_corpus"]
CORPUS = project_path(SETTINGS["passages"])
FROZEN_SHA256 = "d30eea57b4773c24772a88d0f68cb61c0f3d6e29466a7ccf5dbbce0e574fd43b"   # built 27 Oct 2026
SOURCES = json.loads(project_path(SETTINGS["sources"]).read_text(encoding="utf-8"))["directives"]
# docs/STUDY2_CORPUS_RULE.md section 3: articles kept per law
KEPT_ARTICLES = {"GDPR": 37, "CRD": 14, "LPD": 3, "SGD": 12, "ECD": 5}


def manifest() -> dict:
    return json.loads(project_path(SETTINGS["manifest"]).read_text(encoding="utf-8"))


def test_corpus_file_has_the_frozen_hash():
    digest = hashlib.sha256(CORPUS.read_bytes()).hexdigest()
    assert digest == FROZEN_SHA256 == manifest()["passages_sha256"]
    assert b"\r\n" not in CORPUS.read_bytes()                                 # same bytes in every checkout


def test_manifest_counts_match_the_corpus_and_the_rule():
    info = manifest()
    passages = load_passages(CORPUS)
    assert info["n_passages"] == len(passages) == 289
    for prefix, counts in info["per_law"].items():
        assert counts["passages"] == sum(p.id.startswith(prefix + "-") for p in passages)
        assert counts["articles_kept"] == KEPT_ARTICLES[prefix]
    assert list(info["per_law"]) == [s["id_prefix"] for s in SOURCES]
    assert info["sources_sha256"] == hashlib.sha256(project_path(SETTINGS["sources"]).read_bytes()).hexdigest()
    assert len({p.id for p in passages}) == len(passages)


def test_rebuilding_gives_the_same_bytes():
    corpus, counts = build(CONFIG)              # also runs every check: hashes, titles, lost words, earlier corpora
    assert to_bytes(corpus) == CORPUS.read_bytes()
    assert counts == manifest()["per_law"]


def test_only_kept_articles_are_in_the_corpus():
    doc = project_path(SETTINGS["selection_doc"])
    ids = {p.id for p in load_passages(CORPUS)}
    for source in SOURCES:
        rows = read_selection(doc, source["selection_heading"])
        for r in rows:
            present = any(i.startswith(f"{source['id_prefix']}-Art{r['article']}-") for i in ids)
            assert present == (r["decision"] == "keep"), (source["id_prefix"], r["article"])
    assert not any(i.startswith(("GDPR-Art4-", "CRD-Art2-", "SGD-Art2-", "ECD-Art2-", "LPD-Art2-")) for i in ids)


def test_raw_files_match_sources_checksums():
    for s in SOURCES:
        path = project_path(s["raw_dir"]) / s["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == s["sha256"]


def test_check_selection_refuses_missing_article_and_wrong_title():
    crd = next(s for s in SOURCES if s["id_prefix"] == "CRD")
    passages = ConsolidatedChunker(project_path(crd["raw_dir"]), {"directives": [crd]}, 1500).chunk_directive(crd)
    rows = read_selection(project_path(SETTINGS["selection_doc"]), crd["selection_heading"])
    check_selection("CRD", rows, passages)
    with pytest.raises(ValueError, match="once each"):
        check_selection("CRD", rows[1:], passages)
    with pytest.raises(ValueError, match="title"):
        check_selection("CRD", [{**rows[0], "title": "Something else"}] + rows[1:], passages)


def test_main_refuses_to_overwrite():
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        main(CONFIG, [])


# ---------- the consolidated-text reader, on a tiny made-up document ----------

MINI = """<html><body>
<div class="eli-subdivision" id="art_6a">
 <p class="title-article-norm">Article 6a</p>
 <div class="eli-title" id="art_6a.tit_1"><p class="stitle-article-norm">Extra duties</p></div>
 <div class="norm"><span class="no-parag">1.  </span>
  <div class="norm inline-element">
   <p class="norm inline-element">The trader shall give:</p>
   <div class="grid-container grid-list"><div class="list grid-list-column-1"><span>(a) </span></div>
    <div class="grid-list-column-2"><p class="norm">his name;</p>
     <div class="grid-container grid-list"><div class="list grid-list-column-1"><span>(i) </span></div>
      <div class="grid-list-column-2"><p class="norm">the trading name;</p></div></div>
    </div></div>
   <div class="grid-container grid-list"><div class="list grid-list-column-1"><span>(b) </span></div>
    <div class="grid-list-column-2"><p class="norm">his address.</p></div></div>
  </div></div>
 <p class="norm">The second subparagraph stays with paragraph 1.</p>
 <p class="modref"><a href="http://publications.europa.eu/resource/celex/32019L2161">&#9660;M2</a></p>
 <div class="norm"><span class="no-parag">1a.  </span>
  <div class="norm inline-element">An inserted paragraph (<a href="#E0001"><span class="superscript">1</span></a>) with a note.</div></div>
</div>
<div class="eli-subdivision" id="art_7">
 <p class="title-article-norm">Article 7</p>
 <div class="eli-title" id="art_7.tit_1"><p class="stitle-article-norm">One block</p></div>
 <p class="norm">Member States shall ensure that the trader acts.</p>
</div>
</body></html>"""
MINI_SOURCE = {"id_prefix": "MINI", "short_name": "Mini Directive", "number": "1/1/EU", "file": "mini.html"}


@pytest.fixture
def mini(tmp_path):
    (tmp_path / "mini.html").write_text(MINI, encoding="utf-8")
    passages = ConsolidatedChunker(tmp_path, {"directives": [MINI_SOURCE]}, 1500).chunk_directive(MINI_SOURCE)
    return tmp_path, {p.id: p for p in passages}


def test_consolidated_paragraphs_points_and_lettered_numbers(mini):
    _, passages = mini
    assert list(passages) == ["MINI-Art6a-1", "MINI-Art6a-1a", "MINI-Art7-1"]
    assert passages["MINI-Art6a-1"].text.split("\n") == [
        "Mini Directive (1/1/EU) - Article 6a: Extra duties", "1. The trader shall give:", "(a) his name;",
        "(i) the trading name;", "(b) his address.", "The second subparagraph stays with paragraph 1."]
    assert (passages["MINI-Art6a-1"].article, passages["MINI-Art6a-1a"].paragraph) == ("6a", "1a")
    assert (passages["MINI-Art7-1"].article, passages["MINI-Art7-1"].paragraph) == (7, 1)   # plain numbers stay ints


def test_consolidated_drops_amendment_markers_and_footnote_links(mini):
    _, passages = mini
    assert passages["MINI-Art6a-1a"].text.endswith("\n1a. An inserted paragraph () with a note.")
    assert all("M2" not in p.text and "▼" not in p.text for p in passages.values())
    assert passages["MINI-Art7-1"].text.endswith("\nMember States shall ensure that the trader acts.")


def test_consolidated_lost_words_finds_a_missing_word(mini):
    folder, passages = mini
    assert lost_words(folder / "mini.html", list(passages.values())) == {}
    shortened = [p for p in passages.values() if p.id != "MINI-Art6a-1a"]
    assert lost_words(folder / "mini.html", shortened)["6a"] == ["1a", "An", "inserted", "note"]


def test_consolidated_reader_never_changes_the_raw_file(mini):
    folder, _ = mini
    assert (folder / "mini.html").read_text(encoding="utf-8") == MINI
