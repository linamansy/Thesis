"""Summary of scripts/run_all_dev.py (NO LLM): one table row per development variant, then the details of every run in
which the target is not Applicable.

Table columns:
  target      the answer key's target passage
  R           in how many runs the target is in the retrieved (expanded) set of alldev_rag_run_<n>
  oracle      the target's label in med_alldev_oracle_run_<n>: Applicable count / runs, then the label per run
  full run    the same in med_alldev_run_<n> ("-" = target not retrieved in that run, so not mediated)
  requirement the requirement text(s) of the target where it is Applicable (full runs first, else oracle)
Label letters: A Applicable (requirement valid), A* Applicable with an invalid requirement, I Indeterminate,
N Not applicable, X Irrelevant, S Split invalid, D No duty, F failed step, - not retrieved, ? run missing.

Details, for every non-Applicable target (oracle and full runs): the cause of the label, then each IF item (role,
scope, role facts, situations, exceptions): id, kind, status, quotes (canonical), verifier reason, failing stage.

Output: printed and written to results/debug/all_dev_summary.txt.
    .venv\\Scripts\\python.exe -m scripts.summarise_all_dev
"""

import argparse
import json
from pathlib import Path

from scripts.debug_single_case import load_answer_key
from scripts.run_all_dev import LABEL, ORACLE_LABEL, VARIANTS, is_done, med_dir, rag_dir, retrieved_ids
from src.config import load_config, project_path

LETTERS = {"Applicable": "A", "Indeterminate": "I", "Not applicable": "N", "Irrelevant": "X", "Split invalid": "S",
           "No duty": "D"}


def target_record(run_dir: Path, target: str) -> dict | None:
    """The target's audit record of a finished mediation run, or None if the run is missing or did not mediate it."""
    if not is_done(run_dir):
        return None
    records = json.loads((run_dir / "09_audit_trail_full.json").read_text(encoding="utf-8"))
    return next((r for r in records if r["passage_id"] == target), None)


def requirement_ok(record: dict) -> bool:
    req = record.get("requirement") or {}
    return bool(req.get("requirement")) and not req.get("requirement_invalid")


def letter(record: dict | None, missing: str) -> str:
    if record is None:
        return missing
    if record.get("failed_step"):
        return "F"
    if record["label"] == "Applicable":
        return "A" if requirement_ok(record) else "A*"
    return LETTERS.get(record["label"], "?")


def status_cell(letters: list[str]) -> str:
    return f"{letters.count('A')}/{len(letters)} ({' '.join(letters)})"


def item_stage(item: dict, is_exception: bool) -> str:
    """Where an item stopped the rule ("-" if it did not)."""
    status, cause = item.get("status"), item.get("downgrade_cause")
    look = "second look" if "first_look_status" in item else "first look"
    if is_exception:
        return f"exception applies ({item.get('decided_by')})" if status == "confirmed" else "-"
    if status == "confirmed":
        return "-"
    if item.get("kind") == "role":
        return "code rule (roles): " + "; ".join(f"{r['role']}: {r.get('reason')}" for r in item.get("roles", []))
    if cause == "verifier rejected":
        return f"verifier ({look})"
    if cause == "quote not found":
        return f"quote check ({look})"
    if status == "contradicted":
        return f"{item.get('decided_by')}: contradicted"
    return f"{look}: not_stated"


def record_cause(record: dict) -> str:
    if record.get("failed_step"):
        return f"failed at {record['failed_step']}: {record.get('error') or ''}".strip()
    if record["label"] == "Irrelevant":
        return f"relevance: {record.get('label_cause')}"
    if record["label"] in ("Split invalid", "No duty"):
        return f"split: {record.get('label_cause')}"
    if record["label"] == "Applicable":
        return f"requirement: {record.get('label_cause')}"
    return str(record.get("label_cause"))


def item_lines(record: dict) -> list[str]:
    a = record.get("applicability") or {}
    lines = []
    groups = [(a.get("conditions") or [], False), (a.get("role_facts") or [], False), (a.get("exceptions") or [], True)]
    for items, is_exception in groups:
        for item in items:
            quotes = item.get("quotes_canonical") or item.get("quotes") or []
            verifier = (item.get("verifier") or {}).get("reason") or "-"
            lines += [f"      {item['id']:<3} {item.get('kind') or 'exception':<10} {item.get('status')}: "
                      f"{item.get('text_sent') or item.get('text')}",
                      f"          quotes: {json.dumps(quotes, ensure_ascii=False) if quotes else '-'}",
                      f"          verifier: {verifier}",
                      f"          failing stage: {item_stage(item, is_exception)}"]
    return lines


def summarise(config: dict, variants, runs: int) -> str:
    debug = project_path(config["paths"]["runs"]).parent / "debug"
    header = f"{'variant':<8}{'target':<16}{'R':<6}{'oracle':<18}{'full run':<18}requirement"
    table, details = [header, "-" * len(header)], []
    for variant in variants:
        case_dir, target = debug / variant, load_answer_key(config, variant)["target_passage_id"]
        retrieved, oracle, full = [], [], []
        for n in range(1, runs + 1):
            rag = rag_dir(case_dir, n)
            hit = is_done(rag) and target in retrieved_ids(rag)
            retrieved.append(hit)
            oracle.append(("oracle", n, target_record(med_dir(case_dir, ORACLE_LABEL, n), target)))
            done = is_done(med_dir(case_dir, LABEL, n))
            full.append(("full run", n, target_record(med_dir(case_dir, LABEL, n), target) if done else None,
                         "-" if done else "?"))
        oracle_letters = [letter(r, "?") for _, _, r in oracle]
        full_letters = [letter(r, missing) for _, _, r, missing in full]
        reqs = [r["requirement"]["requirement"] for _, _, r, *_ in full + oracle
                if r is not None and r["label"] == "Applicable" and requirement_ok(r)]
        reqs = list(dict.fromkeys(reqs))
        r_cell = f"{sum(retrieved)}/{runs}"
        table.append(f"{variant:<8}{target:<16}{r_cell:<6}{status_cell(oracle_letters):<18}"
                     f"{status_cell(full_letters):<18}{reqs[0] if reqs else '-'}")
        table += [f"{'':<66}{req}" for req in reqs[1:]]
        for kind, n, record, *_ in oracle + full:
            if record is None or letter(record, "") == "A":
                continue
            details += [f"{variant} {target} {kind} {n}: {record['label']} ({letter(record, '')})",
                        f"    cause: {record_cause(record)}"] + item_lines(record)
    return "\n".join(["ALL DEVELOPMENT VARIANTS (scripts/run_all_dev.py)", "", *table, "",
                      "Letters: A Applicable, A* Applicable with invalid requirement, I Indeterminate, N Not "
                      "applicable, X Irrelevant, S Split invalid, D No duty, F failed step, - not retrieved, ? run missing", "",
                      "NON-APPLICABLE TARGETS", *(details or ["(none)"])]) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Summarise the run_all_dev.py folders.")
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    config = load_config()
    text = summarise(config, [v.strip() for v in args.variants.split(",") if v.strip()], args.runs)
    (project_path(config["paths"]["runs"]).parent / "debug" / "all_dev_summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
