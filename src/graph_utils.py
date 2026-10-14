"""Small graph helpers shared by the BPMN builder and the evaluator."""


def find_back_edges(node_ids: list[str], start_ids: list[str], edges: list[tuple[str, str]]) -> set:
    """Find the flows that go back to an earlier element (loops), using depth-first search.

    Walking forward from the start, a flow that points to an element that is still
    on the current path closes a loop. Removing these "back edges" leaves a graph
    without loops.
    """
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
