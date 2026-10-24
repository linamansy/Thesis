"""Tests for Study 2's additional EU laws (docs/C3_V2_DEVELOPMENT.md section 5):
src/legacy_html_study2_laws.py, src/chunk_study2_laws.py, src/freeze_retrieval_study2_laws.py and
src/build_silver_study2_laws_dev.py.

No network and no model download: the dense model (e5-small-v2) is the locally cached one also used by
tests/test_freeze_retrieval.py, the combined dense index is the committed one (only read), the cross-encoder is a
fake model and the silver annotator a MockLLM. Every file a test writes goes into pytest's tmp_path.
"""

import copy
import hashlib
import json
import sys

import pytest

from src.agents.silver_annotator import SilverAnnotator
from src.build_silver_reference import sha256
from src.build_silver_study2_laws_dev import CombinedDevSilverBuilder, decide, label_counts
from src.chunk_study2_laws import (check_selection, chunk_law, kept_passages, load_sources, lost_words,
                                   write_combined)
from src.chunk_study2_laws import main as chunk_main
from src.config import load_config, project_path
from src.freeze_retrieval_study2_laws import combined_view, freeze_combined
from src.freeze_retrieval_study2_laws import main as freeze_main
from src.legacy_html_study2_laws import convert, to_bytes
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.retrieval.chunker import DirectiveChunker
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.passage import Passage, load_passages

CONFIG = load_config()
LAWS = CONFIG["study2_laws"]
GDPR = CONFIG["study2_gdpr"]
RAW = project_path(LAWS["knowledge_raw"])

# A legacy EUR-Lex HTML text in miniature, with every pattern of the real ECD and OSH files.
MINI_LEGACY = """<html><body><div id="TexteOnly"><p><TXT_TE>
<p>Whereas a recital (1) is dropped;</p><p>HAVE ADOPTED THIS DIRECTIVE:</p>
<p>CHAPTER I</p><p>GENERAL PROVISIONS</p>
<p>Article 1</p><p>Definitions</p>
<p>For the purpose of this Directive:</p>
<p>(a) "provider": any person, see Directive 98/34/EC(3);</p>
<p>(b) "coordinated field": requirements in Article 1(2);</p>
<p>(i) The field concerns:</p><p>- taking up the activity,</p>
<p>(ii) The field does not cover goods.</p>
<p></p>
<p>Section 1: Information requirements</p>
<p>Article 2</p><p>Individual Directives -</p><p>General scope</p>
<p>1. The employer shall:</p>
<p>(a)</p><p>avoid risks;</p>
<p>(b) evaluate the risks which</p><p>cannot be avoided;</p>
<p>2. The employer shall ensure adequate controls.SECTION II</p>
<p>EMPLOYERS' OBLIGATIONS</p>
<p>Article 3</p><p>1. Each worker shall take care.</p>
<p>Article 4</p><p>This Directive is addressed to the Member States.</p>
<p>Done at Luxembourg, 12 June 1989.</p><p>For the Council</p>
<p>(1) OJ No C 141, 30. 5. 1988, p. 1.</p><p>ANNEX</p><p>- Work places</p>
</TXT_TE></p></div></body></html>"""

MINI_SOURCE = {"id_prefix": "MINI", "short_name": "Mini Directive", "number": "1/1/EEC", "file": "mini.html",
               "format": "legacy_html"}


@pytest.fixture
def mini(tmp_path):
    (tmp_path / "mini.html").write_text(MINI_LEGACY, encoding="utf-8")
    passages, conversion = chunk_law(MINI_SOURCE, tmp_path, CONFIG["chunking"]["max_passage_chars"])
    return {p.id: p for p in passages}, conversion, tmp_path


def body(passage: Passage) -> list[str]:
    return passage.text.split("\n")[1:]


# ---------- legacy HTML conversion (src/legacy_html_study2_laws.py) ----------

