"""Oracle experiment O2: 01.2, LPD-Art3-1 only, 3 runs (results/debug/01.2/med_o2_<label>_run_<n>).

History: settings A-D were run on commit da013b1 with a redefined item schema (setting C won and became fix C, commit
7e5680b). Since fix nodoc (29 Oct 2026) the oracle uses the REAL classes only: the agents, prompts and schemas of
src/agents/ unchanged, no patch, no redefined schema.

Input: the target passage, and as its case passages the target + ALL other paragraphs of its article from the frozen
Study 2 corpus (so the second look sees exactly what fix sameart gives it when the whole article is retrieved). Only
the target passage is mediated. Everything else is scripts.debug_single_case.debug_run's setup and files.
--think-calls (debug only, setting B): the named LLM calls of ApplicabilityAgentV2 (class names, e.g.
CheckIfCallV2,SecondLookCallV2) get their own Ollama client with think: true; its thinking text is logged as reasoning.
Every other call, the agents and config.yaml stay unchanged.
Usage (from the project folder):
    .venv/Scripts/python.exe scripts/oracle_o2.py [label, default nodoc] [--fresh] [--think-calls A,B]
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")
import scripts.debug_mediation_on_passages as med
from scripts.debug_single_case import (add_fresh_option, load_answer_key, make_llm, mediation_stages, retrieval_stages,
                                       unload_model, write_json)
from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, article_of
from src.agents.base_agent import BaseAgent
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.config import load_config, project_path
from src.llm.ollama_llm import OllamaLLM
from src.logger import RunLogger
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
from src.study2_config import study2_view

VARIANT = "01.2"
TARGET = "LPD-Art3-1"
RUNS = 3


def article_ids(config: dict, passage_id: str) -> list[str]:
    """The target first, then every other paragraph of its article, in corpus order."""
    path = project_path(config["study2_corpus"]["passages"])
    ids = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [passage_id] + [i for i in ids if i != passage_id and article_of(i) == article_of(passage_id)]


class ThinkingOllamaLLM(OllamaLLM):
    """Setting B only: the agents' Ollama client with think: true; Ollama's thinking text is kept as last_reasoning,
    so RunLogger saves it with the call."""

    def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        data = super()._send(method, path, body)
        if path == "/api/chat":
            self.last_reasoning = (data.get("message") or {}).get("thinking")
        return data


def thinking_llm(config: dict) -> ThinkingOllamaLLM:
    llm = ThinkingOllamaLLM.from_config(study2_view(config))
    llm.think = True
    return llm


def give_thinking(agent, call_names: list[str], llm) -> None:
    """The named calls of the agent (class names) send their requests through llm instead. A call whose class is a
    subclass of a named call is included (F2b, design round 2: VerifierCallV2 also names EventVerifierCallV2)."""
    calls = [c for c in vars(agent).values() if isinstance(c, BaseAgent)]

    def names(call) -> set[str]:   # its class and its base classes below BaseAgent
        return {k.__name__ for k in type(call).__mro__ if issubclass(k, BaseAgent) and k is not BaseAgent}

    known = set().union(*(names(c) for c in calls))
    unknown = sorted(set(call_names) - known)
    if unknown:
        raise ValueError(f"no such call in {type(agent).__name__}: {unknown} (has: {sorted(known)})")
    for call in calls:
        if names(call) & set(call_names):
            call.llm = llm


def oracle_run(config, case, description, key, llm, run_dir, run_info, think_calls=(), think_llm=None) -> dict:
    """debug_run for the target passage only; the other article paragraphs are its case passages."""
    run_dir.mkdir(parents=True)   # raises if it exists: nothing is overwritten
    view = study2_view(config)
    logger = RunLogger(run_dir / "logs", "DEBUG", run_dir.name)
    applicability = ApplicabilityAgentV2(llm, logger, config=view)
    if think_calls:
        give_thinking(applicability, list(think_calls), think_llm)
    orch = OrchestratorV2(RelevanceAgentV2(llm, logger), applicability,
                          RequirementAgentV2(llm, logger), {}, run_dir / "unused",
                          load_c3_block_template(view, "c3_block_template_v2"), load_no_knowledge_text(view))
    started = datetime.now(timezone.utc)
    record = orch.mediate_passage(VARIANT, description, case["passages"][0], case["passages"])
    print(f"  {run_dir.name} {record['passage_id']}: {record['label']}", flush=True)
    block = orch.knowledge_block([record])
    files = retrieval_stages(case, description, key, VARIANT) | mediation_stages([record], block)
    files = {"00_run_info.json": run_info | {"run": run_dir.name, "started_at": started.isoformat(timespec="seconds"),
                                             "answer_key": key}} | files
    for name, data in files.items():
        write_json(run_dir / name, data)
    return {"run": run_dir.name, "records": [record], "knowledge_block": block}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Oracle O2: {VARIANT}, {TARGET} only, {RUNS} runs.")
    parser.add_argument("label", nargs="?", default="nodoc", help="name of the setting (default nodoc)")
    add_fresh_option(parser)
    parser.add_argument("--think-calls", default="",
                        help="comma-separated ApplicabilityAgentV2 call classes sent with think: true (default none)")
    args = parser.parse_args(argv)
    label = "o2_" + args.label
    think_calls = [c.strip() for c in args.think_calls.split(",") if c.strip()]
    config = load_config()
    ids = article_ids(config, TARGET)
    passages, corpus_sha = med.load_corpus_passages(config, ids)
    key = load_answer_key(config, VARIANT)
    description = (project_path(config["paths"]["cases"]) / VARIANT / config["paths"]["case_description_file"]
                   ).read_text(encoding="utf-8")
    llm, llm_info = make_llm(config)
    think_llm = thinking_llm(config) if think_calls else None
    run_info = {"case_id": VARIANT, "mode": "oracle O2: target mediated, other article paragraphs as case passages",
                "label": label, "mediated_passage_id": TARGET, "given_passage_ids": ids,
                "corpus_file": config["study2_corpus"]["passages"], "corpus_sha256": corpus_sha, "c3_version": "v2",
                "fresh": args.fresh, "think_calls": think_calls, **llm_info}
    case_dir = project_path(config["paths"]["runs"]).parent / "debug" / VARIANT
    case = med.given_case(passages, description)
    start = time.perf_counter()
    runs = []
    for _ in range(RUNS):
        run_dir = med.next_med_dir(case_dir, label)
        if args.fresh:
            unload_model(config)
        print(f"{run_dir} ...", flush=True)
        runs.append(oracle_run(config, case, description, key, llm, run_dir, run_info, think_calls, think_llm))
    text = med.summary_text(label, runs, VARIANT)
    for run in runs:
        (case_dir / run["run"] / "summary.txt").write_text(text, encoding="utf-8")
    print("\n" + text)
    print(json.dumps({"label": label, "fresh": args.fresh, "think_calls": think_calls, "given_passage_ids": ids, "seconds": round(time.perf_counter() - start, 1)}))


if __name__ == "__main__":
    main()
