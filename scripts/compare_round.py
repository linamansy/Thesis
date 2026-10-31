"""Design-round report (NO LLM): the target's oracle label before a design round (med_alldev_oracle_run_<n>) and after
it (med_<label>_run_<n>, scripts/run_all_dev.py --oracle-label <label>), for every development variant.

Sections:
  1. table: variant, target, alldev oracle letter, <label> oracle letter, the fixes involved in the new label
  2. every target that is still not A/AC: the cause, then each IF item of the main rule and of every sub-rule
     (id, kind, status, quotes, verifier reason, failing stage)
  3. EVERY Applicable / Applicable (conditional) rule on ANY passage of the <label> oracle runs (main rules and
     sub-rules, targets and other paragraphs), with its requirement, to check for false positives
"Fixes involved" is found by code from the audit trails (a pointer to read the items, not a proof):
  D1   the duty holder rule changed the split's roles
  D2   the relevance label changed (Irrelevant <-> relevant)
  D3   an item the verifier rejected before (same id and text) is confirmed by the verifier now
  D4a  an "any" group with more than one item was used
  D4b  the passage has a sub-rule (special case)
  D5   a case-event unit was used (label Applicable (conditional), or a case event decided it)
Letters as in scripts/summarise_all_dev.py, plus AC = Applicable (conditional) with a valid requirement (AC* invalid).

Output: printed and written to results/debug/<label>_comparison.txt.
    .venv\\Scripts\\python.exe -m scripts.compare_round --label round1
"""

import argparse
import json
from pathlib import Path

from scripts.debug_single_case import load_answer_key
from scripts.run_all_dev import ORACLE_LABEL, VARIANTS, is_done, med_dir
from scripts.summarise_all_dev import item_stage, letter, record_cause, target_record
from src.config import load_config, project_path
from src.mediation.resolver_v2 import APPLICABLE_LABELS

PASS_VARIANT, PASS_TARGET = "01.1", "GDPR-Art13-1"   # regression rule of design round 1


def rules_of(record: dict) -> list[dict]:
    """The main rule (the passage record) and its sub-rules (D4b)."""
    return [record] + ((record.get("applicability") or {}).get("sub_rules") or [])


def units_of(rule: dict) -> list[dict]:
    return (rule.get("resolution") or {}).get("units") or []


def same_item(old: dict | None, item_id: str, text: str) -> dict | None:
    a = (old or {}).get("applicability") or {}
    for item in (a.get("conditions") or []) + (a.get("role_facts") or []):
        if item["id"] == item_id and (item.get("text_sent") or item.get("text")) == text:
            return item
    return None


def fixes_involved(old: dict | None, new: dict | None) -> list[str]:
    if new is None:
        return []
    a = new.get("applicability") or {}
    fixes = []
    holder = a.get("duty_holder")
    if holder and holder["roles"] != holder["split_roles"]:
        fixes.append("D1")
    if old is not None and (old["label"] == "Irrelevant") != (new["label"] == "Irrelevant"):
        fixes.append("D2")
    for item in (a.get("conditions") or []) + (a.get("role_facts") or []):
        before = same_item(old, item["id"], item.get("text_sent") or item.get("text"))
        if (before and before.get("downgrade_cause") == "verifier rejected" and item.get("status") == "confirmed"
                and (item.get("verifier") or {}).get("answer") == "yes"):
            fixes.append("D3")
            break
    rules = rules_of(new)
    if any(u["logic"] == "any" and len(u["items"]) > 1 for r in rules for u in units_of(r)):
        fixes.append("D4a")
    if a.get("sub_rules"):
        fixes.append("D4b")
    if any(u.get("case_event") for r in rules for u in units_of(r)):
        fixes.append("D5")
    return fixes


def rule_letter(rule: dict) -> str:
    """The letter of one rule (main or sub-rule)."""
    if rule.get("failed_step"):
        return "F"
    if rule.get("label") in APPLICABLE_LABELS:
        base = "A" if rule["label"] == "Applicable" else "AC"
        req = rule.get("requirement") or {}
        return base if req.get("requirement") and not req.get("requirement_invalid") else base + "*"
    return letter({**rule, "failed_step": None}, "?") if rule.get("label") else "?"


def cell(record: dict | None) -> str:
    """The main rule's letter, with the sub-rules' letters in brackets."""
    if record is None:
        return "?"
    subs = ((record.get("applicability") or {}).get("sub_rules") or [])
    return rule_letter(record) + (" [" + " ".join(f"{s['id']}:{rule_letter(s)}" for s in subs) + "]" if subs else "")


