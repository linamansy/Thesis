"""Tests for bpmngen_harness/repairs.js (fix D2): what BPMNGen's cleanup changed, counted from outside.

repairs.js is plain JavaScript; these tests run it with Node (skipped when Node is not installed).
"""

import json
import shutil
import subprocess

import pytest

from src.config import PROJECT_ROOT

REPAIRS_JS = (PROJECT_ROOT / "bpmngen_harness" / "repairs.js").as_posix()
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")

RAW = """```xml
<bpmn:definitions><bpmn:process id="p">
<bpmn:startEvent id="s"/><bpmn:userTask id="t1" name="Check order"/><bpmn:task id="t2" name="Ship"/>
<bpmn:boundaryEvent id="b1" attachedToRef="t1"/>
<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t1"/>
<bpmn:endEvent id="e"/></bpmn:process></bpmn:definitions>
```"""
FINAL = """<bpmn:definitions><bpmn:process id="p">
<bpmn:startEvent id="s"/><bpmn:userTask id="t1" name="Check order"/><bpmn:task id="t2" name="Ship"/>
<bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t1"/>
<bpmn:sequenceFlow id="auto_flow_1" sourceRef="t1" targetRef="t2"/>
<bpmn:sequenceFlow id="auto_flow_2" sourceRef="t2" targetRef="e"/>
<bpmn:endEvent id="e"/></bpmn:process></bpmn:definitions>"""


def repairs(raw, cleaned, final):
    script = (f"const r = require({json.dumps(REPAIRS_JS)}); "
              f"console.log(JSON.stringify(r.countRepairs({json.dumps(raw)}, {json.dumps(cleaned)}, {json.dumps(final)})));")
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(result.stdout)


def test_counts_elements_before_and_after_the_cleanup():
    r = repairs(RAW, FINAL, FINAL)
    assert r["elements_raw"]["task"] == 2 and r["elements_raw"]["sequenceFlow"] == 1
    assert r["elements_final"]["sequenceFlow"] == 3
    assert r["boundary_events_in_raw"] == 1 and r["boundary_events_in_final"] == 0   # dropped by the cleanup
    assert r["changed_element_types"] == ["boundaryEvent", "sequenceFlow"]
    assert r["n_element_changes"] == 3                                                # 1 boundary event + 2 flows
    assert r["raw_equals_cleaned"] is False


def test_unchanged_model_has_no_repairs():
    r = repairs(FINAL, FINAL, FINAL)
    assert r["changed_element_types"] == [] and r["n_element_changes"] == 0 and r["raw_equals_cleaned"] is True


def test_closing_tags_and_other_names_are_not_counted():
    r = repairs("<task id='a'></task><taskList/><bpmn:laneSet><bpmn:lane id='l'/></bpmn:laneSet>", "", "")
    assert r["elements_raw"]["task"] == 1          # only the opening tag of <task>; "taskList" does not end in task
    assert r["elements_raw"]["lane"] == 1          # laneSet is not a lane


def test_cut_off_answer_counts_only_the_raw_side():
    r = repairs(RAW, None, None)
    assert r["boundary_events_in_raw"] == 1
    assert r["elements_final"] is None and r["changed_element_types"] is None and r["raw_equals_cleaned"] is None


def test_harness_writes_the_counts_into_meta():
    harness = (PROJECT_ROOT / "bpmngen_harness" / "run_bpmngen.ts").read_text(encoding="utf-8")
    assert 'require(path.join(__dirname, "repairs.js"))' in harness
    assert "repair_counts: countRepairs(" in harness
