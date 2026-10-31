"""All development variants, 3 runs each: retrieval -> mediation on the run's own retrieved set -> oracle mediation.

For every variant (VARIANTS) and run n = 1..--runs, three steps, each in its own folder of results/debug/<variant>/:
  1. alldev_rag_run_<n>: RAG step routing with all options on (StepRouter: two-view routing, CombMAX top 10, parent
     expansion cap 20), the same code as scripts/debug_rag_v3_steps.py --two-view --fusion combmax --parent-expansion.
  2. med_alldev_run_<n>: mediation (OrchestratorV2, as scripts/debug_mediation_on_passages.py) on the expanded set of
     alldev_rag_run_<n> (its 04_merged_top5.json "passages").
  3. med_alldev_oracle_run_<n>: mediation on the target (answer key) + the rest of its article (all paragraphs of the
     target's article in the corpus, target first, the others in corpus order, no cap).
--fresh unloads the model before every step; --think-calls names the ApplicabilityAgentV2 calls sent with think: true
(mediation steps only; retrieval has no such calls).
--groq-model MODEL (ceiling test, run option only; config.yaml is not changed): ONLY the oracle step, label
ceiling_<model> (folder med_ceiling_<model>_run_<n>), with every C3 agent call on that Groq model (GroqLLM agent mode:
same prompts and code, temperature/seed/max_tokens from llm, the agents' output schema sent as Groq json_schema,
429 waits as Groq asks, answers cached in results/debug/_groq_cache/<model>/). No retrieval, no Ollama, no thinking
(Groq returns no reasoning in its JSON modes), so --fresh and --think-calls are refused. The silver model is refused.
--groq-json object: Groq json_object mode instead of json_schema (no schema sent; the prompts still carry it), label
ceiling_<model>_jsonobject. Added 31 Oct 2026: with json_schema, qwen/qwen3.8-27b put a junk token after the opening
brace in 27 of 150 calls (Groq json_validate_failed); json_object had 0 unparseable answers in 146 earlier calls.

--oracle-label LABEL (design rounds, added 31 Oct 2026): ONLY the oracle step (qwen3:8b, same options), saved under
that label (folder med_<LABEL>_run_<n>), e.g. --oracle-label round1 after design round 1; no retrieval, no full run.
--no-d5 / --no-d4b (ablation, added 31 Oct 2026, only with --oracle-label): switch off D5 (case events: every IF item
is read as a process fact, no "Applicable (conditional)") or D4b (special-case sub-rules are not evaluated) in
ApplicabilityAgentV2; prompts unchanged; saved in run_info.json as "ablation". Default: both on.

Resumable: a step whose folder has summary.txt (written last) is done and skipped. A folder without summary.txt is
left by a step that stopped; it is moved to results/debug/<variant>/_incomplete/<name>_<time> (never deleted) and the
step is run again. A step that fails (any exception) is logged with its traceback and the script goes on with the next
step; mediation of a run whose retrieval is not done is skipped (logged). Log: results/debug/run_all_dev.log (appended).

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m scripts.run_all_dev --fresh --think-calls CheckIfCallV2,SecondLookCallV2,VerifierCallV2
Ceiling test (GROQ_API_KEY in .env):
    .venv\\Scripts\\python.exe -m scripts.run_all_dev --groq-model qwen/qwen3.8-27b --runs 1
Oracles only, after a design round:
    .venv\\Scripts\\python.exe -m scripts.run_all_dev --oracle-label round1 --runs 1 --fresh --think-calls CheckIfCallV2,SecondLookCallV2,VerifierCallV2
Ablation of a design round, e.g. without D5:
    .venv\\Scripts\\python.exe -m scripts.run_all_dev --oracle-label abl_noD5 --no-d5 --runs 1 --fresh --think-calls CheckIfCallV2,SecondLookCallV2,VerifierCallV2
"""

import argparse
import copy
import hashlib
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path

