"""Freeze the step-routing retrieval (SR, src/rag_v3_steps.py) ONCE for a list of case / variant ids (Study 2).

SR uses the model (StepsAgent lists the steps, RoutingAgent picks the articles), so it is NOT run inside the experiment:
this script runs it once, before any generation, and saves the result. src/run_study2.py (C2 and C3) only reads it,
exactly like Study 1's C2 and C3 read data/retrieval/frozen_retrieval.json.

Settings: StepRouter with config.yaml study2_run.sr_options (two-view routing, CombMAX, parent expansion: the setting
of scripts/run_all_dev.py), the Study 2 corpus (study2_corpus.passages, its SHA-256 must equal study2_corpus.manifest),
the RAG v2 retrievers and reranker, and the C3 agents' model and settings (model + llm).

Refused before anything is loaded: an id of a held-out variant (mediation_test.held_out_variants), an id without a
case folder, a repeated id, and an existing frozen file or manifest (never overwritten). The frozen file is not
written if any case ends with 0 passages (the cases and their S1/S2 failure are listed; the stages stay saved).

Written (--frozen PATH replaces study2_run.frozen_retrieval, the manifest is then PATH with _manifest.json; a smoke
freeze uses study2_run.smoke_frozen_retrieval, so it never touches the real frozen file):
  study2_run.frozen_retrieval   {"created_at", "method", "case_ids", "cases": {id: {"passages": [{rank, passage_id,
                                text}]}}}, the layout of the existing frozen files (ExperimentRunner reads "cases")
  study2_run.frozen_manifest    SHA-256 of the frozen file, corpus file + SHA-256, model, digest, Ollama version, agent
                                and SR settings, reranker, prompt checksums, date
  study2_run.freeze_output_dir/<UTC time>/<case>.json   all four SR stages (S1-S4) of the case
  study2_run.freeze_output_dir/<UTC time>/logs/          every LLM call (RunLogger)

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m src.freeze_sr --ids 01.1,01.2,06.1,11.1,13.1,17.1,19.1,45.1 [--fresh] [--frozen PATH]
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_config, project_path
from src.freeze_retrieval import save, sha256_of_file
from src.logger import RunLogger
from src.rag_v3_steps import ROUTING_PROMPT, STEPS_PROMPT


def held_out_ids(config: dict) -> set[str]:
    """Every held-out variant id (all groups of mediation_test.held_out_variants)."""
    return {i for group in config["mediation_test"]["held_out_variants"].values() for i in group}


def frozen_paths(config: dict, frozen: str | None = None) -> tuple[Path, Path]:
    """(frozen file, manifest): study2_run.frozen_retrieval / frozen_manifest, or frozen and frozen with _manifest.json."""
    if not frozen:
        return project_path(config["study2_run"]["frozen_retrieval"]), project_path(config["study2_run"]["frozen_manifest"])
    path = project_path(frozen)
    return path, path.with_name(f"{path.stem}_manifest.json")


def check_ids(config: dict, ids: list[str]) -> None:
    """Raise ValueError for a held-out id, a repeated id or an id without a case description."""
    if not ids:
        raise ValueError("no case ids given")
    held_out = sorted(set(ids) & held_out_ids(config))
    if held_out:
        raise ValueError(f"held-out variant ids are never retrieved or run: {held_out}")
    if len(set(ids)) != len(ids):
        raise ValueError(f"repeated ids: {ids}")
    cases = project_path(config["paths"]["cases"])
    missing = [i for i in ids if not (cases / i / config["paths"]["case_description_file"]).exists()]
    if missing:
        raise ValueError(f"no case description for: {missing}")


def description_of(config: dict, case_id: str) -> str:
    return (project_path(config["paths"]["cases"]) / case_id / config["paths"]["case_description_file"]
            ).read_text(encoding="utf-8")


def frozen_passages(s4: dict) -> list[dict]:
    """The final S4 set in the frozen layout: rank, passage_id, text."""
    return [{"rank": p["rank"], "passage_id": p["passage_id"], "text": p["text"]} for p in s4["passages"]]


def empty_reason(stages: dict) -> str:
    """Why a case has no passages: what went wrong in S1 (steps) and S2 (routing)."""
    s1, s2 = stages["S1"], stages["S2"]
    per_step = s2.get("per_step", {})
    return (f"S1 failed={s1['failed']}, steps kept={len(s1['steps'])}, dropped={len(s1['dropped'])}; "
            f"S2 steps failed={sum(bool(v['failed']) for v in per_step.values())}, "
            f"steps with a route={sum(bool(v['routes']) for v in per_step.values())}/{len(per_step)}")


def freeze(config: dict, ids: list[str], router_factory, stages_dir: Path, before_case=None) -> dict:
    """Run SR once per id and return the frozen file's content. router_factory(logger) -> StepRouter.
    Every case's S1-S4 stages are written to stages_dir/<id>.json, the LLM calls to stages_dir/logs/.
    before_case(): called before every case (--fresh: unload the model).
    Raises ValueError (after all cases) if any case has 0 passages: nothing may be frozen then."""
    stages_dir.mkdir(parents=True)   # raises if it exists: nothing is overwritten
    router = router_factory(RunLogger(stages_dir / "logs", config["study2_run"]["freeze_log_condition"],
                                      stages_dir.name))
    cases, empty = {}, {}
    for case_id in ids:
        if before_case:
            before_case()
        stages = router.run(case_id, description_of(config, case_id))
        (stages_dir / f"{case_id}.json").write_text(json.dumps(stages, indent=2, ensure_ascii=False) + "\n",
                                                    encoding="utf-8")
        cases[case_id] = {"passages": frozen_passages(stages["S4"])}
        if not cases[case_id]["passages"]:
            empty[case_id] = empty_reason(stages)
        print(f"{case_id:<6}{' '.join(p['passage_id'] for p in cases[case_id]['passages'])}", flush=True)
    if empty:
        raise ValueError(f"cases with 0 passages, frozen file not written: {empty}")
    return {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": "RAG step routing (SR), src/rag_v3_steps.py, study2_run.sr_options; frozen by src/freeze_sr.py",
            "case_ids": ids, "cases": cases}


def manifest(config: dict, frozen: dict, frozen_path: Path, stages_dir: Path, llm_info: dict, reranker,
             fresh: bool) -> dict:
    corpus = project_path(config["study2_corpus"]["passages"])
    return {"description": "Frozen SR retrieval (src/freeze_sr.py); never changed after freezing.",
            "file": str(frozen_path), "sha256": sha256_of_file(frozen_path), "created_at": frozen["created_at"],
            "case_ids": frozen["case_ids"],
            "corpus_file": config["study2_corpus"]["passages"], "corpus_sha256": sha256_of_file(corpus),
            **llm_info, "agent_settings": config["llm"], "sr_options": config["study2_run"]["sr_options"],
            "rrf_k": config["retrieval"]["rrf_k"], "dense_model": config["retrieval"]["dense_model"],
            "reranker": {"model": reranker.model_name, "revision": reranker.revision,
                         "candidates": config["reranker"]["candidates"], "top_k": config["reranker"]["top_k"]},
            "prompt_sha256": {p: sha256_of_file(project_path(p)) for p in (STEPS_PROMPT, ROUTING_PROMPT)},
            "fresh": fresh, "stages_dir": str(stages_dir)}


def check_corpus(config: dict) -> None:
    corpus_sha = sha256_of_file(project_path(config["study2_corpus"]["passages"]))
    expected = json.loads(project_path(config["study2_corpus"]["manifest"]).read_text(encoding="utf-8"))
    if corpus_sha != expected["passages_sha256"]:
        raise RuntimeError(f"Study 2 corpus changed: {corpus_sha} != manifest {expected['passages_sha256']}")


def main(argv: list[str] | None = None) -> None:
    from scripts.debug_single_case import add_fresh_option, make_llm, unload_model
    from src.rag_v3_steps import RoutingAgent, StepRouter, StepsAgent, build_retrievers

    parser = argparse.ArgumentParser(description="Run step-routing retrieval once and freeze it.")
    parser.add_argument("--ids", required=True, help="comma-separated case / variant ids")
    add_fresh_option(parser)
    parser.add_argument("--frozen", help="frozen file to write (default study2_run.frozen_retrieval; manifest = same "
                                         "name with _manifest.json)")
    args = parser.parse_args(argv)
    config = load_config()
    run = config["study2_run"]
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    out_path, manifest_path = frozen_paths(config, args.frozen)
    try:
        check_ids(config, ids)
        if out_path.exists() or manifest_path.exists():   # checked before the slow work
            raise FileExistsError(f"Refusing to overwrite {out_path} / {manifest_path}.")
        check_corpus(config)
        llm, llm_info = make_llm(config)
    except (ValueError, FileExistsError, RuntimeError) as e:
        sys.exit(f"Not started: {e}")
    passages, dense, sparse, reranker = build_retrievers(config)

    def router_factory(logger):
        return StepRouter(config, StepsAgent(llm, logger), RoutingAgent(llm, logger), passages, dense, sparse,
                          reranker, **run["sr_options"])

    stages_dir = project_path(run["freeze_output_dir"]) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        frozen = freeze(config, ids, router_factory, stages_dir,
                        (lambda: unload_model(config)) if args.fresh else None)
    except ValueError as e:
        sys.exit(f"Not saved: {e}")
    save(frozen, out_path, force=False)
    save(manifest(config, frozen, out_path, stages_dir, llm_info, reranker, args.fresh), manifest_path, force=False)
    print(f"Saved {out_path}\nsha256 {hashlib.sha256(out_path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
