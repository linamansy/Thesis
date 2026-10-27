"""Tests for RAG v3, EXPLORATORY (docs/RAG_V2_CRITERIA.md section 8): options E, F, G and the passage enrichment.

No real model is called: the enricher gets a MockLLM, bge-m3 and the rerankers are fakes. The e5 embedding model is
local (option F uses it, as the current freeze). Every index and enrichment file is written in a temporary folder.
"""

import copy
import hashlib
import json
import re

import numpy as np
import pytest

from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.rag_v3 import (RagV3Retriever, bge_reranker, check_ollama_idle, index_text, load_enrichment,
                        make_enricher, run_enrichment)
from src.retrieval.bge_dense_retriever import BgeDenseRetriever
from src.retrieval.cross_encoder_reranker import CrossEncoderReranker
from src.retrieval.passage import load_passages
from src.retrieval.passage_enricher import PassageEnricher

CONFIG = load_config()
V3 = CONFIG["rag_v2"]["v3"]
CORPUS = load_passages(project_path(CONFIG["study2_corpus"]["passages"]))
SHOP = ("A customer orders goods in the online shop. The shop sends an order confirmation by email. "
        "The customer pays the invoice within 30 days.")
ANSWER = "  Applies when a shop takes an order from a customer online.\n"


class ShortFirstModel:
    """Fake cross-encoder: the shorter the passage, the higher the score (same for every query)."""

    def predict(self, pairs, batch_size, show_progress_bar):
        return [-float(len(text)) for _, text in pairs]


class FakeEmbedder:
    """Fake bge-m3: a normalised vector from the hash of each text (no model is loaded)."""

    max_seq_length = 512

    def __init__(self):
        self.encoded = []

    def encode(self, texts, normalize_embeddings, convert_to_numpy):
        self.encoded.extend(texts)
        vectors = np.array([np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8)[:16] + 1.0
                            for t in texts], dtype="float32")
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def fake_reranker():
    return CrossEncoderReranker.from_config(CONFIG, model=ShortFirstModel())


def enricher(tmp_path, answer=ANSWER):
    template = project_path(V3["enrichment_prompt"]).read_text(encoding="utf-8")
    return PassageEnricher(MockLLM([answer]), template, tmp_path / "enrichment",
                           lambda: RunLogger(tmp_path / "logs", V3["enrichment_log_condition"], "test"))


def tmp_config(tmp_path):
    config = copy.deepcopy(CONFIG)
    config["rag_v2"]["v3"]["enrichment_file"] = str(tmp_path / "enrichment.jsonl")
    config["rag_v2"]["v3"]["enrichment_manifest"] = str(tmp_path / "enrichment_manifest.json")
    return config


# ---------- the fixed settings equal the criteria doc ----------

def doc_section(start, end):
    doc = project_path("docs/RAG_V2_CRITERIA.md").read_text(encoding="utf-8")
    return doc[doc.index(start):doc.index(end)]


def test_enrichment_prompt_is_the_doc_block_byte_for_byte():
    block = re.search(r"```text\n(.*?)```", doc_section("### 8.3", "### 8.4"), re.S).group(1)
    assert project_path(V3["enrichment_prompt"]).read_text(encoding="utf-8") == block
    assert block.startswith("/no_think\n") and block.count("{passage_text}") == 1


def test_options_models_and_hashes_equal_section_8_2():
    assert V3["options"] == {"E": {"bge": True, "enrich": False}, "F": {"bge": False, "enrich": True},
                             "G": {"bge": True, "enrich": True}}
    assert V3["simplicity_order"] == ["E", "F", "G"] and V3["baseline_m1"] == 2
    section = doc_section("### 8.2", "### 8.3")
    assert f"`BAAI/bge-m3` = `{V3['dense_revision']}`" in section
    assert f"`BAAI/bge-reranker-v2-m3` = `{V3['reranker_revision']}`" in section
    assert V3["dense_model"] == "BAAI/bge-m3" and V3["reranker_model"] == "BAAI/bge-reranker-v2-m3"
    assert V3["device"] == "cpu" and "CPU in fp32" in section and V3["dense_max_length"] == 8192
    assert CONFIG["reranker"]["candidates"] == 20 and CONFIG["reranker"]["top_k"] == 5
    assert CONFIG["rag_v2"]["sibling_expansion"] is False
    assert len(CORPUS) == 289


def test_v3_files_are_new_and_labelled_exploratory():
    for key in ("frozen_retrieval", "frozen_manifest", "enrichment_file", "enrichment_manifest", "evaluation_dir"):
        assert "exploratory" in V3[key]
    assert V3["frozen_retrieval"] not in (CONFIG["rag_v2"]["frozen_retrieval"],
                                          CONFIG["rag_v2"]["extra_round"]["frozen_retrieval"])
    assert CONFIG["rag_v2"]["dense_index_dir"] not in V3["dense_index_dirs"].values()


def test_make_enricher_refuses_the_mock_provider():
    with pytest.raises(ValueError, match="ollama"):
        make_enricher(CONFIG)   # tests run with THESIS_FORCE_MOCK


# ---------- PassageEnricher ----------

