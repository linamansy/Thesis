"""Tests for the GDPR corpus (src/chunk_gdpr.py): chapter filter and the committed GDPR files. No network."""

import hashlib
import json

import pytest

from src.chunk_gdpr import article_chapters, gdpr_chunker, restrict_to_chapters
from src.config import load_config, project_path
from src.retrieval.passage import Passage

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]

# Chapters as in the EUR-Lex XHTML: a chapter block contains sections and articles; "cpt_I.sct_1" is a section.
MINI_REGULATION = """<html><body>
<div class="eli-subdivision" id="rct_1"><p>(1) A recital.</p></div>
<div id="cpt_I"><p class="oj-ti-section-1">CHAPTER I</p>
  <div class="eli-subdivision" id="art_1"><p>Article 1</p></div>
  <div id="cpt_I.sct_1"><div class="eli-subdivision" id="art_2"><p>Article 2</p></div></div>
</div>
<div id="cpt_II"><p class="oj-ti-section-1">CHAPTER II</p>
  <div class="eli-subdivision" id="art_3"><p>Article 3</p></div>
</div>
</body></html>"""


def passage(article: int, paragraph: int = 1) -> Passage:
    return Passage(id=f"GDPR-Art{article}-{paragraph}", directive="2016/679", article=article, paragraph=paragraph,
                   title="t", text="x", n_chars=1)


def test_article_chapters_reads_chapter_blocks_and_sections(tmp_path):
    path = tmp_path / "mini.html"
    path.write_text(MINI_REGULATION, encoding="utf-8")
    assert article_chapters(path) == {1: "I", 2: "I", 3: "II"}   # article 2 inside a section still counts as I


def test_restrict_keeps_included_chapters_in_order():
    passages = [passage(1), passage(3), passage(2, 1), passage(2, 2)]
    kept = restrict_to_chapters(passages, {1: "I", 2: "I", 3: "II"}, ["I"])
    assert [p.id for p in kept] == ["GDPR-Art1-1", "GDPR-Art2-1", "GDPR-Art2-2"]


def test_restrict_refuses_article_without_chapter():
    with pytest.raises(ValueError, match="No chapter found for articles \\[7\\]"):
        restrict_to_chapters([passage(1), passage(7)], {1: "I"}, ["I"])


# ---------- the committed GDPR files ----------

def test_raw_file_matches_sources_checksum():
    source = json.loads(project_path(GDPR["knowledge_sources"]).read_text(encoding="utf-8"))["directives"][0]
    data = (project_path(GDPR["knowledge_raw"]) / source["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == source["sha256"]
    assert (source["id_prefix"], source["celex"]) == ("GDPR", "32016R0679")


def test_real_chapters_one_to_five_are_articles_1_to_50():
    source = json.loads(project_path(GDPR["knowledge_sources"]).read_text(encoding="utf-8"))["directives"][0]
    chapters = article_chapters(project_path(GDPR["knowledge_raw"]) / source["file"])
    assert len(chapters) == 99
    assert sorted(a for a, c in chapters.items() if c in GDPR["included_chapters"]) == list(range(1, 51))
    assert GDPR["included_chapters"] == ["I", "II", "III", "IV", "V"]


def load_lines(key: str) -> list[dict]:
    return [json.loads(line) for line in project_path(GDPR[key]).read_text(encoding="utf-8").splitlines()]


def test_restricted_file_is_the_full_file_without_chapters_6_to_11():
    full, restricted = load_lines("passages"), load_lines("passages_restricted")
    assert restricted == [p for p in full if p["article"] <= 50]
    assert (len(full), len(restricted)) == (437, 250)


def test_chunker_reproduces_committed_passages():
    passages = gdpr_chunker(CONFIG).chunk_all()
    assert [p.to_dict() for p in passages] == load_lines("passages")
    assert {p.article for p in passages} == set(range(1, 100))


def test_gdpr_paths_are_separate_from_study1():
    for key in ("knowledge_raw", "knowledge_sources", "passages", "passages_restricted", "dense_index_dir_restricted",
                "frozen_dev_hybrid_restricted", "frozen_dev_rerank_restricted", "silver_reference_dev"):
        assert "gdpr" in GDPR[key], key
    assert CONFIG["paths"]["passages"] == "data/knowledge/passages.jsonl"   # Study 1 default unchanged