def test_legacy_articles_paragraphs_and_titles(mini):
    passages, conversion, _ = mini
    assert list(passages) == ["MINI-Art1-1", "MINI-Art2-1", "MINI-Art2-2", "MINI-Art3-1", "MINI-Art4-1"]
    assert passages["MINI-Art1-1"].title == "Definitions"
    assert passages["MINI-Art2-1"].title == "Individual Directives - General scope"   # title over two lines
    assert passages["MINI-Art3-1"].title == "" and passages["MINI-Art4-1"].title == ""
    assert conversion.untitled_articles == [3, 4]
    assert passages["MINI-Art4-1"].text == "Mini Directive (1/1/EEC) - Article 4: \n" \
                                           "This Directive is addressed to the Member States."


def test_legacy_points_and_joined_lines(mini):
    passages, _, _ = mini
    assert body(passages["MINI-Art2-1"]) == ["1. The employer shall:", "(a) avoid risks;",
                                             "(b) evaluate the risks which cannot be avoided;"]


def test_legacy_roman_sub_points_stay_with_their_letter(mini):
    passages, _, _ = mini
    assert body(passages["MINI-Art1-1"]) == [
        "For the purpose of this Directive:", '(a) "provider": any person, see Directive 98/34/EC;',
        '(b) "coordinated field": requirements in Article 1(2);', "(i) The field concerns:",
        "- taking up the activity,", "(ii) The field does not cover goods."]


def test_legacy_letter_i_after_h_is_a_point_without_roman_list(tmp_path):
    points = "".join(f"<p>({chr(c)}) item {chr(c)};</p>" for c in range(ord("a"), ord("j")))
    html = MINI_LEGACY.replace("<p>Article 3</p><p>1. Each worker shall take care.</p>",
                               f"<p>Article 3</p><p>Principles</p><p>1. Principles:</p>{points}")
    (tmp_path / "mini.html").write_text(html, encoding="utf-8")
    doc = convert(tmp_path / "mini.html").document
    labels = [td.text for td in doc.xpath('//div[@id="art_3"]//table/tr/td[1]')]
    assert labels == [f"({chr(c)})" for c in range(ord("a"), ord("j"))]


def test_legacy_drops_headings_footnotes_and_everything_after_done_at(mini):
    passages, conversion, tmp_path = mini
    text = "\n".join(p.text for p in passages.values())
    for gone in ("recital", "CHAPTER", "GENERAL PROVISIONS", "Section 1", "SECTION II", "EMPLOYERS'", "Done at",
                 "OJ No C 141", "Work places", "98/34/EC(3)"):
        assert gone not in text
    assert "adequate controls." in text and "Article 1(2)" in text                  # a reference is kept
    assert conversion.removed_footnotes == ["Art1: ...person, see Directive 98/34/EC(3)"]
    # CHAPTER I comes before "Article 1", so it is outside the articles (not counted as a dropped heading)
    assert conversion.dropped_headings == ["Section 1: Information requirements", "SECTION II",
                                           "EMPLOYERS' OBLIGATIONS"]
    assert lost_words(MINI_SOURCE, tmp_path, list(passages.values())) == {}


def test_lost_words_finds_a_missing_word(mini):
    passages, _, tmp_path = mini
    shortened = [p if p.id != "MINI-Art3-1" else Passage(**dict(p.to_dict(), text="1. Each worker shall."))
                 for p in passages.values()]
    assert lost_words(MINI_SOURCE, tmp_path, shortened) == {3: ["care", "take"]}


def test_legacy_conversion_never_changes_the_raw_file(mini):
    _, _, tmp_path = mini
    assert (tmp_path / "mini.html").read_text(encoding="utf-8") == MINI_LEGACY


def test_text_before_first_numbered_paragraph_is_refused(tmp_path):
    html = MINI_LEGACY.replace("<p>1. Each worker shall take care.</p>",
                               "<p>Some intro text.</p><p>1. Each worker shall take care.</p>")
    (tmp_path / "mini.html").write_text(html, encoding="utf-8")
    with pytest.raises(ValueError, match="Article 3: text before its first numbered paragraph"):
        convert(tmp_path / "mini.html")


# ---------- the committed raw files and passages ----------

SOURCES = load_sources(CONFIG)


