"""BPMNValidator: basic syntactic checks on a BPMN XML file.

Checks:
  1. the file is well-formed XML and its root is a BPMN <definitions> element
  2. it contains at least one process
  3. there is at least one start event and at least one end event
  4. every id is unique
  5. every sequence flow connects elements that exist

All problems are collected, so one report lists every error, not just the first.
"""

from collections import Counter
from pathlib import Path

from lxml import etree

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

# Elements with an id that a sequence flow may NOT connect to.
NOT_FLOW_NODES = {"process", "sequenceFlow", "laneSet", "lane"}


class BPMNValidator:
    """Checks whether a BPMN file is structurally valid."""

    def validate(self, bpmn_path: Path) -> dict:
        """Return {"parses", "valid", "errors", "counts"} for one file."""
        try:
            root = etree.parse(str(bpmn_path)).getroot()
        except (etree.XMLSyntaxError, OSError) as e:
            return {"parses": False, "valid": False, "errors": [f"could not parse XML: {e}"], "counts": None}

        errors = []
        if root.tag != f"{{{BPMN_NS}}}definitions":
            errors.append(f"root element is {root.tag}, expected BPMN definitions")

        processes = root.findall(f"{{{BPMN_NS}}}process")
        if not processes:
            errors.append("no process element")

        counts = Counter()
        for process in processes:
            errors += self._check_process(process, counts)

        if counts["startEvent"] == 0:
            errors.append("no start event")
        if counts["endEvent"] == 0:
            errors.append("no end event")

        all_ids = [el.get("id") for el in root.iter() if isinstance(el.tag, str) and el.get("id")]
        duplicates = sorted(i for i, n in Counter(all_ids).items() if n > 1)
        if duplicates:
            errors.append(f"duplicate ids: {duplicates}")

        return {
            "parses": True,
            "valid": not errors,
            "errors": errors,
            "counts": {
                "start_events": counts["startEvent"],
                "end_events": counts["endEvent"],
                "tasks": counts["tasks"],
                "gateways": counts["gateways"],
                "sequence_flows": counts["sequenceFlow"],
            },
        }

    def _check_process(self, process, counts: Counter) -> list[str]:
        """Count the elements of one process and check that its flows point to real elements."""
        node_ids = set()
        flows = []
        for el in process.iter():
            if not isinstance(el.tag, str) or not el.tag.startswith(f"{{{BPMN_NS}}}"):
                continue
            name = etree.QName(el).localname
            counts[name] += 1
            if name.lower().endswith("task"):
                counts["tasks"] += 1
            elif name.endswith("Gateway"):
                counts["gateways"] += 1
            if name == "sequenceFlow":
                flows.append(el)
            elif el.get("id") and name not in NOT_FLOW_NODES:
                node_ids.add(el.get("id"))

        errors = []
        for flow in flows:
            for end in ("sourceRef", "targetRef"):
                ref = flow.get(end)
                if ref not in node_ids:
                    errors.append(f"sequence flow {flow.get('id')} has {end}={ref!r}, which is not an element")
        return errors
