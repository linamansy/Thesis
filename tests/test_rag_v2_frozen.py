"""The frozen RAG v2 retrieval (src/freeze_rag_v2.py, 27 Oct 2026) must never change.

Checks its SHA-256 against the manifest and a hard-coded value, and that it was made with the decided setting
(sibling expansion OFF) on the frozen Study 2 corpus, for all 13 real cases and the 8 variants.
"""

import hashlib
import json

from src.config import load_config, project_path

CONFIG = load_config()
FROZEN_SHA256 = "b8e856464bcd14c50e79e286c26fc474e540a693b28365f6f64bf501f1dde8b7"   # frozen 27 Oct 2026
CORPUS_SHA256 = "d30eea57b4773c24772a88d0f68cb61c0f3d6e29466a7ccf5dbbce0e574fd43b"


def test_frozen_rag_v2_file_hash_matches_manifest_and_fixed_value():
    path = project_path(CONFIG["rag_v2"]["frozen_retrieval"])
    manifest = json.loads(project_path(CONFIG["rag_v2"]["frozen_manifest"]).read_text(encoding="utf-8"))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert sha == manifest["sha256"] == FROZEN_SHA256


def test_frozen_rag_v2_setting_corpus_and_cases():
    frozen = json.loads(project_path(CONFIG["rag_v2"]["frozen_retrieval"]).read_text(encoding="utf-8"))
    assert frozen["rag_v2"]["sibling_expansion"] is False is CONFIG["rag_v2"]["sibling_expansion"]
    assert frozen["reproducibility"]["passages_sha256"] == CORPUS_SHA256
    variants = [i["case_id"] for i in
                json.loads(project_path(CONFIG["rag_v2"]["test_set"]).read_text(encoding="utf-8"))["items"]]
    assert list(frozen["cases"]) == CONFIG["study2_cases"]["ids"] + variants and len(frozen["cases"]) == 21
    assert all(len(c["passages"]) == CONFIG["reranker"]["top_k"] for c in frozen["cases"].values())