def test_enricher_puts_the_passage_text_verbatim_strips_saves_and_reuses(tmp_path):
    e = enricher(tmp_path)
    passage = CORPUS[0]
    record = e.enrich(passage)
    sent = e.llm.prompts_received[0]
    assert sent == project_path(V3["enrichment_prompt"]).read_text(encoding="utf-8").replace("{passage_text}",
                                                                                              passage.text)
    assert record["enrichment"] == ANSWER.strip() and record["raw_output"] == ANSWER
    saved = json.loads((tmp_path / "enrichment" / f"{passage.id}.json").read_text(encoding="utf-8"))
    assert saved == record and "EXPLORATORY" in saved["label"]
    log = [json.loads(line) for line in e.logger.log_path.read_text(encoding="utf-8").splitlines()]
    assert len(log) == 1 and log[0]["component"] == "PassageEnricher" and log[0]["raw_output"] == ANSWER

    again = enricher(tmp_path, answer="other")              # a resumed run: reuses the file, no LLM call
    assert again.enrich(passage) == record and again.llm.prompts_received == []
    changed = type(passage)(**dict(passage.to_dict(), text=passage.text + " Changed."))
    with pytest.raises(RuntimeError, match="changed"):
        again.enrich(changed)


def test_empty_answer_gives_no_enrichment_and_index_text_is_the_passage(tmp_path):
    record = enricher(tmp_path, answer="  \n").enrich(CORPUS[1])
    assert record["enrichment"] == ""
    assert index_text(CORPUS[1], {CORPUS[1].id: ""}) == CORPUS[1].text
    assert index_text(CORPUS[1], {CORPUS[1].id: "x y"}) == CORPUS[1].text + "\nx y"


def test_run_enrichment_writes_file_and_manifest_once_and_load_checks_the_hash(tmp_path):
    config = tmp_config(tmp_path)
    manifest = run_enrichment(config, enricher(tmp_path))
    assert manifest["n_passages"] == 289 and manifest["n_empty"] == 0 and "EXPLORATORY" in manifest["label"]
    loaded = load_enrichment(config)
    assert list(loaded) == [p.id for p in CORPUS] and set(loaded.values()) == {ANSWER.strip()}
    with pytest.raises(FileExistsError):
        run_enrichment(config, enricher(tmp_path))
    path = tmp_path / "enrichment.jsonl"
    path.write_bytes(path.read_bytes().replace(b"online", b"offline", 1))
    with pytest.raises(RuntimeError, match="changed"):
        load_enrichment(config)


# ---------- options E, F, G ----------

def test_bge_reranker_changes_only_model_and_revision():
    r = bge_reranker(CONFIG, model=ShortFirstModel())
    assert (r.model_name, r.revision) == (V3["reranker_model"], V3["reranker_revision"])
    base = CONFIG["reranker"]
    assert (r.max_length, r.batch_size, r.aggregation, r.queries) == (base["max_length"], base["batch_size"],
                                                                       base["aggregation"], base["queries"])


def test_option_e_uses_bge_without_prefixes_and_returns_the_corpus_text(tmp_path):
    fake = FakeEmbedder()
    e = RagV3Retriever(CONFIG, "E", reranker=fake_reranker(), dense_model=fake, dense_index_dir=tmp_path / "E")
    assert isinstance(e.dense, BgeDenseRetriever) and e.dense.model.max_seq_length == 8192
    assert fake.encoded[:len(CORPUS)] == [p.text for p in CORPUS]          # no "passage: " prefix
    assert V3["dense_revision"] in e.describe()["dense_revision"]
    case = e.retrieve(SHOP)
    assert fake.encoded[len(CORPUS)] == SHOP                               # no "query: " prefix
    assert len(case["candidates"]) == 20 and len(case["passages"]) == 5 and case["option"] == "E"
    corpus = {p.id: p for p in CORPUS}
    assert all(p["text"] == corpus[p["passage_id"]].text for p in case["passages"])


def test_option_f_indexes_enriched_text_but_returns_the_corpus_text(tmp_path):
    enrichment = {p.id: f"Business sentence for {p.id}." for p in CORPUS}
    f = RagV3Retriever(CONFIG, "F", reranker=fake_reranker(), enrichment=enrichment, dense_index_dir=tmp_path / "F")
    corpus = {p.id: p for p in CORPUS}
    assert all(p.text == corpus[p.id].text + "\n" + enrichment[p.id] for p in f.dense.passages)
    assert all(p.text == corpus[p.id].text + "\n" + enrichment[p.id] for p in f.sparse.passages)
    assert f.dense.model_name == CONFIG["retrieval"]["dense_model"]       # e5, as the current freeze
    case = f.retrieve(SHOP)
    assert len(case["candidates"]) == 20 and len(case["passages"]) == 5
    assert all(p["text"] == corpus[p["passage_id"]].text for p in case["passages"])


def test_option_g_combines_bge_and_enrichment(tmp_path):
    enrichment = {p.id: "Sell goods." for p in CORPUS}
    g = RagV3Retriever(CONFIG, "G", reranker=fake_reranker(), enrichment=enrichment, dense_model=FakeEmbedder(),
                       dense_index_dir=tmp_path / "G")
    assert isinstance(g.dense, BgeDenseRetriever) and g.dense.passages[0].text.endswith("\nSell goods.")


def test_check_ollama_idle_stops_when_a_model_is_loaded():
    class Client:
        def __init__(self, models):
            self.models = models

        def get(self, url):
            assert url.endswith("/api/ps")
            return type("R", (), {"json": lambda s: {"models": self.models}})()

    check_ollama_idle(CONFIG, Client([]))
    with pytest.raises(RuntimeError, match="loaded"):
        check_ollama_idle(CONFIG, Client([{"name": "qwen3:8b"}]))
