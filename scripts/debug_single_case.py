"""Debug runner for ONE case (variant 01.1): every stage of the current frozen RAG v2 + C3 v2 pipeline as JSON.

It changes nothing in the pipeline. Retrieval is READ from the frozen file (config.yaml rag_v2.frozen_retrieval; its
SHA-256 must equal rag_v2.frozen_manifest), exactly as C2 and C3 read it. Mediation calls OrchestratorV2.mediate_passage
for each of the 5 frozen passages, with the same agents, prompts and settings as a C3 run and as src/mediation_test.py
(setting R = the frozen top 5). No BPMN is generated.

Files in results/debug/01.1/run_<n>/ (a new run folder every time; nothing is overwritten):
  00_run_info.json                    model, digest, Ollama version, frozen-file checksum, answer key
  01_query.json                       the description and the queries sent to the retrievers and the reranker
  02_top20_before_rerank.json         the hybrid top 20 (BM25 + dense, RRF) in hybrid order, with fused scores
  03_top5_after_rerank.json           the 5 passages after the cross-encoder, with rerank scores and texts
  04_relevance.json                   RelevanceAgentV2 output + code quote check, per passage
  05_applicability.json               ApplicabilityAgentV2: split, every IF item / role fact / exception with status,
                                      quote, quote_found, decided_by (second-look items also keep first_look_status)
  06_resolver.json                    ResolverV2 decision per passage (label, reason, exceptions applying)
  07_second_look.json                 the second-look answer and what it changed (null where it did not run)
  08_final_requirement.json           RequirementAgentV2 output + code check, and the final knowledge block
  09_audit_trail_full.json            the unchanged OrchestratorV2 records
  summary.txt                         the printed one-page summary
Every LLM call is also logged by RunLogger in logs/ inside the run folder.

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m scripts.debug_single_case --runs 3
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config, project_path

CASE_ID = "01.1"


# ---------- retrieval stages (read from the frozen file, nothing is retrieved again) ----------

def load_frozen_case(config: dict, case_id: str = CASE_ID) -> tuple[dict, str]:
    """The frozen RAG v2 result of one case and the file's SHA-256 (must equal the frozen manifest)."""
    import hashlib
    path = project_path(config["rag_v2"]["frozen_retrieval"])
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads(project_path(config["rag_v2"]["frozen_manifest"]).read_text(encoding="utf-8"))
    if sha != manifest["sha256"]:
        raise RuntimeError(f"{path} differs from its manifest (frozen file changed): {sha} != {manifest['sha256']}")
    return json.loads(path.read_text(encoding="utf-8"))["cases"][case_id], sha


def load_answer_key(config: dict, case_id: str = CASE_ID) -> dict:
    variant = json.loads((project_path(config["paths"]["cases"]) / case_id / "variant.json").read_text(encoding="utf-8"))
    return {"target_passage_id": variant["target_passage_id"],
            "accepted_target_ids": variant.get("accepted_target_ids") or [variant["target_passage_id"]],
            "expected_step": variant["expected_step"]}


def retrieval_stages(case: dict, description: str, key: dict) -> dict:
    """Files 01-03 as dicts. Candidates are listed in hybrid order (before reranking); each row also says where the
    reranker put it. The list is the 'candidates' of the frozen file, which is in reranker order."""
    accepted = set(key["accepted_target_ids"])
    rerank_order = {c["passage_id"]: i for i, c in enumerate(case["candidates"], 1)}
    before = sorted((c for c in case["candidates"] if c["hybrid_rank"] is not None), key=lambda c: c["hybrid_rank"])
    top20 = [{"hybrid_rank": c["hybrid_rank"], "passage_id": c["passage_id"], "fused_score": c["fused_score"],
              "rerank_rank_among_candidates": rerank_order[c["passage_id"]], "rerank_score": c["rerank_score"],
              "is_target": c["passage_id"] in accepted} for c in before]
    top5 = [{"rank": p["rank"], "passage_id": p["passage_id"], "rerank_score": p["rerank_score"],
             "hybrid_rank": p["hybrid_rank"], "is_target": p["passage_id"] in accepted, "text": p["text"]}
            for p in case["passages"]]
    return {"01_query.json": {"case_id": CASE_ID, "description": description, "queries": case["queries"],
                              "reranker_queries": case["reranker_queries"]},
            "02_top20_before_rerank.json": {"note": "hybrid retrieval (BM25 + dense, RRF k 60), before the reranker",
                                            "target": key["accepted_target_ids"], "candidates": top20},
            "03_top5_after_rerank.json": {"note": "best 5 by cross-encoder score (the frozen top 5, given to C2/C3)",
                                          "target": key["accepted_target_ids"], "passages": top5}}


