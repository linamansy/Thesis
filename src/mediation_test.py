"""Mediation test of C3 v2 on the Study 2 corpus (docs/MEDIATION_TEST_CRITERIA.md, commit e01ef1c).

Agents only (qwen3:8b on Ollama, the agents' settings in config.yaml), NO BPMN generation. Nothing of C3 v2 is changed:
every passage goes through OrchestratorV2.mediate_passage, exactly as in a C3 run.

Steps (config.yaml mediation_test):
  --build-top5        step 1: the R and O top 5 of every variant, written once to mediation_test.top5_file
                        R = frozen RAG top 5 (rag_v2.frozen_retrieval; held-out variants: the kept-setting report)
                        O = R with rank 5 replaced by the variant's target passage (variant.json target_passage_id)
                            if no accepted target is already in it (text from study2_corpus.passages)
                      The base case gets the SAME top 5 as its variant in each setting.
  --run dev           step 2: 8 development variants + their base cases, settings R and O
  --run heldout       step 4: the 10 held-out variants + their base cases; refused until dev/metrics.json exists
  --report dev|heldout  recompute metrics.json and report.md from answers.json (no model call)

Each "case run" = (variant, setting, role) with role "variant" or "base"; its 5 passages are mediated in rank order.
Outputs in mediation_test.output_dir/<group>/: answers.json (one audit-trail record per passage, written after every
case run; a rerun skips finished case runs), logs/ (every LLM call, RunLogger), metrics.json, report.md.

Measures (criteria section 2), computed by code from the audit trail:
  T1 (O)  target hit: an accepted target passage is Applicable in the variant AND one of its confirmed IF items
          (role fact, scope, situational condition) has a checked quote that lies in the variant's added sentences
  T2 (O)  control: no accepted target passage is Applicable in the base case
  T3 (R, O)  wrong Applicables: Applicable passages that are not an accepted target, with their quotes
  T4 (R)  drop rate: share of retrieved passages NOT passed to the C3 block (passed = Applicable with a requirement
          that passed its code checks, as OrchestratorV2.knowledge_block)
  T5 (O, T1 hits)  requirement: <= max_words words, every listed THEN trigger found in the THEN part and its kept_as in
          the requirement, step_quote verbatim in the passage (criteria wording) - also reported: step_quote in the
          description (the R6 code check of RequirementCheckerV2)
For every miss the audit trail of the passage is summarised and the box(es) that decided it are named
(failing_boxes); the final naming is checked by reading.

Run from the project root (Ollama running):  .venv\\Scripts\\python.exe -m src.mediation_test --run dev
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config, project_path
from src.mediation.applicability_resolver import APPLICABLE
from src.mediation.quote_checker import QuoteChecker
from src.orchestrator import IRRELEVANT, MEDIATION_FAILED

GROUPS = ("dev", "heldout")
SETTINGS = ("R", "O")
ROLES = ("variant", "base")
quote_checker = QuoteChecker()


# ---------- step 1: top 5 lists ----------

def load_variant(config: dict, variant_id: str) -> dict:
    path = project_path(config["paths"]["cases"]) / variant_id / "variant.json"
    v = json.loads(path.read_text(encoding="utf-8"))
    v["accepted"] = v.get("accepted_target_ids") or [v["target_passage_id"]]
    return v


def group_variants(config: dict, group: str) -> list[str]:
    mt = config["mediation_test"]
    if group == "dev":
        return list(mt["development_variants"])
    return list(mt["held_out_variants"]["old"]) + list(mt["held_out_variants"]["v3"])


def r_top5(config: dict, variant_id: str) -> tuple[list[dict], str]:
    """The frozen RAG top 5 of a variant and the file it comes from."""
    mt = config["mediation_test"]
    source = config["rag_v2"]["frozen_retrieval"]
    cases = json.loads(project_path(source).read_text(encoding="utf-8"))["cases"]
    if variant_id not in cases:
        source = next(mt["held_out_r_reports"][k] for k, ids in mt["held_out_variants"].items() if variant_id in ids)
        cases = json.loads(project_path(source).read_text(encoding="utf-8"))["retrievals"]
    passages = sorted(cases[variant_id]["passages"], key=lambda p: p["rank"])
    return [{"rank": p["rank"], "passage_id": p["passage_id"], "text": p["text"]} for p in passages], source


def oracle_top5(r: list[dict], variant: dict, corpus: dict, rank: int) -> tuple[list[dict], str | None]:
    """R with `rank` replaced by the target passage, unless an accepted target is already in R."""
    if any(p["passage_id"] in variant["accepted"] for p in r):
        return [dict(p) for p in r], None
    target = variant["target_passage_id"]
    o = [dict(p) for p in r]
    slot = next(p for p in o if p["rank"] == rank)
    replaced = slot["passage_id"]
    slot.update(passage_id=target, text=corpus[target]["text"], replaces=replaced)
    return o, replaced


def build_top5(config: dict) -> dict:
    mt = config["mediation_test"]
    corpus = {}
    for line in project_path(config["study2_corpus"]["passages"]).read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            corpus[p["id"]] = p
    variants = {}
    for group in GROUPS:
        for vid in group_variants(config, group):
            v = load_variant(config, vid)
            r, source = r_top5(config, vid)
            o, replaced = oracle_top5(r, v, corpus, mt["oracle_rank"])
            variants[vid] = {"group": group, "base_case": v["base_case"], "target_passage_id": v["target_passage_id"],
                             "accepted_target_ids": v["accepted"], "added_text": v["added_text"],
                             "R_source": source, "O_replaced": replaced, "R": r, "O": o}
    return {"note": "Mediation test (docs/MEDIATION_TEST_CRITERIA.md): R = frozen RAG top 5; O = ORACLE diagnostic, "
                    "R with rank 5 replaced by the target if absent (not a retrieval result). The base case gets the "
                    "same top 5 as its variant in each setting.",
            "variants": variants}


def write_top5(config: dict) -> Path:
    path = project_path(config["mediation_test"]["top5_file"])
    if path.exists():
        raise FileExistsError(f"{path} already exists; it is never overwritten")
    data = {"created_at": datetime.now(timezone.utc).isoformat(), **build_top5(config)}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ---------- measures (code only) ----------

def evidence(record: dict) -> list[dict]:
    """Confirmed items with a checked quote (role facts, scope, situational conditions; the role item R1 only
    repeats its fact's quote)."""
    a = record.get("applicability") or {}
    items = [c for c in a.get("conditions", []) if c["kind"] != "role"] + a.get("role_facts", [])
    return [{"id": i["id"], "text": i["text"], "quote": i["quote"], "decided_by": i.get("decided_by")}
            for i in items if i.get("status") == "confirmed" and i.get("quote_found")]


def passed_on(record: dict) -> bool:
    req = record.get("requirement")
    return record["label"] == APPLICABLE and bool(req) and not req["requirement_invalid"]


def failing_boxes(record: dict | None) -> list[str]:
    """The boxes that decided a non-Applicable label, from the audit trail (checked by reading)."""
    if record is None:
        return ["(passage not in the top 5)"]
    if record["label"] == MEDIATION_FAILED:
        step = record["failed_step"]
        return [{"relevance": "relevance", "requirement": "requirement"}.get(step, "split" if step == "split"
                                                                            else "check-IF") + " (no valid answer)"]
    if record["label"] == IRRELEVANT:
        return ["relevance"]
    a = record["applicability"]
    if record["label"] == "Split invalid":
        return ["split (obligation word in an IF item)"]
    boxes = []
    for e in (record.get("resolution") or {}).get("exceptions_applying", []):
        boxes.append(f"check-IF (exception confirmed: {e})")
    for c in a["conditions"] + a["role_facts"]:
        if c.get("status") == "confirmed":
            continue
        if c.get("downgraded"):
            boxes.append(f"quote check ({c['id']}: model said {c.get('original_status')}, quote not found)")
        elif c["kind"] == "role":
            # R1 is set by the role rule (R3) from the split's roles and the role facts / S1 (named on their own)
            if c.get("decided_by") == "code rule":
                roles = ", ".join(r["role"] for r in c.get("roles", []))
                boxes.append(f"split + scope/role rule (R1 {c.get('status')}: split named {roles})")
        elif c["kind"] in ("scope", "role_fact"):
            boxes.append(f"check-IF ({c['id']} {c.get('status')}, first look; {c['kind']} item)")
        else:
            look = "second look" if c.get("first_look_status") else "first look"
            boxes.append(f"check-IF ({c['id']} {c.get('status')}, {look})")
    if not boxes and record["label"] != APPLICABLE:
        boxes.append("resolver (" + (record.get("resolution") or {}).get("reason", "?") + ")")
    return boxes


def trail(record: dict | None) -> dict | None:
    """A short audit-trail summary of one passage for the report."""
    if record is None:
        return None
    rel = record.get("relevance") or {}
    a = record.get("applicability") or {}
    items = [{k: c.get(k) for k in ("id", "text", "status", "original_status", "quote", "quote_found", "decided_by")}
             for c in a.get("conditions", []) + a.get("role_facts", []) + a.get("exceptions", [])]
    return {"label": record["label"], "failed_step": record.get("failed_step"),
            "relevance": {k: rel.get(k) for k in ("relevant", "final_relevant", "law_quote_found",
                                                  "description_quote_found", "process_step", "reason")},
            "split": a.get("split"), "rejected_if": a.get("rejected_if"), "items": items,
            "look": a.get("look"), "resolution": record.get("resolution")}


def requirement_checks(record: dict, max_words: int) -> dict:
    """T5 code checks on the final requirement attempt of a target hit."""
    req = record.get("requirement")
    if not req or not req["attempts"]:
        return {"requirement": None, "pass": False, "note": "no valid answer"}
    final = req["attempts"][-1]
    then = record["applicability"]["split"]["then"]
    triggers_ok = all(quote_checker.found(t["trigger"], then) and quote_checker.found(t["kept_as"], final["requirement"])
                      for t in final["triggers"])
    checks = {"words_ok": final["measures"]["n_words"] <= max_words, "triggers_kept": triggers_ok,
              "step_quote_in_passage": bool(quote_checker.found(final["step_quote"], record["passage_text"]))}
    return {"requirement": final["requirement"], "step_quote": final["step_quote"], "triggers": final["triggers"],
            "n_words": final["measures"]["n_words"], "requirement_invalid": req["requirement_invalid"],
            "problems": final["problems"], **checks,
            "step_quote_in_description": not any("step_quote" in p for p in final["problems"]),
            "pass": all(checks.values()) and not req["requirement_invalid"]}


def metrics(records: list[dict], top5: dict, config: dict) -> dict:
    max_words = config["c3_v2"]["requirement_checks"]["max_words"]
    runs = {}
    for r in records:
        runs.setdefault((r["variant"], r["setting"], r["role"]), []).append(r)
    rows, wrong, misses, t5 = [], [], [], []
    for vid in dict.fromkeys(r["variant"] for r in records):
        v = top5["variants"][vid]
        accepted = v["accepted_target_ids"]
        row = {"variant": vid, "base_case": v["base_case"], "target": v["target_passage_id"],
               "accepted": accepted, "O_replaced": v["O_replaced"]}
        for setting in SETTINGS:
            for role in ROLES:
                recs = runs.get((vid, setting, role), [])
                row[f"{setting}_{role}_labels"] = {x["passage_id"]: x["label"] for x in recs}
                row[f"{setting}_{role}_applicable"] = [x["passage_id"] for x in recs if x["label"] == APPLICABLE]
                row[f"{setting}_{role}_passed_on"] = sum(passed_on(x) for x in recs)
                row[f"{setting}_{role}_n"] = len(recs)
                for x in recs:
                    if x["label"] == APPLICABLE and x["passage_id"] not in accepted:
                        wrong.append({"variant": vid, "setting": setting, "role": role, "case_id": x["case_id"],
                                      "passage_id": x["passage_id"], "evidence": evidence(x),
                                      "requirement": (x.get("requirement") or {}).get("requirement")})
        # T1 (O, variant)
        o_var = [x for x in runs.get((vid, "O", "variant"), []) if x["passage_id"] in accepted]
        target_rec = next(iter(o_var), None)
        hits = []
        for x in o_var:
            added = [e for e in evidence(x) if quote_checker.found(e["quote"], v["added_text"])]
            if x["label"] == APPLICABLE and added:
                hits.append((x, added))
        row["T1_hit"] = bool(hits)
        row["O_variant_target_label"] = target_rec["label"] if target_rec else None
        row["O_variant_target_evidence"] = evidence(target_rec) if target_rec else []
        row["T1_added_quotes"] = [e for _, added in hits for e in added]
        if not hits:
            misses.append({"measure": "T1", "variant": vid, "case_id": vid, "passage_id": v["target_passage_id"],
                           "boxes": (["check-IF (Applicable, but no checked quote from the added sentences)"]
                                     if target_rec and target_rec["label"] == APPLICABLE else failing_boxes(target_rec)),
                           "trail": trail(target_rec)})
        for x, _ in hits[:1]:
            checks = requirement_checks(x, max_words)
            t5.append({"variant": vid, "passage_id": x["passage_id"], **checks})
            if not checks["pass"]:
                misses.append({"measure": "T5", "variant": vid, "case_id": vid, "passage_id": x["passage_id"],
                               "boxes": ["requirement"], "checks": checks})
        # T2 (O, base)
        o_base = [x for x in runs.get((vid, "O", "base"), []) if x["passage_id"] in accepted]
        row["O_base_target_label"] = o_base[0]["label"] if o_base else None
        row["T2_pass"] = bool(o_base) and not any(x["label"] == APPLICABLE for x in o_base)
        for x in o_base:
            if x["label"] == APPLICABLE:
                misses.append({"measure": "T2", "variant": vid, "case_id": x["case_id"], "passage_id": x["passage_id"],
                               "boxes": ["check-IF / scope/role rule (Applicable without the added sentences)"],
                               "evidence": evidence(x), "trail": trail(x)})
        # T4 (R)
        n = row["R_variant_n"] + row["R_base_n"]
        row["R_drop_rate_variant"] = round(1 - row["R_variant_passed_on"] / row["R_variant_n"], 4) if row["R_variant_n"] else None
        row["R_drop_rate_base"] = round(1 - row["R_base_passed_on"] / row["R_base_n"], 4) if row["R_base_n"] else None
        row["R_drop_rate"] = round(1 - (row["R_variant_passed_on"] + row["R_base_passed_on"]) / n, 4) if n else None
        rows.append(row)
    for w in wrong:
        misses.append({"measure": "T3", **w})
    r_n = sum(r["R_variant_n"] + r["R_base_n"] for r in rows)
    r_passed = sum(r["R_variant_passed_on"] + r["R_base_passed_on"] for r in rows)
    summary = {
        "n_variants": len(rows),
        "T1_hits": sum(r["T1_hit"] for r in rows),
        "T2_pass": sum(r["T2_pass"] for r in rows),
        "T3_wrong_applicable": {f"{s}_{role}": sum(w["setting"] == s and w["role"] == role for w in wrong)
                                for s in SETTINGS for role in ROLES},
        "T3_wrong_applicable_base_total": sum(w["role"] == "base" for w in wrong),
        "T4_drop_rate_R": round(1 - r_passed / r_n, 4) if r_n else None,
        "T4_passages_R": r_n, "T4_passed_on_R": r_passed,
        "T5_hits_checked": len(t5), "T5_all_checks_pass": sum(c["pass"] for c in t5),
        "T5_step_quote_in_description": sum(c.get("step_quote_in_description", False) for c in t5),
    }
    return {"summary": summary, "per_variant": rows, "wrong_applicables": wrong, "t5": t5, "misses": misses}


# ---------- report ----------

def report(m: dict, group: str, targets: bool, model_label: str = "qwen3:8b") -> str:
    s = m["summary"]
    n = s["n_variants"]
    title = "development set" if group == "dev" else "held-out set (measured once, report only)"
    lines = [f"# Mediation test, {title}", "",
             "docs/MEDIATION_TEST_CRITERIA.md (commit e01ef1c). C3 v2 agents only, " + model_label + ", no BPMN generation.", "",
             "## T1-T5", "", "| measure | result | target |", "|---|---|---|",
             f"| T1 target hit (O) | {s['T1_hits']}/{n} | {'>= 6/8' if targets else 'none (report only)'} |",
             f"| T2 control (O) | {s['T2_pass']}/{n} | {'>= 7/8' if targets else 'none (report only)'} |",
             f"| T3 wrong Applicables, base cases (R + O) | {s['T3_wrong_applicable_base_total']} | "
             f"{'0' if targets else 'none (report only)'} |",
             f"| T3 wrong Applicables per setting/role | {s['T3_wrong_applicable']} | - |",
             f"| T4 drop rate (R) | {s['T4_drop_rate_R']} ({s['T4_passages_R'] - s['T4_passed_on_R']} of "
             f"{s['T4_passages_R']} not passed on) | none |",
             f"| T5 requirement code checks (O, T1 hits) | {s['T5_all_checks_pass']}/{s['T5_hits_checked']} pass "
             f"(step_quote in description: {s['T5_step_quote_in_description']}/{s['T5_hits_checked']}) | "
             f"{'all pass' if targets else 'none (report only)'} |", "",
             "## Per variant", "",
             "| variant | target | O: variant label (+ quote from added text) | O: base label | R: Applicables "
             "(variant / base) | drop rate R (variant / base) |", "|---|---|---|---|---|---|"]
    for r in m["per_variant"]:
        quotes = "; ".join(f"{e['id']}: \"{e['quote']}\"" for e in r["T1_added_quotes"]) or "no quote from added text"
        lines.append(f"| {r['variant']} | {r['target']} | {r['O_variant_target_label']} ({quotes}) | "
                     f"{r['O_base_target_label']} | {', '.join(r['R_variant_applicable']) or '-'} / "
                     f"{', '.join(r['R_base_applicable']) or '-'} | {r['R_drop_rate_variant']} / {r['R_drop_rate_base']} |")
    lines += ["", "## Wrong Applicables (T3)", ""]
    for w in m["wrong_applicables"] or []:
        quotes = "; ".join(f"{e['id']} \"{e['quote']}\"" for e in w["evidence"]) or "(no quote: confirmed by code rule)"
        lines.append(f"- {w['setting']} / {w['role']} {w['case_id']} (variant {w['variant']}): {w['passage_id']} - {quotes}")
    if not m["wrong_applicables"]:
        lines.append("none")
    lines += ["", "## Misses (automatic box naming from the audit trail; checked by reading)", ""]
    for x in m["misses"]:
        if x["measure"] == "T3":
            continue
        lines.append(f"- {x['measure']} {x['case_id']} {x['passage_id']}: {'; '.join(x['boxes'])}")
    lines += ["", "## T5 requirements (target hits)", ""]
    for c in m["t5"]:
        lines.append(f"- {c['variant']} {c['passage_id']}: \"{c['requirement']}\" ({c.get('n_words')} words; "
                     f"triggers kept {c.get('triggers_kept')}; step_quote \"{c.get('step_quote')}\" in passage "
                     f"{c.get('step_quote_in_passage')}, in description {c.get('step_quote_in_description')})")
    return "\n".join(lines) + "\n"


def write_outputs(config: dict, group: str, records: list[dict], top5: dict, out_dir: Path, extra: dict,
                  model_label: str = "qwen3:8b") -> dict:
    m = metrics(records, top5, config)
    m["summary"].update(extra)
    (out_dir / "metrics.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(report(m, group, group == "dev", model_label), encoding="utf-8")
    return m


# ---------- steps 2 and 4: real run ----------

def run(config: dict, group: str, llm=None, out_dir: Path | None = None, run_settings: tuple = SETTINGS,
        model_label: str = "qwen3:8b") -> dict:
    """llm, out_dir, run_settings, model_label: given only by the stronger-model diagnostic
    (scripts/run_mediation_strong.py, docs/MEDIATION_TEST_CRITERIA.md section 6). Without them: qwen3:8b on Ollama
    with its digest and version checks, settings R and O, as in steps 2 and 4."""
    from run_experiment import create_llm, ollama_settings
    from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.agents.requirement_agent_v2 import RequirementAgentV2
    from src.llm.base_llm import LLMUnavailableError
    from src.logger import RunLogger
    from src.orchestrator_v2 import OrchestratorV2
    from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
    from src.study2_config import study2_view

    mt = config["mediation_test"]
    base_dir = project_path(mt["output_dir"])
    out_dir = out_dir or base_dir / group
    if group == "heldout" and not (base_dir / "dev" / "metrics.json").exists():
        sys.exit("Not started: the held-out set runs only after the development metrics (step 3)")
    top5 = json.loads(project_path(mt["top5_file"]).read_text(encoding="utf-8"))
    view = study2_view(config)
    if llm is None:
        try:
            settings = ollama_settings(view)    # model digest = model.ollama_model_digest, server settings
            expected = str(config["study2_gdpr"]["ollama_version"])
            if settings.get("ollama_version") != expected:
                raise ValueError(f"Ollama is {settings.get('ollama_version')!r}, study2_gdpr.ollama_version is {expected!r}")
            llm = create_llm(view, "relevance", {})
        except (ValueError, FileNotFoundError, LLMUnavailableError) as e:
            sys.exit(f"Not started: {e}")
        extra = {"ollama_version": settings["ollama_version"], "model_digest": settings["generator_digest"]}
    else:
        extra = {"model": llm.model}

    log_dir = out_dir / "logs"
    condition = f"{mt['log_condition']}_{group}"
    logger = RunLogger(log_dir, condition, group, part=1 + len(list(log_dir.glob(f"{condition}_*.jsonl"))))
    applicability = ApplicabilityAgentV2(llm, logger, config=view)
    orch = OrchestratorV2(RelevanceAgentV2(llm, logger), applicability, RequirementAgentV2(llm, logger), {},
                          out_dir / "unused", load_c3_block_template(view, "c3_block_template_v2"),
                          load_no_knowledge_text(view))
    answers_path = out_dir / "answers.json"
    records = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else []
    done = {(r["variant"], r["setting"], r["role"]) for r in records}
    cases_dir = project_path(config["paths"]["cases"])
    for vid in group_variants(config, group):
        v = top5["variants"][vid]
        for setting in run_settings:
            passages = sorted(v[setting], key=lambda p: p["rank"])
            for role, case_id in (("variant", vid), ("base", v["base_case"])):
                if (vid, setting, role) in done:
                    continue
                description = (cases_dir / case_id / config["paths"]["case_description_file"]).read_text(encoding="utf-8")
                for p in passages:
                    record = orch.mediate_passage(case_id, description, p, passages)
                    records.append({"group": group, "variant": vid, "setting": setting, "role": role,
                                    "case_id": case_id} | record)
                    print(f"{vid} {setting} {role} {case_id} rank {p['rank']} {p['passage_id']}: {record['label']}",
                          flush=True)
                out_dir.mkdir(parents=True, exist_ok=True)
                answers_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    m = write_outputs(config, group, records, top5, out_dir, extra, model_label)
    print(json.dumps(m["summary"], indent=2))
    return m


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    config = load_config()
    if "--build-top5" in argv:
        print(write_top5(config))
    elif "--run" in argv:
        group = argv[argv.index("--run") + 1]
        if group not in GROUPS:
            sys.exit(f"--run takes one of {GROUPS}")
        run(config, group)
    elif "--report" in argv:
        group = argv[argv.index("--report") + 1]
        out_dir = project_path(config["mediation_test"]["output_dir"]) / group
        records = json.loads((out_dir / "answers.json").read_text(encoding="utf-8"))
        top5 = json.loads(project_path(config["mediation_test"]["top5_file"]).read_text(encoding="utf-8"))
        old = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))["summary"]
        m = write_outputs(config, group, records, top5, out_dir,
                          {k: old[k] for k in ("ollama_version", "model_digest") if k in old})
        print(json.dumps(m["summary"], indent=2))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