def test_raw_files_match_sources_checksums():
    assert [(s["id_prefix"], s["celex"], s["format"]) for s in SOURCES["directives"]] == [
        ("ECD", "32000L0031", "legacy_html"), ("TPWC", "32019L1152", "xhtml"),
        ("CCD", "32023L2225", "xhtml"), ("OSH", "31989L0391", "legacy_html")]
    for source in SOURCES["directives"]:
        assert hashlib.sha256((RAW / source["file"]).read_bytes()).hexdigest() == source["sha256"]
        assert source["entry_into_force"]["source"] and source["application"]["date"]


@pytest.fixture(scope="module")
def real_passages():
    return {s["id_prefix"]: chunk_law(s, RAW, CONFIG["chunking"]["max_passage_chars"])[0]
            for s in SOURCES["directives"]}


def test_chunking_reproduces_committed_new_law_passages(real_passages):
    committed = load_passages(project_path(LAWS["passages_new_laws_all"]))
    assert [p for law in real_passages.values() for p in law] == committed
    assert {p.id.split("-")[0] for p in committed} == {"ECD", "TPWC", "CCD", "OSH"}
    assert len({p.id for p in committed}) == len(committed)


def test_no_word_lost_in_the_real_legacy_laws(real_passages):
    for source in SOURCES["directives"]:
        if source["format"] == "legacy_html":
            assert lost_words(source, RAW, real_passages[source["id_prefix"]]) == {}


def test_article_selection_names_every_article_once(real_passages):
    selection = json.loads(project_path(LAWS["article_selection"]).read_text(encoding="utf-8"))
    check_selection(selection, real_passages)
    kept = {law: sum(d["decision"] == "keep" for d in decisions) for law, decisions in selection["laws"].items()}
    assert kept == {"ECD": 6, "TPWC": 12, "CCD": 33, "OSH": 10}


def test_check_selection_refuses_missing_article_and_wrong_title(real_passages):
    selection = json.loads(project_path(LAWS["article_selection"]).read_text(encoding="utf-8"))
    broken = copy.deepcopy(selection)
    broken["laws"]["OSH"].pop()
    with pytest.raises(ValueError, match="OSH: article_selection.json must name articles"):
        check_selection(broken, real_passages)
    broken = copy.deepcopy(selection)
    broken["laws"]["ECD"][1]["title"] = "Something else"
    with pytest.raises(ValueError, match="ECD Art2: title"):
        check_selection(broken, real_passages)


def test_combined_corpus_is_gdpr_lines_then_kept_passages(real_passages):
    selection = json.loads(project_path(LAWS["article_selection"]).read_text(encoding="utf-8"))
    combined = project_path(LAWS["passages_combined"]).read_bytes().splitlines(keepends=True)
    gdpr = project_path(GDPR["passages_restricted"]).read_bytes().splitlines(keepends=True)
    assert combined[:len(gdpr)] == gdpr                                    # byte-identical, same order
    new = [Passage(**json.loads(line)) for line in combined[len(gdpr):]]
    assert new == kept_passages(selection, real_passages)
    assert len(gdpr) == 250 and len(new) == 252


def test_write_combined_uses_one_line_ending_and_refuses_id_clash(tmp_path):
    gdpr = tmp_path / "gdpr.jsonl"
    old = Passage(id="GDPR-Art1-1", directive="d", article=1, paragraph=1, title="t", text="x", n_chars=1)
    gdpr.write_bytes((json.dumps(old.to_dict()) + "\r\n").encode("utf-8"))
    new = Passage(id="ECD-Art5-1", directive="d", article=5, paragraph=1, title="t", text="ü", n_chars=1)
    write_combined(gdpr, [new], tmp_path / "out.jsonl")
    data = (tmp_path / "out.jsonl").read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n") == 2
    assert load_passages(tmp_path / "out.jsonl") == [old, new]
    with pytest.raises(ValueError, match="passage ids used twice"):
        write_combined(gdpr, [old], tmp_path / "out2.jsonl")


def test_chunk_main_refuses_to_overwrite():
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        chunk_main(CONFIG, [])


# ---------- retrieval on the combined corpus (src/freeze_retrieval_study2_laws.py) ----------

class ShortFirstModel:
    """Fake cross-encoder: the shorter the passage, the higher the score (same for every query)."""

    def predict(self, pairs, batch_size, show_progress_bar):
        return [-float(len(text)) for _, text in pairs]