# ---------- mediation stages (from the unchanged OrchestratorV2 records) ----------

def mediation_stages(records: list[dict], knowledge_block: str) -> dict:
    """Files 04-09 as dicts, one entry per passage in rank order."""
    def per_passage(pick):
        return [{"rank": r["rank"], "passage_id": r["passage_id"], **pick(r)} for r in records]

    def applicability(r):
        a = r["applicability"]
        if a is None:
            return {"applicability": None, "failed_step": r["failed_step"]}
        return {"applicability": {k: a[k] for k in a if k != "second_look"}, "failed_step": r["failed_step"]}

    def second_look(r):
        a = r["applicability"] or {}
        if not a.get("second_look"):
            return {"second_look": None}
        changed = [{"id": c["id"], "text": c["text"], "first_look_status": c.get("first_look_status"),
                    "second_look_status": c["status"], "quote": c.get("quote"), "quote_found": c.get("quote_found")}
                   for c in a["conditions"] if "first_look_status" in c]
        return {"second_look": {"answer": a["second_look"], "items": changed, "first_look_label": a["first_look_label"],
                                "label_after": a["label"], "decided": a["second_look_decided"]}}

    return {
        "04_relevance.json": per_passage(lambda r: {"relevance": r["relevance"], "failed_step": r["failed_step"]}),
        "05_applicability.json": per_passage(applicability),
        "06_resolver.json": per_passage(lambda r: {"resolution": r["resolution"], "final_label": r["label"],
                                                   "first_look_label": (r["applicability"] or {}).get("first_look_label")}),
        "07_second_look.json": per_passage(second_look),
        "08_final_requirement.json": {"passages": per_passage(lambda r: {"final_label": r["label"],
                                                                         "requirement": r["requirement"]}),
                                      "knowledge_block": knowledge_block},
        "09_audit_trail_full.json": records}


# ---------- one debug run ----------

def next_run_dir(case_dir: Path) -> Path:
    """results/debug/<case>/run_<n> with the next free n (an existing run folder is never reused)."""
    numbers = [int(p.name[4:]) for p in case_dir.glob("run_*") if p.name[4:].isdigit()]
    return case_dir / f"run_{max(numbers, default=0) + 1}"


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def debug_run(config: dict, case: dict, description: str, key: dict, llm, run_dir: Path, run_info: dict) -> dict:
    """Write all stage files of one run into run_dir (new folder) and return the summary data."""
    from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.agents.requirement_agent_v2 import RequirementAgentV2
    from src.logger import RunLogger
    from src.orchestrator_v2 import OrchestratorV2
    from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
    from src.study2_config import study2_view

    run_dir.mkdir(parents=True)   # raises if it exists: nothing is overwritten
    view = study2_view(config)
    logger = RunLogger(run_dir / "logs", "DEBUG", run_dir.name)
    orch = OrchestratorV2(RelevanceAgentV2(llm, logger), ApplicabilityAgentV2(llm, logger, config=view),
                          RequirementAgentV2(llm, logger), {}, run_dir / "unused",
                          load_c3_block_template(view, "c3_block_template_v2"), load_no_knowledge_text(view))
    passages = sorted(case["passages"], key=lambda p: p["rank"])
    started = datetime.now(timezone.utc)
    records = []
    for p in passages:
        record = orch.mediate_passage(CASE_ID, description, p, passages)
        records.append(record)
        print(f"  {run_dir.name} rank {p['rank']} {p['passage_id']}: {record['label']}", flush=True)
    block = orch.knowledge_block(records)

    files = retrieval_stages(case, description, key) | mediation_stages(records, block)
    files = {"00_run_info.json": run_info | {"run": run_dir.name, "started_at": started.isoformat(timespec="seconds"),
                                             "answer_key": key}} | files
    for name, data in files.items():
        write_json(run_dir / name, data)
    return {"run": run_dir.name, "records": records, "knowledge_block": block}


# ---------- summary ----------

def target_ranks(case: dict, key: dict) -> dict:
    """Where the target passage is: hybrid rank (before reranking) and reranker position among the 20 candidates and
    in the top 5. None = not in that list."""
    accepted = set(key["accepted_target_ids"])
    out = {"hybrid_top20": None, "after_rerank_among_20": None, "top5": None, "passage_id": None}
    for i, c in enumerate(case["candidates"], 1):
        if c["passage_id"] in accepted:
            out.update(passage_id=c["passage_id"], hybrid_top20=c["hybrid_rank"], after_rerank_among_20=i)
    for p in case["passages"]:
        if p["passage_id"] in accepted:
            out.update(passage_id=p["passage_id"], top5=p["rank"])
    return out


