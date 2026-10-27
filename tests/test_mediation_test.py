"""Tests for src/mediation_test.py (docs/MEDIATION_TEST_CRITERIA.md): top 5 lists and the T1-T5 measures.
No model is called; the records are hand-written audit-trail records in the OrchestratorV2 format."""

from src.config import load_config
from src.mediation_test import build_top5, failing_boxes, metrics, oracle_top5

CONFIG = load_config()


def passages(ids):
    return [{"rank": i, "passage_id": p, "text": f"text of {p}"} for i, p in enumerate(ids, 1)]


def test_oracle_replaces_rank_5_only_if_target_absent():
    corpus = {"T": {"text": "target text"}}
    variant = {"target_passage_id": "T", "accepted": ["T"]}
    o, replaced = oracle_top5(passages(["A", "B", "C", "D", "E"]), variant, corpus, 5)
    assert [p["passage_id"] for p in o] == ["A", "B", "C", "D", "T"] and replaced == "E"
    assert o[4]["text"] == "target text"
    o, replaced = oracle_top5(passages(["A", "T", "C", "D", "E"]), variant, corpus, 5)
    assert [p["passage_id"] for p in o] == ["A", "T", "C", "D", "E"] and replaced is None


def test_build_top5_covers_every_variant_of_the_criteria():
    data = build_top5(CONFIG)["variants"]
    mt = CONFIG["mediation_test"]
    expected = mt["development_variants"] + mt["held_out_variants"]["old"] + mt["held_out_variants"]["v3"]
    assert sorted(data) == sorted(expected) and len(expected) == 18
    for v in data.values():
        assert len(v["R"]) == len(v["O"]) == 5
        assert any(p["passage_id"] in v["accepted_target_ids"] for p in v["O"])
        changed = [(r["passage_id"], o["passage_id"]) for r, o in zip(v["R"], v["O"]) if r != o]
        assert len(changed) == (1 if v["O_replaced"] else 0)


def item(id_, kind, status, quote=None):
    return {"id": id_, "kind": kind, "text": id_, "status": status, "quote": quote, "quote_found": bool(quote),
            "decided_by": "first look" if status != "not_stated" else None}


def record(variant, setting, role, case_id, pid, label, quotes=(), requirement=None):
    conditions = [item("R1", "role", "confirmed"), item("S1", "scope", "confirmed", quotes[0] if quotes else None)]
    conditions += [item(f"C{i}", "situation", "confirmed" if label == "Applicable" else "not_stated", q)
                   for i, q in enumerate(quotes[1:], 1)]
    req = None
    if requirement:
        req = {"requirement": requirement, "requirement_invalid": False,
               "attempts": [{"requirement": requirement, "step_quote": "takes the order", "problems": [],
                             "triggers": [{"trigger": "after the order", "kept_as": "after the order"}],
                             "measures": {"n_words": len(requirement.split())}}]}
    return {"variant": variant, "setting": setting, "role": role, "case_id": case_id, "passage_id": pid,
            "passage_text": "the shop takes the order", "label": label, "failed_step": None,
            "relevance": {"final_relevant": True}, "resolution": {"reason": "x", "exceptions_applying": []},
            "applicability": {"conditions": conditions, "role_facts": [], "exceptions": [], "look": "first",
                              "split": {"then": "confirm after the order is placed"}},
            "requirement": req}


def toy():
    top5 = {"variants": {"9.1": {"base_case": "9", "target_passage_id": "T", "accepted_target_ids": ["T"],
                                 "added_text": "Customers order online.", "O_replaced": "E"}}}
    recs = []
    for setting in ("R", "O"):
        recs.append(record("9.1", setting, "variant", "9.1", "T", "Applicable", ["the shop", "order online"],
                           requirement="Confirm the order after the order is placed."))
        recs += [record("9.1", setting, "variant", "9.1", p, "Indeterminate") for p in "ABCD"]
        recs.append(record("9.1", setting, "base", "9", "T", "Indeterminate"))
        recs += [record("9.1", setting, "base", "9", p, "Indeterminate") for p in "ABC"]
        recs.append(record("9.1", setting, "base", "9", "D", "Applicable", ["the shop"], requirement="Do x."))
    return recs, top5


def test_measures_on_a_hand_written_case():
    recs, top5 = toy()
    m = metrics(recs, top5, CONFIG)
    s = m["summary"]
    assert s["T1_hits"] == 1 and s["T2_pass"] == 1
    assert s["T3_wrong_applicable_base_total"] == 2      # D in the base case, R and O
    assert s["T4_passages_R"] == 10 and s["T4_passed_on_R"] == 2 and s["T4_drop_rate_R"] == 0.8
    assert s["T5_hits_checked"] == 1
    t5 = m["t5"][0]
    assert t5["words_ok"] and t5["triggers_kept"] and t5["step_quote_in_description"]
    assert t5["step_quote_in_passage"]                   # "takes the order" is in the toy passage text
    assert m["per_variant"][0]["T1_added_quotes"][0]["quote"] == "order online"


def test_t1_needs_a_quote_from_the_added_sentences():
    recs, top5 = toy()
    top5["variants"]["9.1"]["added_text"] = "Something else entirely."
    m = metrics(recs, top5, CONFIG)
    assert m["summary"]["T1_hits"] == 0
    miss = next(x for x in m["misses"] if x["measure"] == "T1")
    assert miss["boxes"][0].startswith("check-IF")


def test_failing_boxes_names_the_unconfirmed_items():
    recs, _ = toy()
    rec = next(r for r in recs if r["label"] == "Indeterminate")
    rec["applicability"]["conditions"][1].update(status="not_stated", downgraded=True, original_status="confirmed")
    rec["applicability"]["conditions"].append(item("C1", "situation", "not_stated"))
    boxes = failing_boxes(rec)
    assert boxes[0].startswith("quote check (S1") and boxes[1].startswith("check-IF (C1")
    assert failing_boxes(dict(rec, label="Irrelevant")) == ["relevance"]
    rec["applicability"]["conditions"][0].update(status="contradicted", decided_by="code rule",
                                                 roles=[{"role": "public body"}])
    assert failing_boxes(rec)[0] == "split + scope/role rule (R1 contradicted: split named public body)"
