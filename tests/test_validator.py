"""Tests for src/validator.py, using small hand-written BPMN files."""

import pytest

from src.config import load_config, project_path
from src.validator import BPMNValidator

HEADER = '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="P">'
FOOTER = "</process></definitions>"


def write(tmp_path, body, name="model.bpmn"):
    path = tmp_path / name
    path.write_text(HEADER + body + FOOTER, encoding="utf-8")
    return path


VALID_BODY = (
    '<startEvent id="s"/><task id="t" name="Work"/><endEvent id="e"/>'
    '<sequenceFlow id="f1" sourceRef="s" targetRef="t"/>'
    '<sequenceFlow id="f2" sourceRef="t" targetRef="e"/>'
)


def test_valid_model(tmp_path):
    result = BPMNValidator().validate(write(tmp_path, VALID_BODY))
    assert result["parses"] and result["valid"]
    assert result["errors"] == []
    assert result["counts"] == {"start_events": 1, "end_events": 1, "tasks": 1,
                                "gateways": 0, "sequence_flows": 2}


def test_unparseable_file(tmp_path):
    path = tmp_path / "broken.bpmn"
    path.write_text("<definitions><process>", encoding="utf-8")
    result = BPMNValidator().validate(path)
    assert result["parses"] is False and result["valid"] is False


def test_missing_start_and_end(tmp_path):
    result = BPMNValidator().validate(write(tmp_path, '<task id="t" name="Work"/>'))
    assert not result["valid"]
    assert "no start event" in result["errors"]
    assert "no end event" in result["errors"]


def test_flow_to_missing_element(tmp_path):
    body = VALID_BODY + '<sequenceFlow id="f3" sourceRef="t" targetRef="ghost"/>'
    result = BPMNValidator().validate(write(tmp_path, body))
    assert not result["valid"]
    assert any("f3" in e and "ghost" in e for e in result["errors"])


def test_duplicate_ids(tmp_path):
    result = BPMNValidator().validate(write(tmp_path, VALID_BODY + '<task id="t" name="Again"/>'))
    assert any("duplicate ids" in e for e in result["errors"])


def test_wrong_root_element(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text("<html/>", encoding="utf-8")
    result = BPMNValidator().validate(path)
    assert not result["valid"]


@pytest.mark.parametrize("case_id", load_config()["cases"]["ids"])
def test_reference_models_are_valid(case_id):
    """Sanity check: the PMo reference models must pass the validator."""
    paths = load_config()["paths"]
    result = BPMNValidator().validate(project_path(paths["cases"]) / case_id / paths["case_reference_file"])
    assert result["valid"], result["errors"]
