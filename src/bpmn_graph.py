"""BPMNGraph: a BPMN file seen as a directed graph, used by the evaluator.

Nodes are the flow elements (events, tasks, gateways); edges are the sequence
flows. Loops are found as "back edges" (flows that jump back to an earlier
element). Reachability, depth and split/join information are computed on the
graph WITHOUT the back edges, so that every calculation finishes and "before /
after" has a clear meaning.
"""

from pathlib import Path

from lxml import etree

from src.bpmn_builder import BPMN_NS
from src.graph_utils import find_back_edges

# Splits where only one outgoing path is taken. Every other kind of split
# (parallel, inclusive, complex gateway, or an activity with several outgoing
# flows, which BPMN treats as parallel) lets several paths run.
EXCLUSIVE_SPLIT_TYPES = {"exclusiveGateway", "eventBasedGateway"}


def is_task(tag: str) -> bool:
    """task, userTask, serviceTask, manualTask, ..."""
    return tag.lower().endswith("task")


def is_flow_node(tag: str) -> bool:
    return is_task(tag) or tag.endswith("Event") or tag.endswith("Gateway") or tag in ("subProcess", "callActivity")


class BPMNGraph:
    """The control-flow graph of one BPMN model."""

    def __init__(self, types: dict[str, str], names: dict[str, str], edges: list[tuple[str, str]]):
        self.types = types    # element id -> BPMN tag, e.g. "task", "exclusiveGateway"
        self.names = names    # element id -> label
        self.edges = edges    # (source id, target id) for every sequence flow

        starts = [n for n, t in types.items() if t == "startEvent"]
        self.back_edges = find_back_edges(list(types), starts, edges)
        self.successors = {n: [] for n in types}
        self.predecessors = {n: [] for n in types}
        for source, target in edges:
            if (source, target) not in self.back_edges:
                self.successors[source].append(target)
                self.predecessors[target].append(source)

        self.order = self._topological_order()
        self.reach = self._reachability()
        self.depth = self._depths()

    @classmethod
    def from_file(cls, path: Path) -> "BPMNGraph":
        root = etree.parse(str(path)).getroot()
        types, names, edges = {}, {}, []
        for process in root.iter(f"{{{BPMN_NS}}}process"):
            for el in process:
                if not isinstance(el.tag, str):
                    continue
                tag = etree.QName(el).localname
                if tag == "sequenceFlow":
                    edges.append((el.get("sourceRef"), el.get("targetRef")))
                elif is_flow_node(tag) and el.get("id"):
                    types[el.get("id")] = tag
                    names[el.get("id")] = " ".join((el.get("name") or "").split())  # tidy line breaks
        edges = [(s, t) for s, t in edges if s in types and t in types]
        return cls(types, names, edges)

    # ---------- simple questions about the model ----------

    @property
    def tasks(self) -> list[str]:
        return [n for n, t in self.types.items() if is_task(t)]

    @property
    def gateways(self) -> list[str]:
        return [n for n, t in self.types.items() if t.endswith("Gateway")]

    def task_labels(self) -> dict[str, str]:
        return {n: self.names[n] for n in self.tasks}

    def out_degree(self, node: str) -> int:
        """Number of outgoing flows, including flows that loop back."""
        return sum(1 for source, _ in self.edges if source == node)

    def is_split(self, node: str) -> bool:
        """Split in the loop-free graph (flows that loop back are not counted)."""
        return len(self.successors[node]) >= 2

    def is_join(self, node: str) -> bool:
        return len(self.predecessors[node]) >= 2

    def split_kind(self, node: str) -> str:
        """'#' if only one outgoing path is taken, '||' if several can run."""
        return "#" if self.types[node] in EXCLUSIVE_SPLIT_TYPES else "||"

    # ---------- precomputed graph information ----------

    def _topological_order(self) -> list[str]:
        """Order the nodes so that every node comes after all its predecessors."""
        incoming = {n: len(self.predecessors[n]) for n in self.types}
        queue = [n for n in self.types if incoming[n] == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for nxt in self.successors[node]:
                incoming[nxt] -= 1
                if incoming[nxt] == 0:
                    queue.append(nxt)
        return order

    def _reachability(self) -> dict[str, set[str]]:
        """reach[a] = all nodes that can come after a (following flows, loops ignored)."""
        reach = {}
        for node in reversed(self.order):
            reach[node] = set()
            for nxt in self.successors[node]:
                reach[node] |= {nxt} | reach[nxt]
        return reach

    def _depths(self) -> dict[str, int]:
        """depth[a] = length of the longest path from a start to a."""
        depth = {n: 0 for n in self.types}
        for node in self.order:
            for nxt in self.successors[node]:
                depth[nxt] = max(depth[nxt], depth[node] + 1)
        return depth
