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


def test_rag_v2_retrieval_test_set_is_consistent():
    # data/retrieval_study2_corpus/retrieval_test_set.json: 8 variants of development cases, one target each; the
    # target is a passage of the Study 2 corpus and equals variant.json; same description/reference rules as 01.1
    test_set = json.loads(project_path("data/retrieval_study2_corpus/retrieval_test_set.json").read_text(encoding="utf-8"))
    corpus = {json.loads(line)["id"] for line in project_path(CONFIG["study2_corpus"]["passages"])
              .read_text(encoding="utf-8").splitlines() if line.strip()}
    development = {case for case, label in CONFIG["study2_cases"]["labels"].items() if label == "development"}
    ids = [item["case_id"] for item in test_set["items"]]
    assert ids == ["01.1", "01.2", "06.1", "11.1", "13.1", "17.1", "19.1", "45.1"]
    for item in test_set["items"]:
        case_id = item["case_id"]
        meta = json.loads((CASES / case_id / "variant.json").read_text(encoding="utf-8"))
        assert meta["base_case"] in development and item["targets"] == [meta["target_passage_id"]]
        assert meta["target_passage_id"] in corpus
        base = (CASES / meta["base_case"] / "description.txt").read_text(encoding="utf-8")
        assert (CASES / case_id / "description.txt").read_text(encoding="utf-8") == base + "\n" + meta["added_text"]
        assert not any(word in meta["added_text"].lower().split() for word in ("must", "shall", "should"))
        result = BPMNValidator().validate(CASES / case_id / "reference.bpmn")
        base_result = BPMNValidator().validate(CASES / meta["base_case"] / "reference.bpmn")
        assert result["valid"] and result["counts"]["tasks"] == base_result["counts"]["tasks"] + 1
        text = (CASES / case_id / "reference.bpmn").read_text(encoding="utf-8")
        assert f'name="{meta["expected_step"]}"' in text and "PROVISIONAL" in text


def test_rag_v2_held_out_set_is_consistent_and_not_used_for_selection():
    # data/retrieval_study2_corpus/held_out_test_set.json (docs/RAG_V2_CRITERIA.md 7.8): 5 variants of NON-development
    # cases, accepted targets per variant (first = variant.json target); never in the selection test set, and no
    # code or config refers to the file (it is measured only once, after the freeze)
    held_out = json.loads(project_path("data/retrieval_study2_corpus/held_out_test_set.json").read_text(encoding="utf-8"))
    test_set = json.loads(project_path(CONFIG["rag_v2"]["test_set"]).read_text(encoding="utf-8"))
    corpus = {json.loads(line)["id"] for line in project_path(CONFIG["study2_corpus"]["passages"])
              .read_text(encoding="utf-8").splitlines() if line.strip()}
    non_development = {case for case, label in CONFIG["study2_cases"]["labels"].items() if label == "non-development"}
    ids = [item["case_id"] for item in held_out["items"]]
    assert ids == ["03.1", "05.1", "21.1", "37.1", "46.1"]
    assert not set(ids) & {item["case_id"] for item in test_set["items"]}
    for item in held_out["items"]:
        meta = json.loads((CASES / item["case_id"] / "variant.json").read_text(encoding="utf-8"))
        assert meta["base_case"] in non_development and meta["author"] == "drafted by Claude, approved by Lina"
        assert item["targets"] == meta["accepted_target_ids"] and item["targets"][0] == meta["target_passage_id"]
        assert set(item["targets"]) <= corpus
        base = (CASES / meta["base_case"] / "description.txt").read_text(encoding="utf-8")
        assert (CASES / item["case_id"] / "description.txt").read_text(encoding="utf-8") == base + "\n" + meta["added_text"]
        assert not any(word in meta["added_text"].lower().split() for word in ("must", "shall", "should"))
        result = BPMNValidator().validate(CASES / item["case_id"] / "reference.bpmn")
        base_result = BPMNValidator().validate(CASES / meta["base_case"] / "reference.bpmn")
        assert result["valid"] and result["counts"]["tasks"] == base_result["counts"]["tasks"] + 1
        text = (CASES / item["case_id"] / "reference.bpmn").read_text(encoding="utf-8")
        assert f'name="{meta["expected_step"]}"' in text and "PROVISIONAL" in text
    for path in [project_path("config.yaml"), *project_path("src").rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        assert "held_out_test_set" not in text and "held_out_v3_test_set" not in text


def test_rag_v3_held_out_set_is_consistent_and_not_used_for_selection():
    # data/retrieval_study2_corpus/held_out_v3_test_set.json (docs/RAG_V2_CRITERIA.md 8.5): 5 NEW variants of
    # non-development cases, separate from the old held-out set and the selection test set; no target was used
    # before; no code or config refers to the file (checked in the test above)
    held_out = json.loads(project_path("data/retrieval_study2_corpus/held_out_v3_test_set.json").read_text(encoding="utf-8"))
    old = json.loads(project_path("data/retrieval_study2_corpus/held_out_test_set.json").read_text(encoding="utf-8"))
    test_set = json.loads(project_path(CONFIG["rag_v2"]["test_set"]).read_text(encoding="utf-8"))
    corpus = {json.loads(line)["id"] for line in project_path(CONFIG["study2_corpus"]["passages"])
              .read_text(encoding="utf-8").splitlines() if line.strip()}
    non_development = {case for case, label in CONFIG["study2_cases"]["labels"].items() if label == "non-development"}
    ids = [item["case_id"] for item in held_out["items"]]
    assert ids == ["03.2", "05.2", "10.1", "21.2", "46.2"]
    assert not set(ids) & {item["case_id"] for item in test_set["items"] + old["items"]}
    used_before = {target for item in test_set["items"] + old["items"] for target in item["targets"]}
    used_before |= {"GDPR-Art13-1", "GDPR-Art17-1", "CRD-Art13-1", "CRD-Art14-1", "SGD-Art14-1",
                    "ECD-Art10-1", "ECD-Art11-1"}
    first_targets = [item["targets"][0] for item in held_out["items"]]
    assert len(set(first_targets)) == 5 and len({target.split("-")[0] for target in first_targets}) >= 3
    for item in held_out["items"]:
        meta = json.loads((CASES / item["case_id"] / "variant.json").read_text(encoding="utf-8"))
        assert meta["base_case"] in non_development and meta["author"] == "drafted by Claude, approved by Lina"
        assert item["targets"] == meta["accepted_target_ids"] and item["targets"][0] == meta["target_passage_id"]
        assert set(item["targets"]) <= corpus and not set(item["targets"]) & used_before
        base = (CASES / meta["base_case"] / "description.txt").read_text(encoding="utf-8")
        assert (CASES / item["case_id"] / "description.txt").read_text(encoding="utf-8") == base + "\n" + meta["added_text"]
        assert not any(word in meta["added_text"].lower().split() for word in ("must", "shall", "should"))
        result = BPMNValidator().validate(CASES / item["case_id"] / "reference.bpmn")
        base_result = BPMNValidator().validate(CASES / meta["base_case"] / "reference.bpmn")
        assert result["valid"] and result["counts"]["tasks"] == base_result["counts"]["tasks"] + 1
        text = (CASES / item["case_id"] / "reference.bpmn").read_text(encoding="utf-8")
        assert f'name="{meta["expected_step"]}"' in text and "PROVISIONAL" in text