from scripts.debug_mediation_on_passages import given_case, load_corpus_passages
from scripts.debug_mediation_on_passages import summary_text as mediation_summary
from scripts.debug_rag_v3_steps import run_once as rag_run_once
from scripts.debug_rag_v3_steps import summary_text as rag_summary
from scripts.debug_single_case import add_fresh_option, debug_run, load_answer_key, make_llm, unload_model
from src.config import load_config, project_path
from src.rag_v3_steps import article_id_of

VARIANTS = ("01.1", "01.2", "06.1", "11.1", "13.1", "17.1", "19.1", "45.1")
SR_OPTIONS = {"two_view": True, "fusion": "combmax", "parent_expansion": True}
LABEL = "alldev"
ORACLE_LABEL = "alldev_oracle"


def rag_dir(case_dir: Path, n: int) -> Path:
    return case_dir / f"{LABEL}_rag_run_{n}"


def med_dir(case_dir: Path, label: str, n: int) -> Path:
    return case_dir / f"med_{label}_run_{n}"


def is_done(run_dir: Path) -> bool:
    return (run_dir / "summary.txt").exists()


def clear_incomplete(run_dir: Path, log) -> None:
    """Move a folder left by a stopped step to _incomplete/ (kept, never deleted)."""
    if run_dir.exists():
        target = run_dir.parent / "_incomplete" / f"{run_dir.name}_{datetime.now():%Y%m%d_%H%M%S}"
        target.parent.mkdir(exist_ok=True)
        shutil.move(str(run_dir), str(target))
        log(f"moved incomplete {run_dir} -> {target}")


def oracle_ids(target: str, corpus_ids: list[str]) -> list[str]:
    """The target first, then the other paragraphs of its article in corpus order."""
    article = article_id_of(target)
    return [target] + [pid for pid in corpus_ids if article_id_of(pid) == article and pid != target]


def ceiling_label(model: str, json: str = "schema") -> str:
    return f"ceiling_{model.split('/')[-1]}" + ("_jsonobject" if json == "object" else "")


def ceiling_config(config: dict, model: str, json: str = "schema") -> dict:
    """A copy of the config with the C3 agents on the Groq model (json_schema, or json_object if json is "object";
    own cache). In memory only."""
    if model == config["silver"]["model"]:
        raise ValueError(f"{model} is the silver annotator's model; it must never be used for C3")
    config = copy.deepcopy(config)
    config["c3_agents_llm"]["provider"] = "groq"
    groq = config["c3_agents_llm"]["groq"]
    groq.update(model=model, json_schema=json == "schema", json_mode=True,
                cache_dir=str(project_path(config["paths"]["runs"]).parent / "debug" / "_groq_cache"
                              / model.replace("/", "__")))
    return config


def groq_llm(config: dict, model: str, json: str = "schema") -> tuple:
    """The Groq client for every C3 agent call (ceiling test); returns (client, run-info part)."""
    from run_experiment import create_llm
    from src.study2_config import study2_view
    config = ceiling_config(config, model, json)
    info = {"model": model, "provider": "groq", "groq_response_format": ("json_schema (agents' output schema)" if json == "schema" else "json_object"),
            "thinking": "none (Groq returns no reasoning in JSON modes)", "agent_settings": config["llm"]}
    return create_llm(study2_view(config), "relevance", {}), info


def retrieved_ids(run_dir: Path) -> list[str]:
    """The final set of an alldev retrieval run (after parent expansion)."""
    s4 = json.loads((run_dir / "04_merged_top5.json").read_text(encoding="utf-8"))
    return [p["passage_id"] for p in s4["passages"]]


