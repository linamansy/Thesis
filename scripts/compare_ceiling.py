"""Ceiling test report (NO LLM): the target's oracle label with qwen3:8b (med_alldev_oracle_run_<n>) next to the label
with the Groq model of scripts/run_all_dev.py --groq-model (med_ceiling_<model>_run_<n>), for every development variant.

Then, for every variant where the two labels differ or neither is A (Applicable with a valid requirement): the cause
of each label and every IF item side by side, matched by item id (role, scope, role facts, situations, exceptions):
id, kind, status qwen -> status strong, the item text (both if they differ), quotes and verifier reason of each model.
Item ids come from each model's own split, so the same id can name different texts; the texts are shown to check.

Output: printed and written to results/debug/ceiling_<model>_comparison.txt.
    .venv\\Scripts\\python.exe -m scripts.compare_ceiling --groq-model qwen/qwen3.8-27b
"""

import argparse
import json

from scripts.debug_single_case import load_answer_key
from scripts.run_all_dev import ORACLE_LABEL, VARIANTS, ceiling_label, med_dir
from scripts.summarise_all_dev import item_stage, letter, record_cause, target_record
from src.config import load_config, project_path


def items_by_id(record: dict | None) -> dict:
    """id -> (item, is_exception) for every IF item of the record, in split order."""
    a = (record or {}).get("applicability") or {}
    groups = [(a.get("conditions") or [], False), (a.get("role_facts") or [], False), (a.get("exceptions") or [], True)]
    return {item["id"]: (item, is_exception) for items, is_exception in groups for item in items}


def side(item: dict | None, is_exception: bool) -> dict:
    if item is None:
        return {"status": "(no item)", "text": None, "quotes": "-", "verifier": "-", "stage": "-"}
    quotes = item.get("quotes_canonical") or item.get("quotes") or []
    return {"status": item.get("status"), "text": item.get("text_sent") or item.get("text"),
            "quotes": json.dumps(quotes, ensure_ascii=False) if quotes else "-",
            "verifier": (item.get("verifier") or {}).get("reason") or "-", "stage": item_stage(item, is_exception)}


def item_lines(weak: dict | None, strong: dict | None) -> list[str]:
    a, b = items_by_id(weak), items_by_id(strong)
    lines = []
    for item_id in list(a) + [i for i in b if i not in a]:
        ia, ea = a.get(item_id, (None, False))
        ib, eb = b.get(item_id, (None, False))
        sa, sb = side(ia, ea), side(ib, eb)
        kind = (ia or ib).get("kind") or "exception"
        lines.append(f"      {item_id:<3} {kind:<10} {sa['status']} -> {sb['status']}")
        if sa["text"] == sb["text"]:
            lines.append(f"          text:            {sa['text']}")
        else:
            lines += [f"          text qwen:       {sa['text'] or '-'}", f"          text strong:     {sb['text'] or '-'}"]
        lines += [f"          quotes qwen:     {sa['quotes']}", f"          quotes strong:   {sb['quotes']}",
                  f"          verifier qwen:   {sa['verifier']}", f"          verifier strong: {sb['verifier']}",
                  f"          stage qwen / strong: {sa['stage']} / {sb['stage']}"]
    return lines


def compare(config: dict, model: str, variants, n: int = 1) -> str:
    debug = project_path(config["paths"]["runs"]).parent / "debug"
    label = ceiling_label(model)
    header = f"{'variant':<8}{'target':<16}{'qwen3:8b oracle':<18}{model + ' oracle':<28}"
    table, details = [header, "-" * len(header)], []
    for variant in variants:
        target = load_answer_key(config, variant)["target_passage_id"]
        weak = target_record(med_dir(debug / variant, ORACLE_LABEL, n), target)
        strong = target_record(med_dir(debug / variant, label, n), target)
        lw, ls = letter(weak, "?"), letter(strong, "?")
        table.append(f"{variant:<8}{target:<16}{lw:<18}{ls:<28}")
        if lw == ls == "A":
            continue
        details.append(f"{variant} {target}: qwen3:8b {lw} -> {model} {ls}")
        for name, record in (("qwen", weak), ("strong", strong)):
            details.append(f"    cause {name}: {record_cause(record) if record else 'run missing'}")
            req = (record or {}).get("requirement") or {}
            if req.get("requirement"):
                details.append(f"    requirement {name}: {req['requirement']}")
        details += item_lines(weak, strong)
    return "\n".join([f"CEILING TEST: oracle run {n}, qwen3:8b (alldev, think on CheckIf/SecondLook/Verifier) vs "
                      f"{model} on Groq (all C3 calls, json_schema, no thinking)", "", *table, "",
                      "Letters: A Applicable, A* Applicable with invalid requirement, I Indeterminate, N Not "
                      "applicable, X Irrelevant, S Split invalid, F failed step, ? run missing", "",
                      "VARIANTS WHERE THE LABELS DIFFER OR NEITHER IS A", *(details or ["(none)"])]) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare the qwen3:8b oracle with the Groq ceiling oracle.")
    parser.add_argument("--groq-model", required=True)
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args(argv)
    config = load_config()
    text = compare(config, args.groq_model, [v.strip() for v in args.variants.split(",") if v.strip()], args.run)
    out = project_path(config["paths"]["runs"]).parent / "debug" / f"{ceiling_label(args.groq_model)}_comparison.txt"
    out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
