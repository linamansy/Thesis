"""Behavioral relations between pairs of tasks, and the behavioral similarity of two models.

NOTE: this is an APPROXIMATION of behavioral profiles (Weidlich et al., 2011).
Real behavioral profiles derive the relation of two activities from all possible
executions of the process, which needs a full execution semantics (e.g. Petri nets).
Here the relation is read from the graph structure instead:

  a -> b   order:      b can be reached from a by following the flows
  a <- b   order:      a can be reached from b
  a || b   parallel:   neither can reach the other, and the nearest split where their
                       paths separate lets several paths run (parallel, inclusive or
                       complex gateway, or an activity with several outgoing flows)
  a #  b   exclusive:  neither can reach the other, and the nearest split is an
                       exclusive (or event-based) gateway; also used when the two
                       tasks share no split at all

Simplifications: loops are ignored (back edges are removed, so two tasks inside a
loop are simply in order), and in unstructured models "nearest split" is a heuristic
(the common split with the greatest depth).
"""

from src.bpmn_graph import BPMNGraph


class BehavioralProfile:
    """Answers: what is the relation between task a and task b in this model?"""

    def __init__(self, graph: BPMNGraph):
        self.graph = graph

    def relation(self, a: str, b: str) -> str:
        reach = self.graph.reach
        if b in reach[a]:
            return "->"
        if a in reach[b]:
            return "<-"
        split = self.nearest_common_split(a, b)
        return "#" if split is None else self.graph.split_kind(split)

    def nearest_common_split(self, a: str, b: str) -> str | None:
        """The deepest split from which a and b are reached through DIFFERENT outgoing branches."""
        graph = self.graph
        best = None
        for node in graph.types:
            if not graph.is_split(node):
                continue
            branches_to_a = {nxt for nxt in graph.successors[node] if nxt == a or a in graph.reach[nxt]}
            branches_to_b = {nxt for nxt in graph.successors[node] if nxt == b or b in graph.reach[nxt]}
            separates = any(x != y for x in branches_to_a for y in branches_to_b)
            if separates and (best is None or graph.depth[node] > graph.depth[best]):
                best = node
        return best


def behavioral_similarity(generated: BPMNGraph, reference: BPMNGraph,
                          matches: list[tuple[str, str]]) -> dict:
    """Share of matched task pairs that have the same relation in both models.

    matches: (generated task id, reference task id) for every matched task.
    Only matched tasks are compared; missing and extra tasks are already counted
    by precision and recall. With fewer than two matched tasks there are no pairs
    and the similarity is 0.
    """
    gen_profile, ref_profile = BehavioralProfile(generated), BehavioralProfile(reference)
    pairs = []
    for i in range(len(matches)):
        for j in range(i + 1, len(matches)):
            (g1, r1), (g2, r2) = matches[i], matches[j]
            gen_rel, ref_rel = gen_profile.relation(g1, g2), ref_profile.relation(r1, r2)
            pairs.append({
                "reference_tasks": [reference.names[r1], reference.names[r2]],
                "generated_tasks": [generated.names[g1], generated.names[g2]],
                "reference_relation": ref_rel,
                "generated_relation": gen_rel,
                "same": gen_rel == ref_rel,
            })
    n_same = sum(p["same"] for p in pairs)
    return {
        "behavioral_similarity": n_same / len(pairs) if pairs else 0.0,
        "n_pairs": len(pairs),
        "n_same": n_same,
        "pairs": pairs,
    }