class AllDevRunner:
    def __init__(self, config: dict, fresh: bool, think_calls: list[str], log, groq_model: str | None = None,
                 groq_json: str = "schema", oracle_label: str | None = None, ablation: dict | None = None):
        self.config, self.fresh, self.think_calls, self.log = config, fresh, think_calls, log
        self.ablation = ablation or {}   # ApplicabilityAgentV2 switches (--no-d5, --no-d4b); empty = all on
        self.groq_model, self.groq_json, self.oracle_label = groq_model, groq_json, oracle_label
        self.llm, self.llm_info = groq_llm(config, groq_model, groq_json) if groq_model else make_llm(config)
        self.think_llm = None
        if think_calls:
            from scripts.oracle_o2 import thinking_llm
            self.think_llm = thinking_llm(config)
        self.retrievers = None    # loaded on the first retrieval step
        corpus = project_path(config["study2_corpus"]["passages"])
        self.corpus_sha = hashlib.sha256(corpus.read_bytes()).hexdigest()
        self.corpus_ids = [json.loads(line)["id"] for line in corpus.read_text(encoding="utf-8").splitlines()
                           if line.strip()]

    def description(self, variant: str) -> str:
        return (project_path(self.config["paths"]["cases"]) / variant / self.config["paths"]["case_description_file"]
                ).read_text(encoding="utf-8")

    def retrieval(self, variant: str, run_dir: Path) -> None:
        from src.rag_v3_steps import RoutingAgent, StepRouter, StepsAgent, build_retrievers
        if self.retrievers is None:
            self.retrievers = build_retrievers(self.config)
        passages, dense, sparse, reranker = self.retrievers
        key = load_answer_key(self.config, variant)
        run_info = {"method": "RAG step routing (SR), src/rag_v3_steps.py, all options on (scripts/run_all_dev.py)",
                    "case_id": variant, "corpus_file": self.config["study2_corpus"]["passages"],
                    "corpus_sha256": self.corpus_sha, "n_passages": len(passages),
                    "agent_settings": self.config["llm"], "reranker_model": reranker.model_name,
                    "reranker_revision": reranker.revision, "fresh": self.fresh, "sr_options": SR_OPTIONS,
                    **self.llm_info}

        def router_factory(logger):
            return StepRouter(self.config, StepsAgent(self.llm, logger), RoutingAgent(self.llm, logger), passages,
                              dense, sparse, reranker, **SR_OPTIONS)

        run = rag_run_once(self.config, router_factory, self.description(variant), key, run_dir, run_info, variant)
        (run_dir / "summary.txt").write_text(rag_summary([run], key, variant), encoding="utf-8")

    def mediation(self, variant: str, run_dir: Path, label: str, ids: list[str], source: str) -> None:
        passages, corpus_sha = load_corpus_passages(self.config, ids)
        description = self.description(variant)
        run_info = {"case_id": variant, "mode": "mediation on given passages (no retrieval)", "label": label,
                    "passages_from": source, "given_passage_ids": ids,
                    "corpus_file": self.config["study2_corpus"]["passages"], "corpus_sha256": corpus_sha,
                    "c3_version": "v2", "fresh": self.fresh, "think_calls": self.think_calls, **self.llm_info}
        if self.ablation:
            run_info["ablation"] = self.ablation
        waits_before = len(getattr(self.llm, "connection_retries", []))
        run = debug_run(self.config, given_case(passages, description), description,
                        load_answer_key(self.config, variant), self.llm, run_dir, run_info, variant,
                        self.think_calls, self.think_llm, self.ablation)
        if self.groq_model:   # Groq rate-limit waits of this step (not failures)
            (run_dir / "groq_rate_limit_waits.json").write_text(json.dumps(
                self.llm.connection_retries[waits_before:], indent=2), encoding="utf-8")
        (run_dir / "summary.txt").write_text(mediation_summary(label, [run], variant), encoding="utf-8")

    def step(self, name: str, run_dir: Path, action) -> bool:
        """Run one step unless it is done. Returns True if the step is done afterwards."""
        if is_done(run_dir):
            self.log(f"skip {name}: {run_dir.name} done")
            return True
        clear_incomplete(run_dir, self.log)
        self.log(f"start {name}: {run_dir}")
        started = datetime.now()
        try:
            if self.fresh:
                unload_model(self.config)
            action()
        except Exception:
            self.log(f"FAILED {name} after {(datetime.now() - started).seconds} s:\n{traceback.format_exc()}")
            return False
        self.log(f"done {name} in {(datetime.now() - started).seconds} s")
        return True

    def run_variant(self, variant: str, n: int) -> None:
        case_dir = project_path(self.config["paths"]["runs"]).parent / "debug" / variant
        target = load_answer_key(self.config, variant)["target_passage_id"]
        if self.groq_model or self.oracle_label:   # ceiling test or design round: the oracle step only
            label = self.oracle_label or ceiling_label(self.groq_model, self.groq_json)
            ceiling = med_dir(case_dir, label, n)
            self.step(f"{variant} run {n} {label}", ceiling,
                      lambda: self.mediation(variant, ceiling, label, oracle_ids(target, self.corpus_ids),
                                             "oracle: target + the rest of its article"))
            return
        rag = rag_dir(case_dir, n)
        if self.step(f"{variant} run {n} retrieval", rag, lambda: self.retrieval(variant, rag)):
            ids = retrieved_ids(rag)
            med = med_dir(case_dir, LABEL, n)
            self.step(f"{variant} run {n} mediation", med,
                      lambda: self.mediation(variant, med, LABEL, ids, rag.name))
        else:
            self.log(f"skip {variant} run {n} mediation: retrieval not done")
        oracle = med_dir(case_dir, ORACLE_LABEL, n)
        self.step(f"{variant} run {n} oracle", oracle,
                  lambda: self.mediation(variant, oracle, ORACLE_LABEL, oracle_ids(target, self.corpus_ids),
                                         "oracle: target + the rest of its article"))


