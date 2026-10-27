"""QueryRewriter: qwen3:8b rewrites a case description into short legal-concept search queries (STUDY 2 only).

Config B and D of the RAG v2 extra round (docs/RAG_V2_CRITERIA.md section 7.2-7.3). Study 1 never uses it.

  1. the fixed prompt (prompts/rag_v2_query_rewrite.txt, byte-identical to section 7.3) gets the description,
     verbatim, in place of {description}; nothing else is changed
  2. one LLM call (OllamaLLM: temperature 0, seed 42, think false, num_ctx 16384)
  3. the answer is parsed: one query per non-empty line, leading "-", "*" and numbering stripped; an empty answer
     gives no queries (the original queries are still used by the retriever)

Every description is rewritten ONCE: the prompt, raw answer and parsed queries are saved to
<rewrite_dir>/<case_id>.json and reused by every later config and run (B, D, the freeze, the held-out check).
A saved file is never overwritten; if the description or the prompt changed, the rewriter stops.
Every real call is also logged through RunLogger.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from src.llm.base_llm import LLMClient

LEADING_MARK = re.compile(r"^(?:[-*]|\d+[.)])\s*")   # "- ", "* ", "1. ", "2) "


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_queries(answer: str) -> list[str]:
    """One query per non-empty line, without leading "-", "*" or numbering (section 7.3)."""
    queries = []
    for line in answer.splitlines():
        line = LEADING_MARK.sub("", line.strip()).strip()
        if line:
            queries.append(line)
    return queries


class QueryRewriter:
    """Rewrites each description once with the fixed prompt; saves and reuses the result per case."""

    def __init__(self, llm: LLMClient, template: str, out_dir: Path, logger_factory, run_facts: dict | None = None):
        """logger_factory: called once, before the first real call, to make the RunLogger (no empty log files).
        run_facts: Ollama version and server settings, stored in every rewrite file."""
        self.llm = llm
        self.template = template
        self.out_dir = Path(out_dir)
        self.logger_factory = logger_factory
        self.logger = None
        self.run_facts = run_facts or {}

    def prompt(self, description: str) -> str:
        return self.template.replace("{description}", description)

    def rewrite(self, case_id: str, description: str) -> list[str]:
        """The rewritten queries of the case (saved file if there is one, otherwise one LLM call)."""
        path = self.out_dir / f"{case_id}.json"
        prompt = self.prompt(description)
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved["prompt_sha256"] != sha256_text(prompt):
                raise RuntimeError(f"{path}: the description or the prompt changed since the rewrite; not reused, "
                                   f"not overwritten")
            return saved["queries"]

        start = time.monotonic()
        answer = self.llm.complete(prompt)
        duration = round(time.monotonic() - start, 2)
        queries = parse_queries(answer)
        if self.logger is None:
            self.logger = self.logger_factory()
        self.logger.log_call(case_id=case_id, component=type(self).__name__, model=self.llm.model_for_log,
                             temperature=self.llm.temperature, prompt=prompt, raw_output=answer,
                             parsed_output={"queries": queries}, valid_json=False, retries=0,
                             duration_seconds=duration, finish_reason=self.llm.last_finish_reason,
                             model_digest=self.llm.model_digest)
        record = {"case_id": case_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "model": self.llm.model_for_log, "model_digest": self.llm.model_digest,
                  "settings": {k: getattr(self.llm, k, None) for k in ("temperature", "seed", "num_ctx", "think",
                                                                        "max_tokens")},
                  **self.run_facts,
                  "finish_reason": self.llm.last_finish_reason, "duration_seconds": duration,
                  "description_sha256": sha256_text(description), "prompt_sha256": sha256_text(prompt),
                  "prompt": prompt, "raw_output": answer, "queries": queries,
                  "log_file": str(self.logger.log_path)}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return queries
