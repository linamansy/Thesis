"""Tests for DIRescue: only a broken diagram (bpmndi) section is ever removed, nothing else is repaired.

The test models look like qwen3's output in the smoke run: prefixed bpmn: tags, a process part and
a bpmndi diagram section.
"""

from src.di_rescue import DIRescue
from src.validator import BPMNValidator

BPMN_NS = 'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"'
DI_NS = ('xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
         'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"')

PROCESS = """
  <bpmn:process id="P">
    <bpmn:startEvent id="s"/>
    <bpmn:task id="t1" name="Check stock"/>
    <bpmn:task id="t2" name="Ship goods"/>
    <bpmn:endEvent id="e"/>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t1"/>
    <bpmn:sequenceFlow id="f2" sourceRef="t1" targetRef="t2"/>
    <bpmn:sequenceFlow id="f3" sourceRef="t2" targetRef="e"/>
  </bpmn:process>"""

DIAGRAM = """
  <bpmndi:BPMNDiagram id="D1">
    <bpmndi:BPMNPlane id="PL1" bpmnElement="P">
      <bpmndi:BPMNShape id="t1_di" bpmnElement="t1"><dc:Bounds x="100" y="80" width="100" height="80"/></bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>"""


def model(namespaces: str, process: str = PROCESS, diagram: str = DIAGRAM) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<bpmn:definitions {namespaces} targetNamespace="x">'
            f"{process}{diagram}\n</bpmn:definitions>\n")


TYPO_PROCESS = PROCESS.replace('<bpmn:sequenceFlow id="f2"', '<b3pmn:sequenceFlow id="f2"')

VALID = model(f"{BPMN_NS} {DI_NS}")                           # everything declared
MISSING_DI_NAMESPACE = model(BPMN_NS)                         # as in smoke_bpmngen C3: bpmndi never declared
B3PMN_TYPO = model(f"{BPMN_NS} {DI_NS}", TYPO_PROCESS)        # typo in the process part only
B3PMN_TYPO_AND_MISSING_DI = model(BPMN_NS, TYPO_PROCESS)      # as in smoke_bpmngen C2: both problems


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_bpmndi_namespace_is_rescued(tmp_path):
    path = write(tmp_path, "generated.bpmn", MISSING_DI_NAMESPACE)
    assert BPMNValidator().validate(path)["valid"] is False   # strict verdict unchanged: invalid

    copy = DIRescue().rescue(path, tmp_path)

    assert copy is not None and copy != path
    stripped = copy.read_text(encoding="utf-8")
    assert "bpmndi:" not in stripped and "dc:Bounds" not in stripped
    assert stripped == MISSING_DI_NAMESPACE.replace(DIAGRAM.strip(), "")   # only the diagram section was removed
    assert BPMNValidator().validate(copy)["counts"]["tasks"] == 2
    assert path.read_text(encoding="utf-8") == MISSING_DI_NAMESPACE   # the generated file is never changed


def test_b3pmn_typo_is_not_rescued(tmp_path):
    for name, text in [("typo.bpmn", B3PMN_TYPO), ("typo_and_di.bpmn", B3PMN_TYPO_AND_MISSING_DI)]:
        path = write(tmp_path, name, text)
        assert BPMNValidator().validate(path)["valid"] is False
        assert DIRescue().rescue(path, tmp_path) is None, name   # the process part itself is broken


def test_valid_file_is_unchanged(tmp_path):
    path = write(tmp_path, "generated.bpmn", VALID)
    assert BPMNValidator().validate(path)["valid"] is True
    assert DIRescue().rescue(path, tmp_path) is None              # nothing to rescue
    assert not (tmp_path / "generated_di_stripped.bpmn").exists()
    assert path.read_text(encoding="utf-8") == VALID


def test_structural_error_with_a_fine_diagram_is_not_rescued(tmp_path):
    broken_flow = PROCESS.replace('targetRef="t2"/>', 'targetRef="nowhere"/>')
    path = write(tmp_path, "generated.bpmn", model(f"{BPMN_NS} {DI_NS}", broken_flow))
    assert DIRescue().rescue(path, tmp_path) is None


def test_invalid_file_without_diagram_section_is_not_rescued(tmp_path):
    path = write(tmp_path, "generated.bpmn", model(BPMN_NS, PROCESS.replace("<bpmn:endEvent", "<bpmn2:endEvent"), ""))
    assert DIRescue().rescue(path, tmp_path) is None


def test_strip_diagram_removes_only_diagram_sections():
    assert DIRescue.strip_diagram(VALID) == VALID.replace(DIAGRAM.strip(), "")
    assert DIRescue.strip_diagram(model(BPMN_NS, diagram="")) is None
    self_closing = model(BPMN_NS, diagram='\n  <bpmndi:BPMNDiagram id="D1"/>')
    assert "BPMNDiagram" not in DIRescue.strip_diagram(self_closing)
