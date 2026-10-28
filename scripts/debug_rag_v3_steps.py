"""Debug runner for RAG step routing (SR, src/rag_v3_steps.py) on variant 01.1. Not the exploratory RAG v3 (E/F/G).

PASS RULES (written before the first run; they are not changed after seeing a result):
  (a) A GDPR Article 13 article ("GDPR-Art13") is among the kept routes of S2 for at least one step.
  (b) The passage "GDPR-Art13-1" is in the S4 top 5.
Both are checked per run by code (check_rules). A run passes only if (a) and (b) both hold; each is reported alone too.

Files in results/debug/01.1/rag_sr_run_<n>/ (a new folder every time; nothing is overwritten):
  00_run_info.json       model name + Ollama digest + version, frozen-corpus checksum, pass rules, answer key
  01_steps.json          S1: the model's steps, the kept steps, the dropped steps (quote not found)
  02_routes.json         S2: per step the model's routes, the kept routes (id, title, reason), the dropped ones
  03_step_rankings.json  S3: per step the reranked paragraphs of its routed articles
  04_merged_top5.json    S4: the RRF merge of the steps' lists, top 5, with texts
  05_pass_rules.json     (a), (b) and the rank of GDPR-Art13-1 in each step list and in the merged list
  logs/                  every LLM call (RunLogger)
  summary.txt            the printed summary

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m scripts.debug_rag_v3_steps --runs 3
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from scripts.debug_single_case import CASE_ID, load_answer_key, make_llm, write_json
from src.config import load_config, project_path
from src.rag_v3_steps import RoutingAgent, StepRouter, StepsAgent, build_retrievers, merge_rankings

RULE_A_ARTICLE = "GDPR-Art13"
RULE_B_PASSAGE = "GDPR-Art13-1"
RUN_PREFIX = "rag_sr_run_"


def next_run_dir(case_dir: Path) -> Path:
    numbers = [int(p.name[len(RUN_PREFIX):]) for p in case_dir.glob(f"{RUN_PREFIX}*") if p.name[len(RUN_PREFIX):].isdigit()]
    return case_dir / f"{RUN_PREFIX}{max(numbers, default=0) + 1}"


def check_rules(stages: dict, rrf_k: int) -> dict:
    """The pass rules (a) and (b) and the rank of RULE_B_PASSAGE in every step list (S3) and in the merged list (S4)."""
    routed = {step: [r["article_id"] for r in v["routes"]] for step, v in stages["S2"]["per_step"].items()}
    rule_a_steps = [step for step, ids in routed.items() if RULE_A_ARTICLE in ids]
    s3 = stages["S3"]["per_step"]
    in_step = {step: next((r["rank"] for r in v["ranking"] if r["passage_id"] == RULE_B_PASSAGE), None)
               for step, v in s3.items()}
    full = merge_rankings({s: [r["passage_id"] for r in v["ranking"]] for s, v in s3.items()}, rrf_k, 10 ** 6)
    merged_rank = next((row["rank"] for row in full if row["passage_id"] == RULE_B_PASSAGE), None)
    top5 = [row["passage_id"] for row in stages["S4"]["passages"]]
    a, b = bool(rule_a_steps), RULE_B_PASSAGE in top5
    return {"rule_a_article": RULE_A_ARTICLE, "rule_a_pass": a, "rule_a_steps": rule_a_steps,
            "rule_b_passage": RULE_B_PASSAGE, "rule_b_pass": b, "rank_in_s3_per_step": in_step,
            "rank_in_s4_full_merge": merged_rank, "s4_top5": top5, "pass": a and b}


def summary_text(runs: list[dict], key: dict) -> str:
    lines = [f"RAG STEP ROUTING (SR) DEBUG, case {CASE_ID}",
             f"Answer key: target {key['target_passage_id']}. Rules: (a) {RULE_A_ARTICLE} routed for >= 1 step; "
             f"(b) {RULE_B_PASSAGE} in the S4 top 5."]
    for run in runs:
        s1, s2, s3, rules = run["stages"]["S1"], run["stages"]["S2"], run["stages"]["S3"], run["rules"]
        lines += ["", f"=== {run['name']} ===",
                  f"S1 steps: {len(s1['steps'])} kept, {len(s1['dropped'])} dropped" + (" (CALL FAILED)" if s1["failed"] else "")]
        lines += [f"  {s['step_id']}: [{s['actor']}] {s['activity']} | {s['data_or_object'] or '-'}" for s in s1["steps"]]
        lines += [f"  dropped {s['step_id']}: {s['dropped_because']} - \"{s['quote'][:60]}\"" for s in s1["dropped"]]
        lines.append("S2 routes per step:")
        for step, v in s2["per_step"].items():
            routes = ", ".join(f"{r['article_id']}" for r in v["routes"]) or "(none)"
            dropped = f"  [dropped: {', '.join(d['article_id'] for d in v['dropped'])}]" if v["dropped"] else ""
            lines.append(f"  {step}: {routes}{dropped}" + ("  (CALL FAILED)" if v["failed"] else ""))
        lines.append(f"S3 rank of {RULE_B_PASSAGE} per step list: "
                     + (", ".join(f"{s}={r or '-'}" for s, r in rules["rank_in_s3_per_step"].items()) or "no step ranked"))
        lines.append(f"S4 rank of {RULE_B_PASSAGE} (full merge): {rules['rank_in_s4_full_merge'] or 'not in any list'}"
                     f"; top 5: {', '.join(rules['s4_top5']) or '(empty)'}")
        lines.append(f"Rule (a) {'PASS' if rules['rule_a_pass'] else 'FAIL'}   Rule (b) "
                     f"{'PASS' if rules['rule_b_pass'] else 'FAIL'}   -> run {'PASS' if rules['pass'] else 'FAIL'}")
    lines += ["", "Runs: " + ", ".join(f"{r['name']} {'PASS' if r['rules']['pass'] else 'FAIL'}" for r in runs)
              + f"  ({sum(r['rules']['pass'] for r in runs)}/{len(runs)} pass)"]
    return "\n".join(lines) + "\n"


def run_once(config: dict, router_factory, description: str, key: dict, run_dir: Path, run_info: dict) -> dict:
    """router_factory(logger) -> StepRouter. Writes all files of one run into the new folder run_dir."""
    from src.logger import RunLogger
    run_dir.mkdir(parents=True)
    router = router_factory(RunLogger(run_dir / "logs", "SR", run_dir.name))
    stages = router.run(CASE_ID, description)
    rules = check_rules(stages, config["retrieval"]["rrf_k"])
    rules_text = {"(a)": f"{RULE_A_ARTICLE} routed for at least one step", "(b)": f"{RULE_B_PASSAGE} in the S4 top 5"}
    write_json(run_dir / "00_run_info.json", run_info | {"run": run_dir.name, "answer_key": key, "pass_rules": rules_text})
    for name, stage in (("01_steps", "S1"), ("02_routes", "S2"), ("03_step_rankings", "S3"), ("04_merged_top5", "S4")):
        write_json(run_dir / f"{name}.json", stages[stage])
    write_json(run_dir / "05_pass_rules.json", rules)
    return {"name": run_dir.name, "stages": stages, "rules": rules}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Debug runner for RAG step routing (SR), variant {CASE_ID}.")
    parser.add_argument("--runs", type=int, default=1, help="how many separate runs to make (default 1)")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    config = load_config()
    key = load_answer_key(config)
    if key["target_passage_id"] != RULE_B_PASSAGE:
        sys.exit(f"Not started: the answer key target {key['target_passage_id']} is not the rule (b) passage")
    description = (project_path(config["paths"]["cases"]) / CASE_ID / config["paths"]["case_description_file"]
                   ).read_text(encoding="utf-8")
    try:
        llm, llm_info = make_llm(config)
    except Exception as e:
        sys.exit(f"Not started: {e}")
    passages, dense, sparse, reranker = build_retrievers(config)
    corpus = project_path(config["study2_corpus"]["passages"])
    run_info = {"method": "RAG step routing (SR), src/rag_v3_steps.py (not the exploratory RAG v3)", "case_id": CASE_ID,
                "corpus_file": config["study2_corpus"]["passages"],
                "corpus_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(), "n_passages": len(passages),
                "agent_settings": config["llm"], "reranker_model": reranker.model_name,
                "reranker_revision": reranker.revision, **llm_info}

    def router_factory(logger):
        return StepRouter(config, StepsAgent(llm, logger), RoutingAgent(llm, logger), passages, dense, sparse, reranker)

    case_dir = project_path(config["paths"]["runs"]).parent / "debug" / CASE_ID
    runs = []
    for _ in range(args.runs):
        run_dir = next_run_dir(case_dir)
        print(f"{run_dir} ...", flush=True)
        runs.append(run_once(config, router_factory, description, key, run_dir, run_info))
    text = summary_text(runs, key)
    for run in runs:
        (case_dir / run["name"] / "summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