def committed_frozen() -> dict:
    return json.loads(project_path(LAWS["frozen_dev_combined_rerank"]).read_text(encoding="utf-8"))


def test_combined_view_changes_only_the_corpus_and_index():
    view = combined_view(CONFIG)
    assert view["study2_gdpr"]["passages_restricted"] == LAWS["passages_combined"]
    assert view["study2_gdpr"]["dense_index_dir_restricted"] == LAWS["dense_index_dir_combined"]
    assert CONFIG["study2_gdpr"]["passages_restricted"] == "data/knowledge_gdpr/passages_ch1-5.jsonl"
    assert view["reranker"] == CONFIG["reranker"] and view["retrieval"] == CONFIG["retrieval"]


def test_freeze_with_fake_reranker_uses_combined_corpus_and_study2_method():
    fake = CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())
    frozen = freeze_combined(CONFIG, reranker=fake)
    saved = committed_frozen()
    assert frozen["reproducibility"] == saved["reproducibility"]       # same corpus, index and libraries
    assert list(frozen["cases"]) == GDPR["development_ids"]
    for case_id, case in frozen["cases"].items():
        # same hybrid top 20 as the committed file; only the (fake) reranker order differs
        assert {c["passage_id"] for c in case["candidates"]} == \
               {c["passage_id"] for c in saved["cases"][case_id]["candidates"]}
        assert case["reranker_queries"] == case["queries"][1:]
        assert all(-p["rerank_score"] == len(p["text"]) for p in case["passages"])
    assert frozen["study2"]["corpus"] == "combined"


def test_committed_frozen_file_is_consistent():
    saved = committed_frozen()
    repro = saved["reproducibility"]
    assert repro["passages_file"] == LAWS["passages_combined"] and repro["n_passages"] == 502
    assert repro["passages_sha256"] == hashlib.sha256(project_path(LAWS["passages_combined"]).read_bytes()).hexdigest()
    assert (saved["reranker"]["settings"]["queries"], saved["reranker"]["settings"]["aggregation"]) == ("sentences", "mean")
    assert saved["reranker"]["revision"] == CONFIG["reranker"]["revision"]
    assert saved["study2"]["article_selection_sha256"] == sha256(project_path(LAWS["article_selection"]))
    for case in saved["cases"].values():
        assert [p["passage_id"] for p in case["passages"]] == [c["passage_id"] for c in case["candidates"][:5]]


def test_freeze_main_refuses_to_overwrite():
    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        freeze_main(CONFIG, [])


# ---------- silver labels (src/build_silver_study2_laws_dev.py) ----------

def answer(label: str) -> str:
    steps = [{"label": "Inform customer", "actor": "Shop", "when": None, "already_in_description": False}]
    return json.dumps({"label": label, "facts": [], "reason": "r", "evidence": [],
                       "required_steps": steps if label == "applicable" else [], "possible_steps": []})


@pytest.fixture
def reuse_setup(tmp_path):
    """A frozen file per development case: rank 1 = the GDPR-only rerank rank-1 passage (already labelled),
    rank 2 = a new passage, rank 3 = the GDPR-only rank-2 passage with a changed text (must be labelled again)."""
    gdpr_rerank = json.loads(project_path(GDPR["frozen_dev_rerank_restricted"]).read_text(encoding="utf-8"))["cases"]
    cases = {}
    for case_id in GDPR["development_ids"]:
        old = sorted(gdpr_rerank[case_id]["passages"], key=lambda p: p["rank"])
        cases[case_id] = {"passages": [
            {"rank": 1, "passage_id": old[0]["passage_id"], "text": old[0]["text"]},
            {"rank": 2, "passage_id": "ECD-Art10-1", "text": "new law text"},
            {"rank": 3, "passage_id": old[1]["passage_id"], "text": old[1]["text"] + " changed"}]}
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    config = copy.deepcopy(CONFIG)
    config["study2_laws"]["frozen_dev_combined_rerank"] = str(frozen)
    config["study2_laws"]["silver_reference_dev_combined"] = str(tmp_path / "silver.json")
    return config, cases, tmp_path


