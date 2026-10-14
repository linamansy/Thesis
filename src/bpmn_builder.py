"""BPMNBuilder: converts a ProcessModel (JSON) into BPMN 2.0 XML. No LLM is involved.

The XML has two parts:
  1. the process itself (events, tasks, gateways, flows, lanes)
  2. a diagram section (BPMNDiagram) with a position for every element, so the
     file can be opened in a BPMN viewer such as bpmn.io or Camunda Modeler.

Layout rule (simple, left to right):
  - column = the longest path from a start event to the element (loops ignored)
  - lane   = the lane of the task, or of a neighbouring task for events/gateways
  - row    = elements sharing a lane and column are stacked below each other
"""

from pathlib import Path

from lxml import etree

from src.schemas import ProcessModel

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI_NS = "http://www.omg.org/spec/BPMN/20100524/DI"
DC_NS = "http://www.omg.org/spec/DD/20100524/DC"
DI_NS = "http://www.omg.org/spec/DD/20100524/DI"
NSMAP = {"bpmn": BPMN_NS, "bpmndi": BPMNDI_NS, "dc": DC_NS, "di": DI_NS}

# Width and height of each kind of shape in the diagram (standard BPMN sizes).
SHAPE_SIZES = {
    "startEvent": (36, 36),
    "endEvent": (36, 36),
    "task": (100, 80),
    "exclusiveGateway": (50, 50),
    "parallelGateway": (50, 50),
}


def ns(namespace: str, tag: str) -> str:
    """Write a tag with its namespace in the form lxml expects: {namespace}tag."""
    return f"{{{namespace}}}{tag}"


