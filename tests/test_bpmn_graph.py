"""Tests for BPMNGraph, BehavioralProfile and ComplexityMeasurer (no embedding model needed)."""

from bpmn_helpers import START_END, sequential_model, split_model, write_bpmn

from src.behavioral_profile import BehavioralProfile
from src.bpmn_graph import BPMNGraph
from src.complexity import ComplexityMeasurer


def graph_of(tmp_path, nodes, flows):
    return BPMNGraph.from_file(write_bpmn(tmp_path / "m.bpmn", nodes, flows))


def test_reads_tasks_and_labels(tmp_path):
    graph = graph_of(tmp_path, *split_model("exclusiveGateway"))
    assert graph.task_labels() == {"A": "Check stock", "B": "Check credit", "C": "Ship goods"}
    assert sorted(graph.gateways) == ["g1", "g2"]


def test_order_relation(tmp_path):
    profile = BehavioralProfile(graph_of(tmp_path, *sequential_model()))
    assert profile.relation("A", "C") == "->"
    assert profile.relation("C", "A") == "<-"


def test_exclusive_relation(tmp_path):
    profile = BehavioralProfile(graph_of(tmp_path, *split_model("exclusiveGateway")))
    assert profile.relation("A", "B") == "#"
    assert profile.relation("A", "C") == "->"


def test_parallel_relation(tmp_path):
    profile = BehavioralProfile(graph_of(tmp_path, *split_model("parallelGateway")))
    assert profile.relation("A", "B") == "||"


def test_activity_with_two_outgoing_flows_is_parallel(tmp_path):
    nodes = START_END + [("task", "X", "Receive order"), ("task", "A", "Pack"), ("task", "B", "Bill")]
    flows = [("s", "X"), ("X", "A"), ("X", "B"), ("A", "e"), ("B", "e")]
    assert BehavioralProfile(graph_of(tmp_path, nodes, flows)).relation("A", "B") == "||"


def test_nearest_split_decides_in_nested_model(tmp_path):
    # s -> AND -> ( A | XOR -> (B | C) -> XOR ) -> AND -> e
    nodes = START_END + [
        ("parallelGateway", "p1", ""), ("parallelGateway", "p2", ""),
        ("exclusiveGateway", "x1", ""), ("exclusiveGateway", "x2", ""),
        ("task", "A", "a"), ("task", "B", "b"), ("task", "C", "c"),
    ]
    flows = [("s", "p1"), ("p1", "A"), ("p1", "x1"), ("x1", "B"), ("x1", "C"),
             ("B", "x2"), ("C", "x2"), ("A", "p2"), ("x2", "p2"), ("p2", "e")]
    graph = graph_of(tmp_path, nodes, flows)
    profile = BehavioralProfile(graph)
    assert profile.relation("B", "C") == "#"
    assert profile.relation("A", "B") == "||"
    measures = ComplexityMeasurer().measure(graph)
    assert measures["nesting_depth"] == 2
    assert measures["cfc"] == 1 + 2  # AND split adds 1, XOR split with 2 branches adds 2


def test_complexity_of_simple_split(tmp_path):
    measures = ComplexityMeasurer().measure(graph_of(tmp_path, *split_model("exclusiveGateway")))
    assert measures == {"tasks": 3, "gateways": 2, "loops": 0, "nesting_depth": 1, "cfc": 2}


def three_way_split(gateway_tag: str):
    """s -> split -> (A | B | C) -> join -> e"""
    nodes = START_END + [(gateway_tag, "g1", ""), (gateway_tag, "g2", ""),
                         ("task", "A", "a"), ("task", "B", "b"), ("task", "C", "c")]
    flows = [("s", "g1"), ("g1", "A"), ("g1", "B"), ("g1", "C"),
             ("A", "g2"), ("B", "g2"), ("C", "g2"), ("g2", "e")]
    return nodes, flows


def test_cfc_per_gateway_type(tmp_path):
    def cfc(tag):
        return ComplexityMeasurer().measure(graph_of(tmp_path, *three_way_split(tag)))["cfc"]

    assert cfc("exclusiveGateway") == 3   # n branches
    assert cfc("parallelGateway") == 1    # always 1
    assert cfc("inclusiveGateway") == 7   # 2^3 - 1
    assert cfc("eventBasedGateway") == 3  # treated like XOR
    assert cfc("complexGateway") == 7     # treated like OR


def test_cfc_of_sequence_is_zero(tmp_path):
    assert ComplexityMeasurer().measure(graph_of(tmp_path, *sequential_model()))["cfc"] == 0


def test_complexity_counts_loops(tmp_path):
    # s -> A -> XOR -> A (back) or -> e
    nodes = START_END + [("task", "A", "Correct invoice"), ("exclusiveGateway", "x", "OK?")]
    flows = [("s", "A"), ("A", "x"), ("x", "A"), ("x", "e")]
    measures = ComplexityMeasurer().measure(graph_of(tmp_path, nodes, flows))
    assert measures["loops"] == 1
    assert measures["nesting_depth"] == 0  # a loop is not a nested split
    assert measures["cfc"] == 2            # but the loop decision is a real XOR choice with 2 branches