def item_lines(rule: dict, indent: str = "      ") -> list[str]:
    a = rule.get("applicability") if "applicability" in rule else rule
    a = a or {}
    lines = []
    for items, is_exception in ((a.get("conditions") or [], False), (a.get("role_facts") or [], False),
                                (a.get("exceptions") or [], True)):
        for item in items:
            kind = item.get("kind") or "exception"
            if item.get("item_kind"):
                kind += f"/{item['item_kind']}"
            if item.get("logic") == "any":
                kind += f" ({item['group']} any)"
            quotes = item.get("quotes_canonical") or []
            lines += [f"{indent}{item['id']:<3} {kind:<32} {item.get('status')}: {item.get('text_sent') or item.get('text')}",
                      f"{indent}    quotes: {json.dumps(quotes, ensure_ascii=False) if quotes else '-'}",
                      f"{indent}    verifier: {(item.get('verifier') or {}).get('reason') or '-'}",
                      f"{indent}    failing stage: {item_stage(item, is_exception)}"]
    return lines


def requirement_text(rule: dict) -> str:
    req = rule.get("requirement") or {}
    if req.get("requirement") and not req.get("requirement_invalid"):
        return req["requirement"]
    if req.get("attempts"):
        last = req["attempts"][-1]
        return f"(invalid) {last.get('requirement')}  -- problems: {'; '.join(last.get('problems') or [])}"
    return "(no requirement: " + str(rule.get("label_cause")) + ")"


def all_records(run_dir: Path) -> list[dict]:
    if not is_done(run_dir):
        return []
    return json.loads((run_dir / "09_audit_trail_full.json").read_text(encoding="utf-8"))


def compare(config: dict, label: str, variants, n: int = 1) -> str:
    debug = project_path(config["paths"]["runs"]).parent / "debug"
    header = f"{'variant':<8}{'target':<16}{'alldev oracle':<16}{label + ' oracle':<22}fixes involved"
    table, details, applicable = [header, "-" * len(header)], [], []
    for variant in variants:
        target = load_answer_key(config, variant)["target_passage_id"]
        old = target_record(med_dir(debug / variant, ORACLE_LABEL, n), target)
        new = target_record(med_dir(debug / variant, label, n), target)
        fixes = fixes_involved(old, new)
        changed = cell(old) != cell(new)
        table.append(f"{variant:<8}{target:<16}{cell(old):<16}{cell(new):<22}"
                     f"{', '.join(fixes) or '-'}{'' if changed else '  (label unchanged)'}")
        if new is not None and not any(rule_letter(r) in ("A", "AC") for r in rules_of(new)):
            details += [f"{variant} {target}: {cell(new)}", f"    cause: {record_cause(new)}"] + item_lines(new)
            for sub in rules_of(new)[1:]:
                details += [f"    sub-rule {sub['id']} ({sub.get('clause')!r}): {sub.get('label')}; cause: "
                            f"{sub.get('label_cause')}"] + item_lines(sub, "        ")
        for record in all_records(med_dir(debug / variant, label, n)):
            for rule in rules_of(record):
                if rule.get("label") in APPLICABLE_LABELS:
                    rule_id = "main" if rule is record else f"sub-rule {rule['id']} ({rule.get('clause')!r})"
                    events = (rule.get("resolution") or {}).get("case_events") or []
                    applicable += [f"{variant} {record['passage_id']}{' (target)' if record['passage_id'] == target else ''}"
                                   f" {rule_id}: {rule['label']} ({rule_letter(rule)})",
                                   f"    requirement: {requirement_text(rule)}"]
                    if events:
                        applicable.append("    case events: " + "; ".join(f"{e['id']}: {e['text']}" for e in events))
    regression = target_record(med_dir(debug / PASS_VARIANT, label, n), PASS_TARGET)
    passed = regression is not None and rule_letter(regression) in ("A", "AC")
    return "\n".join([f"DESIGN ROUND REPORT: {label} oracle run {n} vs alldev oracle run {n} (qwen3:8b)", "",
                      f"Regression rule: {PASS_VARIANT} {PASS_TARGET} Applicable (conditional or not) with requirement: "
                      f"{'PASS' if passed else 'FAIL'} ({cell(regression)})", "", *table, "",
                      "Letters: A Applicable, AC Applicable (conditional), * invalid requirement, I Indeterminate, N Not "
                      "applicable, X Irrelevant, S Split invalid, D No duty, F failed step, ? run missing; [K1:..] sub-rules", "",
                      "TARGETS STILL NOT APPLICABLE", *(details or ["(none)"]), "",
                      f"EVERY APPLICABLE / APPLICABLE (CONDITIONAL) RULE IN THE {label} ORACLE RUNS (any passage)",
                      *(applicable or ["(none)"])]) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare a design round's oracles with the alldev oracles.")
    parser.add_argument("--label", required=True)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args(argv)
    config = load_config()
    text = compare(config, args.label, [v.strip() for v in args.variants.split(",") if v.strip()], args.run)
    out = project_path(config["paths"]["runs"]).parent / "debug" / f"{args.label}_comparison.txt"
    out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
