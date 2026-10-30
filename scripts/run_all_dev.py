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

Resumable: a step whose folder has summary.txt (written last) is done and skipped. A folder without summary.txt is
left by a step that stopped; it is moved to results/debug/<variant>/_incomplete/<name>_<time> (never deleted) and the
step is run again. A step that fails (any exception) is logged with its traceback and the script goes on with the next
step; mediation of a run whose retrieval is not done is skipped (logged). Log: results/debug/run_all_dev.log (appended).

Run from the project root (Ollama running):
    .venv\\Scripts\\python.exe -m scripts.run_all_dev --fresh --think-calls CheckIfCallV2,SecondLookCallV2,VerifierCallV2
"""

import argparse
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


def retrieved_ids(run_dir: Path) -> list[str]:
    """The final set of an alldev retrieval run (after parent expansion)."""
    s4 = json.loads((run_dir / "04_merged_top5.json").read_text(encoding="utf-8"))
    return [p["passage_id"] for p in s4["passages"]]


class AllDevRunner:
    def __init__(self, config: dict, fresh: bool, think_calls: list[str], log):
        self.config, self.fresh, self.think_calls, self.log = config, fresh, think_calls, log
        self.llm, self.llm_info = make_llm(config)
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
        run = debug_run(self.config, given_case(passages, description), description,
                        load_answer_key(self.config, variant), self.llm, run_dir, run_info, variant,
                        self.think_calls, self.think_llm)
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
    args = parser.parse_args(argv)
    config = load_config()
    log = make_log(project_path(config["paths"]["runs"]).parent / "debug" / "run_all_dev.log")
    think_calls = [c.strip() for c in args.think_calls.split(",") if c.strip()]
    runner = AllDevRunner(config, args.fresh, think_calls, log)
    numbers = [args.only_run] if args.only_run else range(1, args.runs + 1)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    log(f"run_all_dev: variants {variants}, runs {list(numbers)}, fresh {args.fresh}, think_calls {think_calls}")
    for variant in variants:
        for n in numbers:
            runner.run_variant(variant, n)
    log("run_all_dev finished")


if __name__ == "__main__":
    main()
