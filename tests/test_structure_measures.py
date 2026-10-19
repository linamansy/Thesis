"""Tests for the structure measures (src/structure_measures.py, fix D1) on synthetic models.
A fake word-overlap matcher replaces the embedding model for actor names."""

import pandas as pd
import pytest

from src.config import load_config
from src.evaluate import Evaluator
from src.structure_measures import NOT_DEFINED, StructureMeasures, read_structure, summary

CONFIG = load_config()
NS = 'xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"'


class WordMatcher:
    model_name, threshold = "fake", 0.75

    def match(self, generated, reference, threshold=None):
        def sim(a, b):
            words = a.lower().split()
            return sum(w in b.lower().split() for w in words) / len(words) if words else 0.0
        used, matched = set(), []
        for gi, g in generated.items():
            for ri, r in reference.items():
                if ri not in used and sim(g, r) >= self.threshold:
                    used.add(ri)
                    matched.append({"generated_id": gi, "reference_id": ri})
                    break
        return {"matched": matched, "missing": [], "extra": []}


def lanes_model(path, lanes, gateway="exclusiveGateway", n_starts=1, loop=False):
    """start -> g (split into A and B) -> A/B -> end; lanes named as given; optional loop back from B to g."""
    lane_xml = "".join(f'<lane id="l{i}" name="{name}"/>' for i, name in enumerate(lanes))
    starts = "".join(f'<startEvent id="s{i}"/><sequenceFlow id="fs{i}" sourceRef="s{i}" targetRef="g"/>'
                     for i in range(n_starts))
    back = '<sequenceFlow id="fl" sourceRef="B" targetRef="g"/>' if loop else ""
    xml = (f'<definitions {NS}><process id="P"><laneSet>{lane_xml}</laneSet>{starts}'
           f'<{gateway} id="g"/><task id="A" name="Check"/><task id="B" name="Ship"/><endEvent id="e"/>'
           '<sequenceFlow id="f1" sourceRef="g" targetRef="A"/><sequenceFlow id="f2" sourceRef="g" targetRef="B"/>'
           f'<sequenceFlow id="f3" sourceRef="A" targetRef="e"/>{back}</process></definitions>')
    path.write_text(xml, encoding="utf-8")
    return path


def pools_model(path, pools):
    """One pool (participant) per actor, no lanes, like BPMNGen."""
    participants = "".join(f'<participant id="p{i}" name="{n}" processRef="P{i}"/>' for i, n in enumerate(pools))
    processes = "".join(f'<process id="P{i}"><startEvent id="s{i}"/><endEvent id="e{i}"/>'
                        f'<sequenceFlow id="f{i}" sourceRef="s{i}" targetRef="e{i}"/></process>'
                        for i in range(len(pools)))
    path.write_text(f'<definitions {NS}><collaboration id="c">{participants}</collaboration>{processes}'
                    '</definitions>', encoding="utf-8")
    return path


def measures():
    return StructureMeasures(Evaluator(CONFIG, WordMatcher()))


def test_actors_from_pools_are_matched_against_reference_lanes(tmp_path):
    ref = read_structure(lanes_model(tmp_path / "ref.bpmn", ["Sales clerk", "Warehouse", "Accounting"]), True)
    gen = read_structure(pools_model(tmp_path / "gen.bpmn", ["Sales clerk", "Warehouse"]), True)
    row = measures().compare(gen, ref)
    assert (row["actors_generated"], row["actors_reference"], row["actors_matched"]) == (2, 3, 2)
    assert row["actors_precision"] == 1.0 and row["actors_recall"] == 0.6667


def test_reference_without_actors_gives_not_defined(tmp_path):
    ref = read_structure(lanes_model(tmp_path / "ref.bpmn", []), True)
    gen = read_structure(pools_model(tmp_path / "gen.bpmn", ["Clerk"]), True)
    row = measures().compare(gen, ref)
    assert row["actors_precision"] == NOT_DEFINED and row["actors_recall"] == NOT_DEFINED


def test_decisions_are_matched_per_gateway_type(tmp_path):
    ref = read_structure(lanes_model(tmp_path / "ref.bpmn", [], gateway="exclusiveGateway"), True)
    same = read_structure(lanes_model(tmp_path / "same.bpmn", [], gateway="exclusiveGateway"), True)
    other = read_structure(lanes_model(tmp_path / "other.bpmn", [], gateway="parallelGateway"), True)
    assert measures().compare(same, ref)["decisions_recall"] == 1.0
    row = measures().compare(other, ref)
    assert row["decisions_matched"] == 0 and row["decisions_precision"] == 0.0 and row["decisions_recall"] == 0.0
    assert row["decision_types_generated"] == '{"parallelGateway": 1}'


def test_a_loop_decision_still_counts(tmp_path):
    looped = read_structure(lanes_model(tmp_path / "loop.bpmn", [], loop=True), True)
    assert sum(looped["decisions"].values()) == 1


def test_start_and_end_events_by_count(tmp_path):
    ref = read_structure(lanes_model(tmp_path / "ref.bpmn", []), True)
    gen = read_structure(lanes_model(tmp_path / "gen.bpmn", [], n_starts=2), True)
    row = measures().compare(gen, ref)
    assert (row["start_events_generated"], row["start_events_matched"]) == (2, 1)
    assert row["start_events_precision"] == 0.5 and row["start_events_recall"] == 1.0
    assert row["end_events_precision"] == 1.0


def test_failed_model_scores_zero_where_defined(tmp_path):
    ref = read_structure(lanes_model(tmp_path / "ref.bpmn", []), True)
    row = measures().compare(None, ref)
    assert row["decisions_precision"] == 0.0 and row["decisions_recall"] == 0.0
    assert row["actors_precision"] == NOT_DEFINED      # the reference has no actors


def test_summary_averages_only_defined_values():
    table = pd.DataFrame([{"condition": "C1", **{f"{f}_{k}": v for f in ["actors", "decisions", "start_events",
                                                                          "end_events"]
                                                for k, v in [("precision", 1.0), ("recall", 0.5)]}},
                          {"condition": "C1", "actors_precision": NOT_DEFINED, "actors_recall": NOT_DEFINED,
                           "decisions_precision": 0.0, "decisions_recall": 0.5, "start_events_precision": 1.0,
                           "start_events_recall": 1.0, "end_events_precision": 1.0, "end_events_recall": 1.0}])
    text = summary(table)
    assert "| C1 | actors | 1.0000 (n=1) | 0.5000 (n=1) |" in text
    assert "| C1 | decisions | 0.5000 (n=2) | 0.5000 (n=2) |" in text


def test_command_never_overwrites(tmp_path, monkeypatch):
    from src import structure_measures
    existing = tmp_path / "s.csv"
    existing.write_text("x", encoding="utf-8")
    config = dict(CONFIG, paths=dict(CONFIG["paths"], structure_measures_csv=str(existing),
                                     structure_measures_report=str(tmp_path / "s.md")))
    monkeypatch.setattr(structure_measures, "load_config", lambda: config)
    with pytest.raises(SystemExit, match="never overwritten"):
        structure_measures.main()