def make_builder(config, tmp_path, answers) -> CombinedDevSilverBuilder:
    logger = RunLogger(tmp_path / "logs", LAWS["silver_log_condition"], "t1")
    return CombinedDevSilverBuilder(config, SilverAnnotator(MockLLM(answers), logger))


def test_silver_copies_existing_labels_and_labels_only_new_pairs(reuse_setup):
    config, cases, tmp_path = reuse_setup
    old = json.loads(project_path(GDPR["silver_reference_dev"]).read_text(encoding="utf-8"))["cases"]
    n_cases = len(cases)
    builder = make_builder(config, tmp_path, [answer("applicable"), answer("irrelevant")] * n_cases)
    data = builder.build()
    assert len(builder.annotator.llm.prompts_received) == 2 * n_cases       # ranks 2 and 3 of every case, never rank 1
    for case_id, case in data["cases"].items():
        first, second, third = case["passages"]
        expected = next(r for r in old[case_id]["passages"] if r["passage_id"] == first["passage_id"])
        assert {k: v for k, v in first.items() if k not in ("label_source", "copied_annotated_at")} == expected
        assert first["label_source"] == GDPR["silver_reference_dev"]
        assert first["copied_annotated_at"] == old[case_id]["annotated_at"]
        assert (second["label_source"], second["label"]) == ("new", "applicable")
        assert (third["label_source"], third["label"]) == ("new", "irrelevant")    # changed text: labelled again
        assert (case["n_new"], case["n_copied"]) == (2, 1)
        assert [s["passage_id"] for s in case["required_steps"]][-1] == "ECD-Art10-1"
    assert data["labels_reused_from"] == GDPR["silver_reference_dev"]
    assert data["frozen_retrieval_sha256"] == sha256(tmp_path / "frozen.json")


def test_silver_refuses_reuse_from_another_prompt(reuse_setup, tmp_path):
    config, _, _ = reuse_setup
    old = json.loads(project_path(GDPR["silver_reference_dev"]).read_text(encoding="utf-8"))
    old["prompt_sha256"] = "0" * 64
    (tmp_path / "old_silver.json").write_text(json.dumps(old), encoding="utf-8")
    config["study2_gdpr"]["silver_reference_dev"] = str(tmp_path / "old_silver.json")
    with pytest.raises(ValueError, match="another silver prompt"):
        make_builder(config, tmp_path, [answer("irrelevant")])


def test_decision_rule_needs_strictly_more_than_gdpr_only():
    def data(n_applicable):
        labels = ["applicable"] * n_applicable + ["irrelevant"] * (5 - n_applicable)
        return {"cases": {"01": {"passages": [{"passage_id": str(i), "label": l} for i, l in enumerate(labels)]}}}
    assert decide(data(4), 3)[0] == "combined"
    assert decide(data(3), 3) == ("gdpr_only", "combined has 3 silver-applicable passages, equal to 3 (not higher)")
    assert decide(data(2), 3)[0] == "gdpr_only" and "lower than" in decide(data(2), 3)[1]


def test_label_counts_put_failed_annotations_under_other():
    data = {"cases": {"01": {"passages": [{"label": "applicable"}, {"label": "annotation_failed"}]}}}
    assert label_counts(data)["01"] == {"applicable": 1, "indeterminate": 0, "not_applicable": 0, "irrelevant": 0,
                                        "other": 1}


def test_committed_silver_file_matches_its_inputs():
    path = project_path(LAWS["silver_reference_dev_combined"])
    data = json.loads(path.read_text(encoding="utf-8"))
    frozen = committed_frozen()
    assert data["frozen_retrieval_sha256"] == sha256(project_path(LAWS["frozen_dev_combined_rerank"]))
    assert data["prompt_sha256"] == sha256(project_path(CONFIG["paths"]["silver_prompt"]))
    assert data["annotator_model"] == CONFIG["silver"]["model"]
    assert sorted(data["cases"]) == GDPR["development_ids"]
    for case_id, case in data["cases"].items():
        assert [p["passage_id"] for p in case["passages"]] == [p["passage_id"] for p in frozen["cases"][case_id]["passages"]]
        assert all(p["label_source"] in ("new", GDPR["silver_reference_dev"]) for p in case["passages"])
