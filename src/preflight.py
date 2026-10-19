"""Preflight: checks that must ALL pass before any generation (fix E1, 19 Oct 2026). One PASS / FAIL line per check.

  1 analysis plan     docs/ANALYSIS_PLAN.md is committed, without uncommitted changes
  2 frozen retrieval  SHA-256 of frozen_retrieval.json and passages.jsonl = the values in the plan (section 9)
  3 C3 version        every C3 prompt part equals the frozen version named in config (mediation.c3_version)
  4 model             the installed Ollama model has the digest in config (model.ollama_model_digest)
  5 BPMNGen           the hashes of every BPMNGen file the harness loads = the verified record
                      (paths.bpmngen_expected_hashes)
  6 sample cases      the n_sample_cases DEVELOPMENT cases (cases.development_ids) with the longest C2 prompt:
                      C1, C2, C3 requests made by BPMNGen itself (harness --dry-run, nothing sent) differ only in the
                      knowledge block and match config (model, temperature, num_ctx, think, system prompt); C3's
                      block comes from the REAL C3 agents (decided 19 Oct 2026; agents never run on test cases)
  7 prompt length     each of those requests stays below max_prompt_share_of_num_ctx (80%) of model.num_ctx:
                      counted by Ollama (one call with num_predict 1) when it runs, else a conservative ESTIMATE
  8 test cases       (cases.test_ids) C1 and C2 requests only: same checks as 6 and 7, no agents
Everything is written to results/preflight/<timestamp>/ (report.txt, the dry-run requests, the C3 mediation and
the log of every LLM call); nothing else is touched.

Run from the project root:  .venv\\Scripts\\python.exe -m src.preflight      (exit code 0 = all passed)
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.bpmngen_files import BPMNGenFiles
from src.bpmngen_generator import BPMNGenGenerator, GeneratorSetupError, installed_ollama_digest
from src.c3_version import changed_items
from src.config import load_config, project_path
from src.generator import format_passages
from src.llm.base_llm import LLMUnavailableError
from src.logger import RunLogger
from src.orchestrator import Orchestrator
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
from src.retrieval.passage import load_passages
from src.stage_gates import git_committed

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class OllamaProbe:
    """The two Ollama questions of the preflight: the installed digest, and the prompt length of a request."""

    def __init__(self, config: dict, client: httpx.Client | None = None):
        model = config["model"]
        self.url, self.name = model["ollama_url"], model["name"]
        self.client = client or httpx.Client(timeout=config["llm"]["ollama_timeout_seconds"])

    def digest(self) -> str | None:
        return installed_ollama_digest(self.url, self.name, self.client)

    def prompt_tokens(self, request: dict) -> int:
        """Ollama's own count of the request's prompt: the same request, not streamed, at most 1 answer token."""
        body = dict(request, stream=False, options=dict(request.get("options") or {}, num_predict=1))
        try:
            response = self.client.post(f"{self.url.rstrip('/')}/api/chat", json=body)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama not usable for the token count: {e}") from e
        return response.json()["prompt_eval_count"]


class Preflight:
    def __init__(self, config: dict, out_dir: Path, generator=None, files=None, probe=None, agent_llms=None):
        """generator, files, probe and agent_llms can be replaced in tests (no BPMNGen, no Ollama)."""
        self.config, self.out_dir = config, Path(out_dir)
        self.generator = generator or BPMNGenGenerator(config, logger=None)
        self.files = files or BPMNGenFiles(config)
        self.probe = probe or OllamaProbe(config)
        self.agent_llms = agent_llms
        self.lines: list[tuple[str, str]] = []
        self.logger = None
        paths = config["paths"]
        self.frozen = json.loads(project_path(paths["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
        self.cases_dir = project_path(paths["cases"])

    def record(self, status: str, text: str) -> None:
        self.lines.append((status, text))

    # ---------- checks 1-5 ----------

    def check_plan_and_frozen(self) -> None:
        paths = self.config["paths"]
        plan = project_path(paths["analysis_plan"])
        reason = git_committed(plan)
        self.record(PASS if reason is None else FAIL, f"analysis plan committed ({plan.name})"
                    + ("" if reason is None else f": {reason}"))
        text = plan.read_text(encoding="utf-8")
        for key, name in (("frozen_retrieval", "frozen_retrieval.json"), ("passages", "passages.jsonl")):
            match = re.search(re.escape(name) + r"`?\s*SHA-256\s*`?([0-9a-f]{64})", text)
            actual = sha256_file(project_path(paths[key]))
            if match is None:
                self.record(FAIL, f"{name} checksum: not stated in the analysis plan")
            else:
                self.record(PASS if match.group(1) == actual else FAIL,
                            f"{name} checksum matches the plan ({actual[:12]}...)" if match.group(1) == actual
                            else f"{name} checksum {actual[:12]}... differs from the plan ({match.group(1)[:12]}...)")

    def check_c3_version(self) -> None:
        try:
            changed = changed_items(self.config)
        except (ValueError, FileNotFoundError) as e:
            self.record(FAIL, f"C3 version: {e}")
            return
        version = self.config["mediation"]["c3_version"]
        self.record(PASS if not changed else FAIL, f"C3 prompts match frozen C3 {version}" if not changed
                    else f"C3 prompts differ from frozen C3 {version}: {changed}")

    def check_model(self) -> bool:
        """True if Ollama answered (needed for the agents and the exact token count)."""
        expected = self.config["model"]["ollama_model_digest"]
        try:
            digest = self.probe.digest()
        except LLMUnavailableError as e:
            self.record(FAIL, f"model digest: Ollama not reachable ({e})")
            return False
        self.record(PASS if digest == expected else FAIL,
                    f"model {self.config['model']['name']} digest matches config ({expected[:12]}...)"
                    if digest == expected else f"model digest {str(digest)[:12]}... differs from config ({expected[:12]}...)")
        return True

    def check_bpmngen(self) -> None:
        expected = json.loads(project_path(self.config["paths"]["bpmngen_expected_hashes"])
                              .read_text(encoding="utf-8"))["hashes"]
        try:
            current = self.files.hashes()
        except (RuntimeError, FileNotFoundError) as e:
            self.record(FAIL, f"BPMNGen hashes: {e}")
            return
        changed = sorted(p for p in set(expected) | set(current) if expected.get(p) != current.get(p))
        self.record(PASS if not changed else FAIL, f"BPMNGen hashes match the record ({len(current)} files)"
                    if not changed else f"BPMNGen files differ from the record: {changed}")

    # ---------- checks 6-8 ----------

    def c2_block(self, case_id: str) -> str:
        return format_passages(self.frozen[case_id]["passages"])

    def sample_cases(self) -> list[str]:
        """The development cases with the longest C2 prompt (description + C2 block)."""
        paths = self.config["paths"]
        size = {c: len((self.cases_dir / c / paths["case_description_file"]).read_text(encoding="utf-8"))
                + len(self.c2_block(c)) for c in self.config["cases"]["development_ids"]}
        return sorted(size, key=lambda c: (-size[c], c))[:self.config["preflight"]["n_sample_cases"]]

    def c3_block(self, case_id: str, description: str) -> str:
        """C3's knowledge block from the REAL C3 agents (development cases only), saved in the preflight folder."""
        paths = self.config["paths"]
        if self.logger is None:
            self.logger = RunLogger(self.out_dir / "logs", "C3", "preflight")
        llms = self.agent_llms
        titles = {p.id: p.title for p in load_passages(project_path(paths["passages"]))}
        orchestrator = Orchestrator(RelevanceAgent(llms["relevance"], self.logger),
                                    ApplicabilityAgent(llms["applicability"], self.logger),
                                    RequirementAgent(llms["requirement"], self.logger),
                                    self.frozen, titles, self.out_dir / paths["mediation_dir"],
                                    load_c3_block_template(self.config), paths["mediation_summary_file"])
        return orchestrator.mediate_case(case_id, description)["knowledge_block"]

    def check_case(self, case_id: str, conditions: list[str], kind: str, ollama_up: bool) -> None:
        paths, label = self.config["paths"], self.config["generator"]["knowledge_label"]
        description_file = self.cases_dir / case_id / paths["case_description_file"]
        description = description_file.read_text(encoding="utf-8")
        requests, users = {}, {}
        try:
            for condition in conditions:
                block = {"C1": lambda: load_no_knowledge_text(self.config), "C2": lambda: self.c2_block(case_id),
                         "C3": lambda: self.c3_block(case_id, description)}[condition]()
                work = self.out_dir / "dry_run" / case_id / condition
                requests[condition] = self.generator.dry_run_request(description_file, block, work)
                self.generator.check_request(requests[condition])
                # line endings normalised on both sides (the block file is written in text mode on Windows)
                knowledge = (work / paths["knowledge_block_file"]).read_text(encoding="utf-8").strip()
                user = [m["content"] for m in requests[condition]["messages"]
                        if m["role"] == "user"][-1].replace("\r\n", "\n")
                marker = f"{label}\n{knowledge}"
                users[condition] = user.replace(marker, f"{label}\n<KNOWLEDGE>") if marker in user else None
        except (GeneratorSetupError, RuntimeError, LLMUnavailableError) as e:
            self.record(FAIL, f"{kind} case {case_id}: {type(e).__name__}: {e}")
            return
        rest = {c: {k: v for k, v in r.items() if k != "messages"} | {"system": [m for m in r["messages"]
                                                                                 if m["role"] != "user"]}
                for c, r in requests.items()}
        same_rest = all(rest[c] == rest[conditions[0]] for c in conditions)
        same_user = None not in users.values() and len(set(users.values())) == 1
        self.record(PASS if same_rest and same_user else FAIL,
                    f"{kind} case {case_id}: {'/'.join(conditions)} requests differ only in the knowledge block "
                    "and match config" if same_rest and same_user else
                    f"{kind} case {case_id}: requests differ in more than the knowledge block")
        self.check_length(case_id, requests, kind, ollama_up)

    def check_length(self, case_id: str, requests: dict, kind: str, ollama_up: bool) -> None:
        settings, num_ctx = self.config["preflight"], self.config["model"]["num_ctx"]
        limit = int(settings["max_prompt_share_of_num_ctx"] * num_ctx)
        for condition, request in requests.items():
            if ollama_up:
                try:
                    tokens, how = self.probe.prompt_tokens(request), "counted by Ollama"
                except LLMUnavailableError as e:
                    self.record(FAIL, f"{kind} case {case_id} {condition}: prompt length not counted ({e})")
                    continue
                self._log_count(case_id, condition, request, tokens)
            else:
                chars = sum(len(m["content"]) for m in request["messages"])
                tokens, how = int(chars / settings["chars_per_token_estimate"]) + 1, "ESTIMATE, Ollama not running"
            self.record(PASS if tokens < limit else FAIL,
                        f"{kind} case {case_id} {condition}: prompt {tokens} tokens ({how}) "
                        f"{'<' if tokens < limit else '>='} {limit} = {settings['max_prompt_share_of_num_ctx']:.0%} "
                        f"of num_ctx {num_ctx}")

    def _log_count(self, case_id: str, condition: str, request: dict, tokens: int) -> None:
        """Every LLM call is logged, also the 1-token count call."""
        logger = RunLogger(self.out_dir / "logs", f"TOKENS_{condition}", f"preflight_{case_id}")
        logger.log_call(case_id=case_id, component="PreflightTokenCount", model=request.get("model"),
                        temperature=(request.get("options") or {}).get("temperature"),
                        prompt=json.dumps(request.get("messages"), ensure_ascii=False), raw_output="",
                        parsed_output={"prompt_eval_count": tokens}, valid_json=True, retries=0,
                        duration_seconds=None, finish_reason="MAX_TOKENS",
                        model_digest=self.config["model"]["ollama_model_digest"])

    # ---------- all ----------

    def run(self) -> bool:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.check_plan_and_frozen()
        self.check_c3_version()
        ollama_up = self.check_model()
        self.check_bpmngen()
        if ollama_up and self.agent_llms is not None:
            for case_id in self.sample_cases():
                self.check_case(case_id, self.config["conditions"], "development", ollama_up)
        else:
            self.record(FAIL, "development sample cases: not checked, because Ollama (needed for the C3 agents) "
                              "is not running")
        test_ids = self.config["cases"]["test_ids"]
        if not test_ids:
            self.record(SKIP, "test cases: none defined (config.yaml cases.test_ids)")
        for case_id in test_ids:
            self.check_case(case_id, ["C1", "C2"], "test", ollama_up)
        report = "\n".join(f"{status:4}  {text}" for status, text in self.lines)
        passed = all(status != FAIL for status, _ in self.lines)
        (self.out_dir / "report.txt").write_text(report + f"\n\nPREFLIGHT {'PASSED' if passed else 'FAILED'}\n",
                                                 encoding="utf-8")
        return passed


def main() -> None:
    from run_experiment import MEDIATION_ROLES, create_llm
    config = load_config()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = project_path(config["paths"]["preflight_dir"]) / stamp
    shared = {}
    agent_llms = {role: create_llm(config, role, shared) for role in MEDIATION_ROLES}
    preflight = Preflight(config, out_dir, agent_llms=agent_llms)
    passed = preflight.run()
    print((out_dir / "report.txt").read_text(encoding="utf-8"))
    print(f"Saved in {out_dir}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
