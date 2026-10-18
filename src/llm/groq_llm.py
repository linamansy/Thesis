"""GroqLLM: calls a model on Groq's free API (OpenAI-compatible chat completions), used ONLY for the silver
reference annotator (src/build_silver_reference.py). The generator and the C3 agents never use it.

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
  - Server errors (5xx), timeouts and network errors are retried with increasing waits (2, 4, 8, ... s,
    silver.groq_api_max_retries times). Other errors (e.g. 401 wrong key, 404 unknown model) stop at once.
"""

import os
import re
import time
from typing import Callable

import httpx
from dotenv import load_dotenv

from src.config import project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError

FINISH_REASONS = {"stop": "STOP", "length": "MAX_TOKENS"}  # same words as for Gemini and Ollama
MAX_RATE_LIMIT_WAITS = 100   # safety stop: a call that keeps getting 429 is given up after this many waits


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


class GroqLLM(LLMClient):
    """LLMClient for Groq's OpenAI-compatible chat completions API."""

    def __init__(self, model: str, temperature: float, max_tokens: int, api_max_retries: int,
                 initial_wait_seconds: float, max_rate_limit_wait_seconds: float, base_url: str,
                 timeout_seconds: float, api_key: str | None = None, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        """client and sleep can be replaced in tests: no real API call and no real waiting."""
        super().__init__(model=model, temperature=temperature)
        self.max_tokens = max_tokens
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.max_rate_limit_wait_seconds = max_rate_limit_wait_seconds
        self.sleep = sleep
        self.retry_waits: list[float] = []       # waits after server errors / timeouts (counted as retries)
        self.rate_limit_waits: list[float] = []  # waits after 429 (not counted)
        self.last_system_fingerprint: str | None = None
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
                   silver["groq_base_url"], silver["groq_timeout_seconds"], client=client)

    def request_body(self, prompt: str) -> dict:
        """The exact request sent for every call."""
        return {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature, "max_tokens": self.max_tokens}

    def complete(self, prompt: str) -> str:
        failures = waits = 0   # for this call: counted failures, and rate-limit waits (not counted as failures)
        for _ in range(MAX_RATE_LIMIT_WAITS + self.api_max_retries + 1):
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
                if waits > MAX_RATE_LIMIT_WAITS:
                    raise LLMUnavailableError(f"Groq rate limit: more than {MAX_RATE_LIMIT_WAITS} waits for one call")
                self.rate_limit_waits.append(wait)
                self.sleep(wait)
                continue
            if response.status_code >= 500:  # server error: a counted retry
                failures = self._count_failure(failures, f"HTTP {response.status_code}: {response.text[:300]}")
                continue
            if response.status_code != 200:   # e.g. 401 wrong key, 404 unknown model, 413 request too large
                raise LLMUnavailableError(f"Groq API error (not retried): HTTP {response.status_code}: "
                                          f"{response.text[:500]}")
            return self._read(response.json())
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
