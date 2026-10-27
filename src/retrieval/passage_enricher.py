"""PassageEnricher: qwen3:8b writes 1-2 business-language sentences on when a law passage applies (STUDY 2 only).

Option F and G of RAG v3, EXPLORATORY (docs/RAG_V2_CRITERIA.md section 8.2-8.3). Study 1 never uses it.

  1. the fixed prompt (prompts/rag_v3_enrichment.txt, byte-identical to section 8.3) gets the passage's `text`
     field, verbatim, in place of {passage_text}; nothing else is changed. The input is the passage text ONLY
     (never a case, variant or description).
  2. one LLM call (OllamaLLM: temperature 0, seed 42, think false, num_ctx 16384)
  3. the answer is stripped of leading/trailing whitespace and used verbatim (no shortening, no repair); an empty
     answer gives no enrichment. A cut-off answer (finish_reason MAX_TOKENS) is kept as it is.

Every passage is enriched ONCE: the prompt, raw answer, enrichment and finish reason are saved to
<out_dir>/<passage_id>.json and reused by a resumed run. A saved file is never overwritten; if the passage text or
the prompt changed, the enricher stops. Every real call is also logged through RunLogger.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from src.llm.base_llm import LLMClient
from src.retrieval.passage import Passage
from src.retrieval.query_rewriter import sha256_text


class PassageEnricher:
    """Enriches each passage once with the fixed prompt; saves and reuses the result per passage."""

    def __init__(self, llm: LLMClient, template: str, out_dir: Path, logger_factory, run_facts: dict | None = None):
        """logger_factory: called once, before the first real call, to make the RunLogger (no empty log files).
        run_facts: Ollama version and server settings, stored in every enrichment file."""
        self.llm = llm
        self.template = template
        self.out_dir = Path(out_dir)
        self.logger_factory = logger_factory
        self.logger = None
        self.run_facts = run_facts or {}

    def prompt(self, passage_text: str) -> str:
        return self.template.replace("{passage_text}", passage_text)

    def enrich(self, passage: Passage) -> dict:
        """The saved record of the passage (saved file if there is one, otherwise one LLM call)."""
        path = self.out_dir / f"{passage.id}.json"
        prompt = self.prompt(passage.text)
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved["prompt_sha256"] != sha256_text(prompt):
                raise RuntimeError(f"{path}: the passage text or the prompt changed since the enrichment; not reused, "
                                   f"not overwritten")
            return saved

        start = time.monotonic()
        answer = self.llm.complete(prompt)
        duration = round(time.monotonic() - start, 2)
        enrichment = answer.strip()
        if self.logger is None:
            self.logger = self.logger_factory()
        self.logger.log_call(case_id=passage.id, component=type(self).__name__, model=self.llm.model_for_log,
                             temperature=self.llm.temperature, prompt=prompt, raw_output=answer,
                             parsed_output={"enrichment": enrichment}, valid_json=False, retries=0,
                             duration_seconds=duration, finish_reason=self.llm.last_finish_reason,
                             model_digest=self.llm.model_digest)
        record = {"passage_id": passage.id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "label": "EXPLORATORY (docs/RAG_V2_CRITERIA.md section 8)",
                  "model": self.llm.model_for_log, "model_digest": self.llm.model_digest,
                  "settings": {k: getattr(self.llm, k, None) for k in ("temperature", "seed", "num_ctx", "think",
                                                                        "max_tokens")},
                  **self.run_facts,
                  "finish_reason": self.llm.last_finish_reason, "duration_seconds": duration,
                  "passage_text_sha256": sha256_text(passage.text), "prompt_sha256": sha256_text(prompt),
                  "prompt": prompt, "raw_output": answer, "enrichment": enrichment,
                  "log_file": str(self.logger.log_path)}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return record
