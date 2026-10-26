"""C3 v2 round 1 fixes: agent-only evaluation against the criteria of docs/C3_V2_DEVELOPMENT.md section 7.

Real agent calls only (qwen3:8b on Ollama, the agents' settings in config.yaml), NO BPMN generation. Ollama must be
study2_gdpr.ollama_version and the model digest model.ollama_model_digest, otherwise nothing starts.

Passage sets (development and variant cases only; test cases are refused):
  gdpr_dev       study2_gdpr.development_ids (7)   study2_gdpr.frozen_retrieval (rerank top 5)
  variant_01.1   01.1                              study2_gdpr.frozen_variants_rerank (frozen top 5)
  oracle_01.1    01.1                              study2_gdpr.oracle_top5 (frozen top 5, rank 5 -> GDPR-Art13-1)

For every passage, OrchestratorV2.mediate_passage runs the four boxes as in C3 v2 (relevance -> split -> check-IF ->
second look -> resolver -> requirement for Applicable rules). A passage marked irrelevant gets no applicability call in
the pipeline; for the split criteria (1-3, "count over all passages") its split call is made on its own (the split
sees the law text only, so it does not depend on the case).

Writes only into paths.c3_v2_round<n>_dir (n = --round, default 1; round 2 = section 8 prompts, same passages):
  answers.json   one record per passage (the audit-trail record, plus split_only for irrelevant passages); written
                 after every case, a rerun skips finished cases
  logs/          every LLM call (RunLogger)
  metrics.json   the counts for each section 7 criterion
  report.md      the same as tables, with every split and every requirement text (criteria 3, 4 and 7 are judged by
                 reading them)

Run from the project root (Ollama running):  .venv\\Scripts\\python.exe -m src.c3_v2_round1_eval [--round 2]
"""

import json
import re
import sys
from pathlib import Path

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.config import load_config, project_path
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
from src.study2_config import study2_view

LOG_CONDITION = "C3V2_ROUND{n}"   # n = the round
ROLE_PATTERN = re.compile(r"\b(acts? as|organisation)\b", re.IGNORECASE)   # IF item written as a role (criterion 3)


def passage_sets(config: dict) -> list[dict]:
    gdpr = config["study2_gdpr"]
    sets = [{"name": "gdpr_dev", "frozen": gdpr["frozen_retrieval"], "case_ids": list(gdpr["development_ids"])},
            {"name": "variant_01.1", "frozen": gdpr["frozen_variants_rerank"], "case_ids": ["01.1"]},
            {"name": "oracle_01.1", "frozen": gdpr["oracle_top5"], "case_ids": ["01.1"]}]
    for s in sets:
        test_cases = [c for c in s["case_ids"] if c in config["cases"]["test_ids"]]
        if test_cases:
            raise ValueError(f"test cases are never used in C3 v2 development: {test_cases}")
    return sets


def split_of(record: dict) -> dict | None:
    """The split answer of a passage: from the pipeline, or from the split-only call for an irrelevant passage."""
    if record["applicability"] and record["applicability"]["split"]:
        return record["applicability"]["split"]
    return record.get("split_only")


