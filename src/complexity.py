"""ComplexityMeasurer: how complex is a (reference) process model?

Descriptive measures:
  tasks          number of tasks
  gateways       number of gateways (splits and joins)
  loops          number of back edges, i.e. flows that jump back to an earlier element
  nesting_depth  the largest number of splits that are "open" at the same time,
                 e.g. a decision inside a parallel branch has depth 2

Control-Flow Complexity (CFC, Cardoso 2005, 2006) counts how many different
situations ("states") a reader must consider after each split. Every split adds:
  exclusive split (XOR) with n outgoing branches:  n        exactly one of n paths is chosen
  parallel split (AND):                            1        all paths run, so only one situation
  inclusive split (OR) with n outgoing branches:   2^n - 1  any non-empty subset of the paths can run
CFC is the sum over all splits; joins add nothing.

Mapping of other BPMN split types (Cardoso defines only XOR, AND and OR):
  event-based gateway  -> like XOR (one path is chosen, by the first event)
  complex gateway      -> like OR (any combination of paths may be activated)
  activity with several outgoing flows -> like AND (BPMN starts all of them)
A split's branches include flows that loop back, because they are real choices.
"""

from src.bpmn_graph import BPMNGraph

XOR_LIKE = {"exclusiveGateway", "eventBasedGateway"}
OR_LIKE = {"inclusiveGateway", "complexGateway"}


class ComplexityMeasurer:
    """Computes the descriptive measures and the CFC of one BPMN model."""

    def measure(self, graph: BPMNGraph) -> dict:
        return {
            "tasks": len(graph.tasks),
            "gateways": len(graph.gateways),
            "loops": len(graph.back_edges),
            "nesting_depth": nesting_depth(graph),
            "cfc": control_flow_complexity(graph),
        }


def control_flow_complexity(graph: BPMNGraph) -> int:
    """Cardoso's CFC: the sum of every split's contribution (see the module comment)."""
    cfc = 0
    for node, node_type in graph.types.items():
        n = graph.out_degree(node)
        if n < 2:
            continue  # not a split
        if node_type in XOR_LIKE:
            cfc += n
        elif node_type in OR_LIKE:
            cfc += 2 ** n - 1
        else:  # parallel gateway, or an activity/event with several outgoing flows
            cfc += 1
    return cfc


def nesting_depth(graph: BPMNGraph) -> int:
    """Walk through the model from start to end, counting how many splits are open.

    Following a flow out of a split opens one level; arriving at a join closes one.
    The nesting depth is the deepest level any split reaches. In unstructured models
    (where a join does not close exactly one split) this is an approximation.
    """
    open_splits = {}
    deepest = 0
    for node in graph.order:
        coming_in = [open_splits[p] + (1 if graph.is_split(p) else 0) for p in graph.predecessors[node]]
        level = max(coming_in, default=0)
        if graph.is_join(node):
            level = max(level - 1, 0)
        open_splits[node] = level
        if graph.is_split(node):
            deepest = max(deepest, level + 1)
    return deepest
