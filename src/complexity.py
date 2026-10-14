"""ComplexityMeasurer: how complex is a (reference) process model?

Measures:
  tasks          number of tasks
  gateways       number of gateways (splits and joins)
  loops          number of back edges, i.e. flows that jump back to an earlier element
  nesting_depth  the largest number of splits that are "open" at the same time,
                 e.g. a decision inside a parallel branch has depth 2

Combined score (weights in config.yaml, evaluation.complexity_weights):
  score = w_tasks * tasks + w_gateways * gateways + w_loops * loops + w_nesting * nesting_depth

Default weights 1, 2, 3, 3. Rationale: a task is one unit of work; every gateway adds a
branching decision that a reader (or an LLM) must get right; loops and deep nesting
make the control flow hardest to follow. Process-model metrics research (e.g. Mendling's
work on connectors, cycles and nesting) supports giving control-flow constructs more weight
than plain activities. The weights are a modelling choice and can be changed in config.yaml.
"""

from src.bpmn_graph import BPMNGraph


class ComplexityMeasurer:
    """Computes the complexity measures of one BPMN model."""

    def __init__(self, weights: dict[str, float]):
        self.weights = weights

    def measure(self, graph: BPMNGraph) -> dict:
        measures = {
            "tasks": len(graph.tasks),
            "gateways": len(graph.gateways),
            "loops": len(graph.back_edges),
            "nesting_depth": nesting_depth(graph),
        }
        measures["complexity_score"] = sum(self.weights[name] * value for name, value in measures.items())
        return measures


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
