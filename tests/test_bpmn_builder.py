"""Tests for src/schemas.py and src/bpmn_builder.py."""

import json

import pytest
from lxml import etree
from pydantic import ValidationError

from src.bpmn_builder import BPMN_NS, BPMNDI_NS, DC_NS, BPMNBuilder, assign_columns
from src.config import load_config, project_path
from src.schemas import ProcessModel
from src.validator import BPMNValidator


def bpmn(tag):
    return f"{{{BPMN_NS}}}{tag}"


def load_sample() -> dict:
    path = project_path(load_config()["paths"]["mock_generator_response"])
    return json.loads(path.read_text(encoding="utf-8"))


def simple_process(**extra) -> ProcessModel:
    """start -> task_1 -> end, plus any extra fields."""
    data = {
        "start_events": [{"id": "s", "name": "Start"}],
        "end_events": [{"id": "e", "name": "End"}],
        "tasks": [{"id": "task_1", "name": "Do work"}],
        "sequence_flows": [{"id": "f1", "source": "s", "target": "task_1"},
                           {"id": "f2", "source": "task_1", "target": "e"}],
    }
    data.update(extra)
    return ProcessModel.model_validate(data)


# ---------- schema ----------

def test_sample_process_matches_schema():
    process = ProcessModel.model_validate(load_sample())
    assert len(process.tasks) == 5
    assert len(process.flow_nodes()) == 11


def test_schema_rejects_duplicate_ids():
    data = load_sample()
    data["tasks"][1]["id"] = "task_1"
    with pytest.raises(ValidationError, match="duplicate ids"):
        ProcessModel.model_validate(data)


def test_schema_rejects_lane_with_unknown_task():
    data = load_sample()
    data["lanes"][0]["task_ids"].append("task_99")
    with pytest.raises(ValidationError, match="unknown tasks"):
        ProcessModel.model_validate(data)


def test_schema_rejects_id_with_space():
    with pytest.raises(ValidationError):
        simple_process(tasks=[{"id": "task 1", "name": "Do work"}])


# ---------- builder ----------

def test_builder_writes_all_elements(tmp_path):
    process = ProcessModel.model_validate(load_sample())
    path = tmp_path / "out.bpmn"
    BPMNBuilder().write(process, path)

    root = etree.parse(str(path)).getroot()
    proc = root.find(bpmn("process"))
    assert len(proc.findall(bpmn("task"))) == 5
    assert len(proc.findall(bpmn("exclusiveGateway"))) == 2
    assert len(proc.findall(bpmn("parallelGateway"))) == 2
    assert len(proc.findall(bpmn("sequenceFlow"))) == 12
    assert len(proc.findall(f"{bpmn('laneSet')}/{bpmn('lane')}")) == 2
    names = {f.get("id"): f.get("name") for f in proc.findall(bpmn("sequenceFlow"))}
    assert names["flow_4"] == "yes" and names["flow_10"] == "no"
    # The task has its incoming and outgoing flows listed.
    task_1 = proc.find(f"{bpmn('task')}[@id='task_1']")
    assert [x.text for x in task_1.findall(bpmn("incoming"))] == ["flow_1"]


def test_builder_draws_every_element_and_flow(tmp_path):
    process = ProcessModel.model_validate(load_sample())
    root = BPMNBuilder().build(process).getroot()

    shapes = {s.get("bpmnElement") for s in root.iter(f"{{{BPMNDI_NS}}}BPMNShape")}
    edges = {e.get("bpmnElement") for e in root.iter(f"{{{BPMNDI_NS}}}BPMNEdge")}
    node_ids = {element.id for _, element in process.flow_nodes()}
    assert node_ids | {"Participant_1", "lane_sales", "lane_warehouse"} == shapes
    assert edges == {f.id for f in process.sequence_flows}


def test_layout_goes_left_to_right_and_respects_lanes():
    process = ProcessModel.model_validate(load_sample())
    root = BPMNBuilder().build(process).getroot()
    bounds = {s.get("bpmnElement"): s.find(f"{{{DC_NS}}}Bounds") for s in root.iter(f"{{{BPMNDI_NS}}}BPMNShape")}
    x = {k: float(b.get("x")) for k, b in bounds.items()}
    y = {k: float(b.get("y")) for k, b in bounds.items()}

    assert x["start_1"] < x["task_1"] < x["task_2"] < x["xor_1"] < x["end_1"]
    # task_2 (Warehouse) sits inside the Warehouse lane band.
    lane_top = y["lane_warehouse"]
    lane_bottom = lane_top + float(bounds["lane_warehouse"].get("height"))
    assert lane_top <= y["task_2"] < lane_bottom


def test_process_without_lanes_has_no_pool(tmp_path):
    root = BPMNBuilder().build(simple_process()).getroot()
    assert root.find(bpmn("collaboration")) is None
    plane = root.find(f"{{{BPMNDI_NS}}}BPMNDiagram/{{{BPMNDI_NS}}}BPMNPlane")
    assert plane.get("bpmnElement") == "Process_1"


def test_loop_is_laid_out_without_error(tmp_path):
    # task_1 -> xor -> task_1 (loop back) or -> end
    process = simple_process(
        exclusive_gateways=[{"id": "x", "name": "Done?"}],
        sequence_flows=[{"id": "f1", "source": "s", "target": "task_1"},
                        {"id": "f2", "source": "task_1", "target": "x"},
                        {"id": "f3", "source": "x", "target": "task_1", "condition": "no"},
                        {"id": "f4", "source": "x", "target": "e", "condition": "yes"}],
    )
    path = tmp_path / "loop.bpmn"
    BPMNBuilder().write(process, path)
    assert BPMNValidator().validate(path)["valid"]


def test_assign_columns_ignores_loops():
    edges = [("s", "a"), ("a", "b"), ("b", "a"), ("b", "e")]
    assert assign_columns(["s", "a", "b", "e"], ["s"], edges) == {"s": 0, "a": 1, "b": 2, "e": 3}


def test_built_sample_passes_validator(tmp_path):
    path = tmp_path / "out.bpmn"
    BPMNBuilder().write(ProcessModel.model_validate(load_sample()), path)
    result = BPMNValidator().validate(path)
    assert result["valid"], result["errors"]
    assert result["counts"]["tasks"] == 5
