"""Helpers for tests: write small BPMN models by hand."""

HEADER = '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"><process id="P">'
FOOTER = "</process></definitions>"


def make_bpmn(nodes: list[tuple[str, str, str]], flows: list[tuple[str, str]]) -> str:
    """nodes: (tag, id, name); flows: (source id, target id)."""
    parts = [f'<{tag} id="{node_id}" name="{name}"/>' for tag, node_id, name in nodes]
    parts += [f'<sequenceFlow id="flow_{i}" sourceRef="{s}" targetRef="{t}"/>' for i, (s, t) in enumerate(flows)]
    return HEADER + "".join(parts) + FOOTER


def write_bpmn(path, nodes, flows):
    path.write_text(make_bpmn(nodes, flows), encoding="utf-8")
    return path


START_END = [("startEvent", "s", "Start"), ("endEvent", "e", "End")]


def split_model(gateway_tag: str):
    """s -> split -> (A | B) -> join -> C -> e, with the given gateway type."""
    nodes = START_END + [
        (gateway_tag, "g1", ""), (gateway_tag, "g2", ""),
        ("task", "A", "Check stock"), ("task", "B", "Check credit"), ("task", "C", "Ship goods"),
    ]
    flows = [("s", "g1"), ("g1", "A"), ("g1", "B"), ("A", "g2"), ("B", "g2"), ("g2", "C"), ("C", "e")]
    return nodes, flows


def sequential_model():
    """s -> A -> B -> C -> e, the same three tasks as split_model() but in sequence."""
    nodes = START_END + [("task", "A", "Check stock"), ("task", "B", "Check credit"), ("task", "C", "Ship goods")]
    flows = [("s", "A"), ("A", "B"), ("B", "C"), ("C", "e")]
    return nodes, flows