def log_calls(log_dir: Path) -> dict:
    """Criterion 8 from the log: one agent call = one record with retries 0; a failed call = an invalid last attempt."""
    records = [json.loads(line) for path in sorted(log_dir.glob("*.jsonl"))
               for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    max_retries = max((r["retries"] for r in records), default=0)
    calls = sum(r["retries"] == 0 for r in records)
    retried = sum(r["retries"] == 1 for r in records)
    failed = sum(not r["valid_json"] and r["retries"] == max_retries and max_retries > 0 for r in records)
    return {"calls": calls, "calls_with_retry": retried, "calls_failed_after_retry": failed,
            "max_retries_seen": max_retries, "valid_share": round((calls - failed) / calls, 4) if calls else None}


def metrics(records: list[dict], obligation_pattern, log: dict, limits: dict) -> dict:
    """limits: config.yaml c3_v2.requirement_checks."""
    splits = [(r, split_of(r)) for r in records]
    usable = [r for r, s in splits if s and s["if"] and s["then"].strip()
              and not any(obligation_pattern.search(c) for c in s["if"])]
    if_items = [c for _, s in splits if s for c in s["if"]]
    obligation_items = [c for c in if_items if obligation_pattern.search(c)]
    requirements = [r for r in records if r["label"] == APPLICABLE]
    written = [r for r in requirements if r["requirement"]]
    invalid = [r for r in written if r["requirement"]["requirement_invalid"]]
    final = [r["requirement"]["attempts"][-1] for r in written]
    return {
        "passages": len(records), "unique_passage_ids": len({r["passage_id"] for r in records}),
        "c1_usable_split": len(usable), "c1_share": round(len(usable) / len(records), 4) if records else None,
        "split_failed_json": sum(s is None for _, s in splits),
        "split_empty_if": sum(bool(s) and not s["if"] for _, s in splits),
        "c2_if_items": len(if_items), "c2_if_items_with_obligation_word": len(obligation_items),
        "c3_if_items_in_role_form": sum(bool(ROLE_PATTERN.search(c)) for c in if_items),
        "applicable": len(requirements), "requirements_written": len(written),
        "requirement_invalid": len(invalid), "requirements_passed_on": len(written) - len(invalid),
        "requirements_needing_check_retry": sum(len(r["requirement"]["attempts"]) > 1 for r in written),
        "c4_over_word_limit": sum(a["measures"]["n_words"] > limits["max_words"] for a in final),
        "c4_over_sentence_limit": sum(a["measures"]["n_sentences"] > limits["max_sentences"] for a in final),
        "c5_banned_word": sum(bool(a["measures"]["banned_found"]) for a in final),
        "c6_copied_over_limit": sum(a["measures"]["copied_share"] > limits["max_copied_share"] for a in final),
        "c8_log": log}


def report(m: dict, records: list[dict], round_no: int = 1) -> str:
    sections = "section 7" if round_no == 1 else "sections 7 and 8"
    lines = [f"# C3 v2 round {round_no}: agent-only evaluation ({sections})", "",
             "Real calls (qwen3:8b, Ollama), no BPMN generation. Criteria 3, 4 (plain language, names the step) and 7 "
             "are judged by reading the texts below.", "", "## Counts", "", "| measure | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in m.items() if k != "c8_log"]
    lines += [f"| c8 {k} | {v} |" for k, v in m["c8_log"].items()]
    lines += ["", "## Every split", "", "| set | case | rank | passage | relevant | label | IF | THEN |", "|---|---|---|---|---|---|---|---|"]
    for r in records:
        s = split_of(r)
        rel = r["relevance"]["final_relevant"] if r["relevance"] else None
        if_text = "; ".join(s["if"]) if s else "(no valid split)"
        then = s["then"] if s else ""
        lines.append(f"| {r['set']} | {r['case_id']} | {r['rank']} | {r['passage_id']} | {rel} | {r['label']} | "
                     f"{if_text} | {then} |".replace("\n", " "))
    lines += ["", "## Every requirement", ""]
    for r in records:
        if r["label"] == APPLICABLE:
            lines.append(f"### {r['set']} / {r['case_id']} / {r['passage_id']}")
            lines.append(f"- process step: {r['relevance']['process_step']}")
            if not r["requirement"]:
                lines.append("- no valid answer")
                continue
            for i, a in enumerate(r["requirement"]["attempts"], 1):
                lines.append(f"- attempt {i}: \"{a['requirement']}\" — {a['measures']} — problems: {a['problems'] or 'none'}")
            lines.append(f"- requirement_invalid: {r['requirement']['requirement_invalid']}")
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    from run_experiment import create_llm, ollama_settings
    round_no = int(sys.argv[sys.argv.index("--round") + 1]) if "--round" in sys.argv else 1
    config = load_config()
    view = study2_view(config)
    out_dir = project_path(config["paths"][f"c3_v2_round{round_no}_dir"])
    try:
        sets = passage_sets(config)
        settings = ollama_settings(view)    # model digest = model.ollama_model_digest, server settings
        expected = str(config["study2_gdpr"]["ollama_version"])
        if settings.get("ollama_version") != expected:
            raise ValueError(f"Ollama is {settings.get('ollama_version')!r}, study2_gdpr.ollama_version is {expected!r}")
        llm = create_llm(view, "relevance", {})
    except (ValueError, FileNotFoundError, LLMUnavailableError) as e:
        sys.exit(f"Not started: {e}")

    log_dir = out_dir / "logs"
    condition = LOG_CONDITION.format(n=round_no)
    logger = RunLogger(log_dir, condition, f"round{round_no}", part=1 + len(list(log_dir.glob(f"{condition}_*.jsonl"))))
    applicability = ApplicabilityAgentV2(llm, logger, config=view)
    answers_path = out_dir / "answers.json"
    records = json.loads(answers_path.read_text(encoding="utf-8")) if answers_path.exists() else []
    done = {(r["set"], r["case_id"]) for r in records}
    cases_dir = project_path(config["paths"]["cases"])
    for s in sets:
        frozen = json.loads(project_path(s["frozen"]).read_text(encoding="utf-8"))["cases"]
        orch = OrchestratorV2(RelevanceAgentV2(llm, logger), applicability, RequirementAgentV2(llm, logger), frozen,
                              out_dir / "unused", load_c3_block_template(view, "c3_block_template_v2"),
                              load_no_knowledge_text(view))
        for case_id in s["case_ids"]:
            if (s["name"], case_id) in done:
                continue
            description = (cases_dir / case_id / config["paths"]["case_description_file"]).read_text(encoding="utf-8")
            passages = sorted(frozen[case_id]["passages"], key=lambda p: p["rank"])
            for p in passages:
                record = orch.mediate_passage(case_id, description, p, passages)
                if record["applicability"] is None and record["relevance"] is not None:
                    split = applicability.split_call.run(case_id, passage_id=p["passage_id"], passage_text=p["text"])
                    record["split_only"] = split.model_dump(by_alias=True) if split else None
                records.append({"set": s["name"], "case_id": case_id} | record)
                print(f"{s['name']} {case_id} rank {p['rank']} {p['passage_id']}: {record['label']}")
            out_dir.mkdir(parents=True, exist_ok=True)
            answers_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    m = metrics(records, applicability.obligation_pattern, log_calls(log_dir),
                config["c3_v2"]["requirement_checks"])
    m["ollama_version"], m["model_digest"] = settings["ollama_version"], settings["generator_digest"]
    (out_dir / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(report(m, records, round_no), encoding="utf-8")
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
