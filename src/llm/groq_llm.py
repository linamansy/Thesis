"""GroqLLM: calls a model on Groq's free API (OpenAI-compatible chat completions), used for the silver
reference annotator (src/build_silver_reference.py) and, ONLY in the stronger-model mediation diagnostic
(docs/MEDIATION_TEST_CRITERIA.md section 6, scripts/run_mediation_strong.py), for the C3 agents
(config.yaml c3_agents_llm.provider: groq; the default stays ollama). The generator never uses it.

  - The API key is read from the .env file (GROQ_API_KEY); it never appears in code.
  - Model, temperature (0) and max_tokens come from config.yaml (silver section). After every answer, the
    exact model name Groq returns is stored in last_response_model (the silver builder stops if it differs
    from silver.model), and Groq's system_fingerprint (which backend build answered) in last_system_fingerprint.
  - gpt-oss-120b is a reasoning model: Groq returns its reasoning in a separate field. It is kept in
    last_reasoning and written to the log, so every output is saved.
  - Free-tier limits (seen 19 Oct 2026: 1000 requests/day, 8000 tokens/minute). Groq counts prompt + max_tokens
    against the per-minute budget when the request arrives, so silver.max_tokens is set low enough that one
    request always fits. When a limit is reached Groq answers 429 with the time to wait; the client waits and
    tries again. These waits are NOT failures and are not counted as retries. If Groq asks for a wait longer
    than silver.groq_max_rate_limit_wait_seconds (the daily limit is used up), the run stops
    (LLMUnavailableError) and can be resumed later.
  - Agent mode (from_agent_config, c3_agents_llm.groq): the agents' temperature (0), seed and max_tokens from the
    llm section, JSON output (response_format json_object), every 429 wait recorded in connection_retries, and a
    response cache (one file per request, named by the SHA-256 of the exact request body), so a rerun sends nothing
    twice. If Groq rejects an answer as invalid JSON (HTTP 400 json_validate_failed), the model's text is returned as
    the answer, so BaseAgent treats it like any invalid JSON answer (one retry), as with Ollama.
    The silver requests are unchanged: seed, response_format and the cache are only used when set.
  - Server errors (5xx), timeouts and network errors are retried with increasing waits (2, 4, 8, ... s,
    silver.groq_api_max_retries times). Other errors (e.g. 401 wrong key, 404 unknown model) stop at once.
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from dotenv import load_dotenv

from src.config import project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError

FINISH_REASONS = {"stop": "STOP", "length": "MAX_TOKENS", "json_validate_failed": "JSON_VALIDATE_FAILED"}  # same words as for Gemini and Ollama


class MissingGroqKeyError(RuntimeError):
    """Raised when GROQ_API_KEY is not set."""


def wait_seconds(response: httpx.Response, default: float) -> float:
    """How long Groq asks us to wait: the retry-after header, else the x-ratelimit-reset-* headers
    (e.g. "2.114s", "1m26.4s"), else the default."""
    if response.headers.get("retry-after"):
        try:
            return float(response.headers["retry-after"])
        except ValueError:
            pass
    resets = [parse_duration(response.headers[h]) for h in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
              if response.headers.get(h)]
    resets = [r for r in resets if r is not None]
    return max(resets) if resets else default


def parse_duration(text: str) -> float | None:
    """'1m26.4s' -> 86.4, '2.114s' -> 2.114, '850ms' -> 0.85; None if not understood."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?", text.strip())
    if not match or not any(match.groups()):
        return None
    h, m, s, ms = match.groups()
    return int(h or 0) * 3600 + int(m or 0) * 60 + float(s or 0) + float(ms or 0) / 1000


def failed_generation(response: httpx.Response) -> str | None:
    """The model's text when Groq rejected it as invalid JSON (error code json_validate_failed), else None."""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        return None
    return error.get("failed_generation", "") if error.get("code") == "json_validate_failed" else None


