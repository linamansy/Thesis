"""Tests for BPMNGraph, BehavioralProfile and ComplexityMeasurer (no embedding model needed)."""

from bpmn_helpers import START_END, sequential_model, split_model, write_bpmn

from src.behavioral_profile import BehavioralProfile
from src.bpmn_graph import BPMNGraph
from src.complexity import ComplexityMeasurer

WEIGHTS = {"tasks": 1, "gateways": 2, "loops": 3, "nesting_depth": 3}


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
    assert ComplexityMeasurer(WEIGHTS).measure(graph)["nesting_depth"] == 2


def test_complexity_of_simple_split(tmp_path):
    measures = ComplexityMeasurer(WEIGHTS).measure(graph_of(tmp_path, *split_model("exclusiveGateway")))
    assert measures == {"tasks": 3, "gateways": 2, "loops": 0, "nesting_depth": 1,
                        "complexity_score": 3 * 1 + 2 * 2 + 0 * 3 + 1 * 3}


def test_complexity_counts_loops(tmp_path):
    # s -> A -> XOR -> A (back) or -> e
    nodes = START_END + [("task", "A", "Correct invoice"), ("exclusiveGateway", "x", "OK?")]
    flows = [("s", "A"), ("A", "x"), ("x", "A"), ("x", "e")]
    measures = ComplexityMeasurer(WEIGHTS).measure(graph_of(tmp_path, nodes, flows))
    assert measures["loops"] == 1
    assert measures["nesting_depth"] == 0  # a loop is not a nested split
