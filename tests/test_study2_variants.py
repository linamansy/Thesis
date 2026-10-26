"""Study 2 variant cases: the committed files of variant 01.1 are consistent (no model, no retrieval run)."""

import json

from src.config import load_config, project_path
from src.validator import BPMNValidator

CONFIG = load_config()
GDPR = CONFIG["study2_gdpr"]
CASES = project_path(CONFIG["paths"]["cases"])


def test_variant_description_is_base_plus_added_text():
    for case_id in GDPR["variant_ids"]:
        meta = json.loads((CASES / case_id / "variant.json").read_text(encoding="utf-8"))
        base = (CASES / meta["base_case"] / "description.txt").read_text(encoding="utf-8")
        assert (CASES / case_id / "description.txt").read_text(encoding="utf-8") == base + "\n" + meta["added_text"]
        assert meta["author"] == "Lina" and meta["target_passage_id"]


def test_variant_reference_is_valid_and_has_the_expected_step():
    for case_id in GDPR["variant_ids"]:
        meta = json.loads((CASES / case_id / "variant.json").read_text(encoding="utf-8"))
        reference = CASES / case_id / "reference.bpmn"
        result = BPMNValidator().validate(reference)
        base = BPMNValidator().validate(CASES / meta["base_case"] / "reference.bpmn")
        assert result["valid"] and result["counts"]["tasks"] == base["counts"]["tasks"] + 1
        text = reference.read_text(encoding="utf-8")
        assert f'name="{meta["expected_step"]}"' in text and "PROVISIONAL" in text


def test_frozen_variant_file_has_every_variant_with_top_5():
    frozen = json.loads(project_path(GDPR["frozen_variants_rerank"]).read_text(encoding="utf-8"))
    assert list(frozen["cases"]) == GDPR["variant_ids"]
    assert frozen["study2"]["development_top5_reproduced"] == GDPR["development_ids"]
    for case in frozen["cases"].values():
        assert [p["rank"] for p in case["passages"]] == [1, 2, 3, 4, 5]