def final_status(record: dict) -> str:
    a = record["applicability"] or {}
    text = record["label"] or "?"
    if record["failed_step"]:
        text += f" (failed at {record['failed_step']})"
    elif a.get("second_look"):
        text += f" [first look {a['first_look_label']}, second look -> {a['label']}]"
    req = record["requirement"]
    if req is not None:
        text += " + requirement" + (" INVALID" if req["requirement_invalid"] else "")
    return text


def summary_text(key: dict, ranks: dict, runs: list[dict], case: dict) -> str:
    def where(value):
        return f"rank {value}" if value else "NOT present"
    lines = [f"DEBUG SUMMARY, case {CASE_ID}, frozen RAG v2 + C3 v2",
             f"Answer key: target {', '.join(key['accepted_target_ids'])}; expected step \"{key['expected_step']}\"", "",
             "Target passage:",
             f"  in the hybrid top 20 (before reranking): {where(ranks['hybrid_top20'])}"
             + ("" if ranks["hybrid_top20"] else "  -> retrieval never reaches it; mediation cannot help"),
             f"  position among the 20 after reranking:   {where(ranks['after_rerank_among_20'])}",
             f"  in the top 5 after reranking:            {where(ranks['top5'])}", "",
             "Frozen top 5 (rank, passage, rerank score, hybrid rank):"]
    lines += [f"  {p['rank']}. {p['passage_id']:<14} {p['rerank_score']:>7.3f}  hybrid #{p['hybrid_rank']}"
              + ("   <- TARGET" if p["passage_id"] in key["accepted_target_ids"] else "") for p in case["passages"]]
    lines += ["", "Final status per passage:"]
    for run in runs:
        lines.append(f"  {run['run']}:")
        lines += [f"    {r['rank']}. {r['passage_id']:<14} {final_status(r)}" for r in run["records"]]
        lines.append("    block: " + ("(none, C1 text)" if run["knowledge_block"].startswith("No domain")
                                      else run["knowledge_block"].replace("\n", " | ")[:200]))
    if len(runs) > 1:
        labels = [tuple(r["label"] for r in run["records"]) for run in runs]
        lines += ["", "Labels identical in all runs: " + ("yes" if len(set(labels)) == 1 else "NO, they differ")]
    return "\n".join(lines) + "\n"


# ---------- entry point ----------

def make_llm(config: dict) -> tuple:
    """The C3 agents' Ollama client with the same digest check as a study run; returns (client, run-info part)."""
    from run_experiment import create_llm, ollama_settings
    from src.study2_config import study2_view

    view = study2_view(config)
    settings = ollama_settings(view)   # stops (ValueError) if the model digest or server settings differ
    expected = str(config["study2_gdpr"]["ollama_version"])
    if settings.get("ollama_version") != expected:
        print(f"WARNING: Ollama is {settings.get('ollama_version')!r}, study2_gdpr.ollama_version is {expected!r}")
    info = {"model": view["model"]["name"], "model_digest": settings["generator_digest"],
            "ollama_version": settings["ollama_version"]}
    return create_llm(view, "relevance", {}), info


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Debug runner for variant {CASE_ID} (frozen RAG v2 + C3 v2).")
    parser.add_argument("--runs", type=int, default=1, help="how many separate runs to make (default 1)")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    config = load_config()
    case, sha = load_frozen_case(config)
    key = load_answer_key(config)
    description = (project_path(config["paths"]["cases"]) / CASE_ID / config["paths"]["case_description_file"]
                   ).read_text(encoding="utf-8")
    try:
        llm, llm_info = make_llm(config)
    except Exception as e:
        sys.exit(f"Not started: {e}")
    run_info = {"case_id": CASE_ID, "frozen_retrieval": config["rag_v2"]["frozen_retrieval"], "frozen_sha256": sha,
                "c3_version": "v2", "c3_block_template": "prompts/c3_block_template_v2.json", **llm_info}

    case_dir = project_path(config["paths"]["runs"]).parent / "debug" / CASE_ID
    runs = []
    for _ in range(args.runs):
        run_dir = next_run_dir(case_dir)
        print(f"{run_dir} ...")
        runs.append(debug_run(config, case, description, key, llm, run_dir, run_info))
    text = summary_text(key, target_ranks(case, key), runs, case)
    for run in runs:
        (case_dir / run["run"] / "summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