def make_log(path: Path):
    def log(message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        print(line, flush=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return log


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Retrieval + mediation + oracle for all development variants.")
    parser.add_argument("--variants", default=",".join(VARIANTS), help="comma-separated variants (default all)")
    parser.add_argument("--runs", type=int, default=3, help="runs per variant (default 3)")
    parser.add_argument("--only-run", type=int, default=None, help="do only run n (e.g. a smoke test of run 1)")
    add_fresh_option(parser)
    parser.add_argument("--think-calls", default="",
                        help="comma-separated ApplicabilityAgentV2 call classes sent with think: true (default none)")
    parser.add_argument("--groq-model", default=None,
                        help="ceiling test: oracle step only, every C3 agent call on this Groq model")
    parser.add_argument("--groq-json", choices=("schema", "object"), default="schema",
                        help="Groq JSON output: json_schema (default) or json_object")
    parser.add_argument("--oracle-label", default=None,
                        help="design round: only the oracle step, saved as med_<label>_run_<n> (e.g. round1)")
    parser.add_argument("--no-d5", action="store_true",
                        help="ablation (with --oracle-label): switch off D5, every IF item read as a process fact")
    parser.add_argument("--no-d4b", action="store_true",
                        help="ablation (with --oracle-label): switch off D4b, special-case sub-rules not evaluated")
    args = parser.parse_args(argv)
    if args.groq_model and (args.fresh or args.think_calls):
        parser.error("--groq-model does not use Ollama: --fresh and --think-calls are not allowed")
    if args.oracle_label and (args.groq_model or args.oracle_label in (LABEL, ORACLE_LABEL)):
        parser.error("--oracle-label needs its own name and cannot be combined with --groq-model")
    if (args.no_d5 or args.no_d4b) and not args.oracle_label:
        parser.error("--no-d5 / --no-d4b need --oracle-label (their own folder name)")
    ablation = {k: False for k, off in (("case_events", args.no_d5), ("sub_rules", args.no_d4b)) if off}
    config = load_config()
    log = make_log(project_path(config["paths"]["runs"]).parent / "debug" / "run_all_dev.log")
    think_calls = [c.strip() for c in args.think_calls.split(",") if c.strip()]
    runner = AllDevRunner(config, args.fresh, think_calls, log, args.groq_model, args.groq_json, args.oracle_label,
                          ablation)
    numbers = [args.only_run] if args.only_run else range(1, args.runs + 1)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    log(f"run_all_dev: variants {variants}, runs {list(numbers)}, fresh {args.fresh}, think_calls {think_calls}, "
        f"groq_model {args.groq_model}, groq_json {args.groq_json}, oracle_label {args.oracle_label}, ablation {ablation}")
    for variant in variants:
        for n in numbers:
            runner.run_variant(variant, n)
    log("run_all_dev finished")


if __name__ == "__main__":
    main()
