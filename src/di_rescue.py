"""DIRescue: evaluate the process part of a model whose ONLY problem is its diagram (bpmndi) section.

A BPMN file has two parts:
  - the process part (<bpmn:process>, <bpmn:collaboration>): tasks, gateways, flows - what is evaluated
  - the diagram part (<bpmndi:BPMNDiagram>): only x/y positions for drawing, no process meaning
qwen3 sometimes writes a diagram part with bpmndi: tags but forgets to declare the bpmndi namespace in the
file header. A strict XML parser then rejects the WHOLE file, although the process part is fine.

Validity rule (decided 18 Oct 2026, before the real runs, the same for C1, C2 and C3):
  - "valid" stays the strict verdict of our validator (src/validator.py); a rescued file is still NOT valid
  - for the structural metrics only (precision, recall, F1, behavioral similarity, ...), a file that is not
    valid is rescued when removing its <bpmndi:BPMNDiagram> section(s) makes it pass the whole validator.
    That shows the diagram section was the only problem. The evaluation then marks di_stripped = True.
  - nothing else is ever repaired: if the file still fails without its diagram section (e.g. a "b3pmn:" typo
    in the process part), it is not rescued and scores 0 like every other invalid model.
The stripped copy is made in memory and written to a temporary folder only; the generated file is never changed.
"""

import re
from pathlib import Path

from src.validator import BPMNValidator

# One diagram section: <bpmndi:BPMNDiagram .../> or <bpmndi:BPMNDiagram ...> ... </bpmndi:BPMNDiagram>.
DIAGRAM_SECTION = re.compile(
    r"<bpmndi:BPMNDiagram\b[^>]*?/>|<bpmndi:BPMNDiagram\b[^>]*>.*?</bpmndi:BPMNDiagram\s*>", re.DOTALL)


class DIRescue:
    """Decides whether a model can be evaluated without its diagram section, and makes that copy."""

    def __init__(self, validator: BPMNValidator | None = None):
        self.validator = validator or BPMNValidator()

    @staticmethod
    def strip_diagram(xml_text: str) -> str | None:
        """The XML without its <bpmndi:BPMNDiagram> section(s); None if it has no such section."""
        stripped, n_removed = DIAGRAM_SECTION.subn("", xml_text)
        return stripped if n_removed else None

    def rescue(self, bpmn_path: Path, work_dir: Path) -> Path | None:
        """Path of a stripped copy (in work_dir) that passes the validator, or None if no rescue applies.

        None when: the file is already valid (nothing to rescue), it has no diagram section, or it still
        fails the validator without its diagram section (the problem is elsewhere).
        """
        if self.validator.validate(bpmn_path)["valid"]:
            return None
        stripped = self.strip_diagram(Path(bpmn_path).read_text(encoding="utf-8"))
        if stripped is None:
            return None
        copy = Path(work_dir) / "generated_di_stripped.bpmn"
        copy.write_text(stripped, encoding="utf-8")
        return copy if self.validator.validate(copy)["valid"] else None
