"""Tests for src/load_cases.py, using a tiny fake dataset in a temporary folder."""

from src.load_cases import CaseLoader, count_tasks_and_gateways

SMALL_BPMN = """<?xml version="1.0"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL">
  <process id="P">
    <startEvent id="S"/>
    <task id="T1" name="Receive order"/>
    <userTask id="T2" name="Check stock"/>
    <exclusiveGateway id="G1"/>
    <serviceTask id="T3" name="Send invoice"/>
    <parallelGateway id="G2"/>
    <endEvent id="E"/>
  </process>
</definitions>
"""


def make_config(tmp_path, case_ids):
    """Build a config dictionary that points to folders inside tmp_path."""
    return {
        "cases": {"ids": case_ids},
        "paths": {
            "pmo_descriptions": str(tmp_path / "raw" / "descriptions"),
            "pmo_bpmn": str(tmp_path / "raw" / "bpmn"),
            "cases": str(tmp_path / "cases"),
            "case_description_file": "description.txt",
            "case_reference_file": "reference.bpmn",
        },
    }


def write_raw_case(tmp_path, case_id, text):
    (tmp_path / "raw" / "descriptions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "bpmn").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw" / "descriptions" / f"{case_id}.txt").write_text(text, encoding="utf-8")
    (tmp_path / "raw" / "bpmn" / f"{case_id}.bpmn").write_text(SMALL_BPMN, encoding="utf-8")


def test_count_tasks_and_gateways(tmp_path):
    path = tmp_path / "model.bpmn"
    path.write_text(SMALL_BPMN, encoding="utf-8")
    assert count_tasks_and_gateways(path) == (3, 2)


def test_copy_and_summarise(tmp_path):
    write_raw_case(tmp_path, "07", "The customer places an order.")
    loader = CaseLoader(make_config(tmp_path, ["07"]))

    loader.copy_all()

    case_dir = tmp_path / "cases" / "07"
    assert (case_dir / "description.txt").read_text(encoding="utf-8") == "The customer places an order."
    assert (case_dir / "reference.bpmn").exists()
    assert loader.summarise_case("07") == {"case_id": "07", "words": 5, "tasks": 3, "gateways": 2}