class GroqLLM(LLMClient):
    """LLMClient for Groq's OpenAI-compatible chat completions API."""

    def __init__(self, model: str, temperature: float, max_tokens: int, api_max_retries: int,
                 initial_wait_seconds: float, max_rate_limit_wait_seconds: float, base_url: str,
                 timeout_seconds: float, max_rate_limit_waits: int, api_key: str | None = None, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, seed: int | None = None, json_mode: bool = False,
                 cache_dir: Path | None = None):
        """client and sleep can be replaced in tests: no real API call and no real waiting.
        max_rate_limit_waits: safety stop, one call that keeps getting 429 is given up after this many waits
        (config.yaml silver.groq_max_rate_limit_waits).
        seed, json_mode, cache_dir: agent mode only (from_agent_config); None/False = not sent, no cache."""
        super().__init__(model=model, temperature=temperature)
        self.max_tokens = max_tokens
        self.max_rate_limit_waits = max_rate_limit_waits
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.max_rate_limit_wait_seconds = max_rate_limit_wait_seconds
        self.sleep = sleep
        self.retry_waits: list[float] = []       # waits after server errors / timeouts (counted as retries)
        self.rate_limit_waits: list[float] = []  # waits after 429 (not counted)
        self.last_system_fingerprint: str | None = None
        self.seed = seed
        self.json_mode = json_mode
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.connection_retries: list[dict] = []  # agent mode: every 429 wait (saved by the diagnostic script)
        self.cache_hits = 0
        if client is None:
            api_key = api_key or os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise MissingGroqKeyError("GROQ_API_KEY is not set. Add the line GROQ_API_KEY=<your key> to the "
                                          ".env file in the project root (see .env.example).")
            client = httpx.Client(base_url=base_url, timeout=timeout_seconds,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self.client = client

    @classmethod
    def from_config(cls, config: dict, client: httpx.Client | None = None) -> "GroqLLM":
        load_dotenv(project_path(config["paths"]["env_file"]))  # puts GROQ_API_KEY into the environment
        silver, llm = config["silver"], config["llm"]
        return cls(silver["model"], silver["temperature"], silver["max_tokens"], silver["groq_api_max_retries"],
                   llm["api_initial_wait_seconds"], silver["groq_max_rate_limit_wait_seconds"],
                   silver["groq_base_url"], silver["groq_timeout_seconds"], silver["groq_max_rate_limit_waits"],
                   client=client)

    @classmethod
    def from_agent_config(cls, config: dict, client: httpx.Client | None = None,
                          sleep: Callable[[float], None] = time.sleep) -> "GroqLLM":
        """The C3 agents' client when c3_agents_llm.provider is groq: model and Groq settings from c3_agents_llm.groq;
        temperature, seed and max_tokens from llm (the same values the agents send to Ollama)."""
        load_dotenv(project_path(config["paths"]["env_file"]))  # puts GROQ_API_KEY into the environment
        groq, llm = config["c3_agents_llm"]["groq"], config["llm"]
        return cls(groq["model"], llm["temperature"], llm["max_tokens"], groq["api_max_retries"],
                   llm["api_initial_wait_seconds"], groq["max_rate_limit_wait_seconds"], groq["base_url"],
                   groq["timeout_seconds"], groq["max_rate_limit_waits"], client=client, sleep=sleep,
                   seed=llm["seed"], json_mode=groq["json_mode"], cache_dir=project_path(groq["cache_dir"]))

    def request_body(self, prompt: str) -> dict:
        """The exact request sent for every call."""
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature, "max_tokens": self.max_tokens}
        if self.seed is not None:
            body["seed"] = self.seed
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def complete(self, prompt: str) -> str:
        if self.cache_dir is None:
            return self._read(self._post(prompt))
        body = self.request_body(prompt)
        key = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():   # the same request was answered before: no new call
            self.cache_hits += 1
            return self._read(json.loads(path.read_text(encoding="utf-8"))["response"])
        data = self._post(prompt)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"request": body, "response": data}, indent=2, ensure_ascii=False), encoding="utf-8")
        return self._read(data)

    def _post(self, prompt: str) -> dict:
        """Send one request (with the waits and retries described above); return Groq's JSON answer."""
        failures = waits = 0   # for this call: counted failures, and rate-limit waits (not counted as failures)
        for _ in range(self.max_rate_limit_waits + self.api_max_retries + 1):
            try:
                response = self.client.post("/chat/completions", json=self.request_body(prompt))
            except httpx.TransportError as e:  # timeout or network error: a counted retry
                failures = self._count_failure(failures, f"{type(e).__name__}: {e}", e)
                continue
            if response.status_code == 429:   # rate limit: wait as asked, NOT a failure
                wait = wait_seconds(response, self.initial_wait_seconds)
                if wait > self.max_rate_limit_wait_seconds:
                    raise LLMUnavailableError(f"Groq rate limit: asked to wait {wait:.0f} s (more than "
                                              f"{self.max_rate_limit_wait_seconds} s, probably the daily limit). "
                                              f"Resume later. {response.text[:300]}")
                waits += 1
                if waits > self.max_rate_limit_waits:
                    raise LLMUnavailableError(f"Groq rate limit: more than {self.max_rate_limit_waits} waits for one call")
                self.rate_limit_waits.append(wait)
                self.connection_retries.append({"at": datetime.now(timezone.utc).isoformat(), "http_status": 429,
                                                "wait_seconds": wait})
                self.sleep(wait)
                continue
            if response.status_code >= 500:  # server error: a counted retry
                failures = self._count_failure(failures, f"HTTP {response.status_code}: {response.text[:300]}")
                continue
            if response.status_code == 400 and self.json_mode and failed_generation(response) is not None:
                return {"model": self.model, "choices": [{"finish_reason": "json_validate_failed",
                                                          "message": {"content": failed_generation(response)}}]}
            if response.status_code != 200:   # e.g. 401 wrong key, 404 unknown model, 413 request too large
                raise LLMUnavailableError(f"Groq API error (not retried): HTTP {response.status_code}: "
                                          f"{response.text[:500]}")
            return response.json()
        raise LLMUnavailableError("Groq API: too many attempts")

    def _count_failure(self, failures: int, text: str, cause: Exception | None = None) -> int:
        if failures == self.api_max_retries:
            raise LLMUnavailableError(f"Groq API still failing after {self.api_max_retries} retries: {text}") from cause
        wait = self.initial_wait_seconds * 2 ** failures
        self.retry_waits.append(wait)
        self.sleep(wait)
        return failures + 1

    def _read(self, data: dict) -> str:
        """Store model name, fingerprint, finish reason and reasoning; return the answer text."""
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        self.last_response_model = data.get("model") or self.model
        self.last_system_fingerprint = data.get("system_fingerprint")
        reason = choice.get("finish_reason")
        self.last_finish_reason = FINISH_REASONS.get(reason, reason.upper() if reason else None)
        self.last_reasoning = message.get("reasoning")
        return message.get("content") or ""