class BPMNBuilder:
    """Builds a BPMN XML file from a ProcessModel."""

    COLUMN_WIDTH = 160   # horizontal distance between columns
    ROW_HEIGHT = 120     # vertical distance between rows
    MARGIN = 40          # empty space around the diagram
    POOL_LABEL_WIDTH = 30  # width of the name strip on the left of the pool and of each lane

    def __init__(self, process_id: str = "Process_1"):
        self.process_id = process_id

    # ---------- public ----------

    def write(self, process: ProcessModel, path: Path) -> None:
        """Build the XML and save it to a file."""
        self.build(process).write(str(path), xml_declaration=True, encoding="UTF-8", pretty_print=True)

    def build(self, process: ProcessModel) -> etree._ElementTree:
        """Build the complete BPMN XML tree."""
        root = etree.Element(ns(BPMN_NS, "definitions"), nsmap=NSMAP,
                             id="Definitions_1", targetNamespace="http://thesis.example/bpmn")
        if process.lanes:
            # Lanes must sit inside a pool (participant), which needs a collaboration.
            collaboration = etree.SubElement(root, ns(BPMN_NS, "collaboration"), id="Collaboration_1")
            etree.SubElement(collaboration, ns(BPMN_NS, "participant"), id="Participant_1",
                             name="Process", processRef=self.process_id)

        process_el = etree.SubElement(root, ns(BPMN_NS, "process"), id=self.process_id, isExecutable="false")
        self._add_lanes(process_el, process)
        self._add_flow_nodes(process_el, process)
        self._add_sequence_flows(process_el, process)
        self._add_diagram(root, process, self._layout(process))
        return etree.ElementTree(root)

    # ---------- process part ----------

    def _add_lanes(self, process_el, process: ProcessModel) -> None:
        if not process.lanes:
            return
        lane_set = etree.SubElement(process_el, ns(BPMN_NS, "laneSet"), id="LaneSet_1")
        for lane in process.lanes:
            lane_el = etree.SubElement(lane_set, ns(BPMN_NS, "lane"), id=lane.id, name=lane.name)
            for task_id in lane.task_ids:
                etree.SubElement(lane_el, ns(BPMN_NS, "flowNodeRef")).text = task_id

    def _add_flow_nodes(self, process_el, process: ProcessModel) -> None:
        for tag, element in process.flow_nodes():
            node = etree.SubElement(process_el, ns(BPMN_NS, tag), id=element.id, name=element.name)
            for flow in process.sequence_flows:
                if flow.target == element.id:
                    etree.SubElement(node, ns(BPMN_NS, "incoming")).text = flow.id
            for flow in process.sequence_flows:
                if flow.source == element.id:
                    etree.SubElement(node, ns(BPMN_NS, "outgoing")).text = flow.id

    def _add_sequence_flows(self, process_el, process: ProcessModel) -> None:
        for flow in process.sequence_flows:
            attributes = {"id": flow.id, "sourceRef": flow.source, "targetRef": flow.target}
            if flow.condition:
                attributes["name"] = flow.condition
            etree.SubElement(process_el, ns(BPMN_NS, "sequenceFlow"), **attributes)

    # ---------- layout ----------

    def _layout(self, process: ProcessModel) -> dict:
        """Compute the centre point of every element and the size of the pool and lanes."""
        tags = {element.id: tag for tag, element in process.flow_nodes()}
        node_ids = list(tags)
        # Flows that point to unknown ids cannot be drawn; the validator reports them.
        edges = [(f.source, f.target) for f in process.sequence_flows
                 if f.source in tags and f.target in tags]

        columns = assign_columns(node_ids, [e.id for e in process.start_events], edges)
        lane_of = assign_lanes(process, node_ids, edges)
        band_ids = [lane.id for lane in process.lanes] or [None]  # None = one band, no lanes

        # Row: stack elements that share the same lane and column.
        rows, used = {}, {}
        for node_id in sorted(node_ids, key=lambda n: columns[n]):
            key = (lane_of[node_id], columns[node_id])
            rows[node_id] = used.get(key, 0)
            used[key] = rows[node_id] + 1
        band_rows = {band: max([count for (lane, _), count in used.items() if lane == band], default=1)
                     for band in band_ids}

        origin_x = self.MARGIN + (2 * self.POOL_LABEL_WIDTH + 20 if process.lanes else 0)
        band_top, y = {}, self.MARGIN
        for band in band_ids:
            band_top[band] = y
            y += band_rows[band] * self.ROW_HEIGHT

        centers = {
            n: (origin_x + columns[n] * self.COLUMN_WIDTH + SHAPE_SIZES["task"][0] // 2,
                band_top[lane_of[n]] + rows[n] * self.ROW_HEIGHT + self.ROW_HEIGHT // 2)
            for n in node_ids
        }
        n_columns = max(columns.values(), default=0) + 1
        return {
            "tags": tags,
            "columns": columns,
            "centers": centers,
            "band_top": band_top,
            "band_height": {b: band_rows[b] * self.ROW_HEIGHT for b in band_ids},
            "width": origin_x - self.MARGIN + n_columns * self.COLUMN_WIDTH,
            "height": y - self.MARGIN,
        }

    # ---------- diagram part ----------

    def _add_diagram(self, root, process: ProcessModel, layout: dict) -> None:
        diagram = etree.SubElement(root, ns(BPMNDI_NS, "BPMNDiagram"), id="BPMNDiagram_1")
        plane_target = "Collaboration_1" if process.lanes else self.process_id
        plane = etree.SubElement(diagram, ns(BPMNDI_NS, "BPMNPlane"), id="BPMNPlane_1", bpmnElement=plane_target)

        if process.lanes:
            self._add_shape(plane, "Participant_1", self.MARGIN, self.MARGIN,
                            layout["width"], layout["height"], isHorizontal="true")
            for lane in process.lanes:
                self._add_shape(plane, lane.id, self.MARGIN + self.POOL_LABEL_WIDTH, layout["band_top"][lane.id],
                                layout["width"] - self.POOL_LABEL_WIDTH, layout["band_height"][lane.id],
                                isHorizontal="true")

        for node_id, tag in layout["tags"].items():
            cx, cy = layout["centers"][node_id]
            w, h = SHAPE_SIZES[tag]
            extra = {"isMarkerVisible": "true"} if tag == "exclusiveGateway" else {}
            self._add_shape(plane, node_id, cx - w // 2, cy - h // 2, w, h, **extra)

        for flow in process.sequence_flows:
            if flow.source in layout["tags"] and flow.target in layout["tags"]:
                edge = etree.SubElement(plane, ns(BPMNDI_NS, "BPMNEdge"), id=f"{flow.id}_di", bpmnElement=flow.id)
                for x, y in self._waypoints(layout, flow.source, flow.target):
                    etree.SubElement(edge, ns(DI_NS, "waypoint"), x=str(int(x)), y=str(int(y)))

    def _add_shape(self, plane, element_id, x, y, width, height, **extra) -> None:
        shape = etree.SubElement(plane, ns(BPMNDI_NS, "BPMNShape"), id=f"{element_id}_di",
                                 bpmnElement=element_id, **extra)
        etree.SubElement(shape, ns(DC_NS, "Bounds"), x=str(int(x)), y=str(int(y)),
                         width=str(int(width)), height=str(int(height)))

    def _waypoints(self, layout: dict, source: str, target: str) -> list[tuple[float, float]]:
        """Points the arrow passes through, from source to target."""
        sx, sy = layout["centers"][source]
        tx, ty = layout["centers"][target]
        sw, sh = SHAPE_SIZES[layout["tags"][source]]
        tw, th = SHAPE_SIZES[layout["tags"][target]]

        if layout["columns"][target] > layout["columns"][source]:
            # Forward: leave on the right side, enter on the left side.
            start, end = (sx + sw / 2, sy), (tx - tw / 2, ty)
            if sy == ty:
                return [start, end]
            middle_x = (start[0] + end[0]) / 2
            return [start, (middle_x, sy), (middle_x, ty), end]

        # Backward (a loop): leave at the bottom, go back underneath, enter at the bottom.
        below = max(sy, ty) + self.ROW_HEIGHT / 2 - 5
        return [(sx, sy + sh / 2), (sx, below), (tx, below), (tx, ty + th / 2)]


def find_back_edges(node_ids: list[str], start_ids: list[str], edges: list[tuple[str, str]]) -> set:
    """Find the flows that go back to an earlier element (loops), using depth-first search."""
    successors = {n: [] for n in node_ids}
    for source, target in edges:
        successors[source].append(target)

    state = {}  # "active" while the element is on the current path, "done" afterwards
    back_edges = set()

    def visit(node):
        state[node] = "active"
        for nxt in successors[node]:
            if state.get(nxt) == "active":
                back_edges.add((node, nxt))
            elif nxt not in state:
                visit(nxt)
        state[node] = "done"

    for node in start_ids + node_ids:
        if node not in state:
            visit(node)
    return back_edges


def assign_columns(node_ids: list[str], start_ids: list[str], edges: list[tuple[str, str]]) -> dict:
    """Column of each element = length of the longest path to it, ignoring loops."""
    back_edges = find_back_edges(node_ids, start_ids, edges)
    forward = [e for e in edges if e not in back_edges]

    column = {n: 0 for n in node_ids}
    incoming = {n: 0 for n in node_ids}
    for _, target in forward:
        incoming[target] += 1
    queue = [n for n in node_ids if incoming[n] == 0]
    while queue:  # visit elements in an order where all predecessors come first
        node = queue.pop(0)
        for source, target in forward:
            if source == node:
                column[target] = max(column[target], column[node] + 1)
                incoming[target] -= 1
                if incoming[target] == 0:
                    queue.append(target)
    return column


def assign_lanes(process: ProcessModel, node_ids: list[str], edges: list[tuple[str, str]]) -> dict:
    """Lane of each element. Tasks use their own lane; other elements borrow a neighbour's lane."""
    if not process.lanes:
        return {n: None for n in node_ids}

    lane_of = {task_id: lane.id for lane in process.lanes for task_id in lane.task_ids}
    neighbours = {n: [] for n in node_ids}
    for source, target in edges:
        neighbours[source].append(target)
        neighbours[target].append(source)

    changed = True
    while changed:  # repeat so that chains of gateways also find a lane
        changed = False
        for node in node_ids:
            if node not in lane_of:
                for other in neighbours[node]:
                    if other in lane_of:
                        lane_of[node] = lane_of[other]
                        changed = True
                        break
    for node in node_ids:
        lane_of.setdefault(node, process.lanes[0].id)  # not connected to any task: first lane
    return lane_of
