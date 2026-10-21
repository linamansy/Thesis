"""OpenRouterLLM: calls a model on OpenRouter (OpenAI-compatible chat completions). STUDY 2 only: the C3 mediation
agents use it when config.yaml model.provider is "openrouter", so they use the SAME model as the generator
(BPMNGen's server route with an OpenRouter model, src/bpmngen_server_generator.py; decision 16 Oct 2026).

  - The API key is read from the .env file (OPENROUTER_API_KEY); it never appears in code.
  - The model is model.name; temperature (0), max_tokens and seed come from the llm section, as for the other
    agent clients. Thinking is switched off with OpenRouter's reasoning switch (openrouter.reasoning_enabled).
  - After every answer, the exact model name OpenRouter returns is stored in last_response_model (written to the
    log), the provider that served it (OpenRouter routes one model to several providers) in last_upstream_provider,
    and any reasoning text in last_reasoning (written to the log), so every output is saved.
  - Errors: rate limits (429), server errors (5xx), timeouts and network errors are retried with increasing waits
    (2, 4, 8, ... s, openrouter.api_max_retries times). Other errors (e.g. 401 wrong key, 402 no credit,
    404 unknown model) stop at once. Every one ends in LLMUnavailableError: the run stops without recording a
    result, and the case is continued when the command is run again.
"""

import os
import time
from typing import Callable

import httpx
from dotenv import load_dotenv

from src.config import project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError

FINISH_REASONS = {"stop": "STOP", "length": "MAX_TOKENS"}  # same words as for Gemini, Ollama and Groq


class MissingOpenRouterKeyError(RuntimeError):
    """Raised when OPENROUTER_API_KEY is not set."""


class OpenRouterLLM(LLMClient):
    """LLMClient for OpenRouter's OpenAI-compatible chat completions API."""

    def __init__(self, model: str, temperature: float, max_tokens: int, seed: int, reasoning_enabled: bool,
                 base_url: str, timeout_seconds: float, api_max_retries: int, initial_wait_seconds: float,
                 api_key: str | None = None, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        """client and sleep can be replaced in tests: no real API call and no real waiting."""
        super().__init__(model=model, temperature=temperature)
        self.max_tokens = max_tokens
        self.seed = seed
        self.reasoning_enabled = reasoning_enabled
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.sleep = sleep
        self.retry_waits: list[float] = []   # every retry wait that happened, for inspection
        self.last_upstream_provider: str | None = None
        if client is None:
            api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
            if not api_key:
                raise MissingOpenRouterKeyError("OPENROUTER_API_KEY is not set. Add the line "
                                                "OPENROUTER_API_KEY=<your key> to the .env file in the project root.")
            client = httpx.Client(base_url=base_url, timeout=timeout_seconds,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self.client = client

    @classmethod
    def from_config(cls, config: dict, client: httpx.Client | None = None) -> "OpenRouterLLM":
        load_dotenv(project_path(config["paths"]["env_file"]))  # puts OPENROUTER_API_KEY into the environment
        model, llm, openrouter = config["model"], config["llm"], config["openrouter"]
        return cls(model["name"], llm["temperature"], llm["max_tokens"], llm["seed"], openrouter["reasoning_enabled"],
                   openrouter["base_url"], openrouter["timeout_seconds"], openrouter["api_max_retries"],
                   llm["api_initial_wait_seconds"], client=client)

    def request_body(self, prompt: str) -> dict:
        """The exact request sent for every call."""
        return {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature, "max_tokens": self.max_tokens, "seed": self.seed,
                "reasoning": {"enabled": self.reasoning_enabled}}

    def complete(self, prompt: str) -> str:
        failures = 0
        while True:
            try:
                response = self.client.post("/chat/completions", json=self.request_body(prompt))
            except httpx.TransportError as e:  # timeout or network error
                failures = self._count_failure(failures, f"{type(e).__name__}: {e}", e)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                failures = self._count_failure(failures, f"HTTP {response.status_code}: {response.text[:300]}")
                continue
            if response.status_code != 200:   # e.g. 401 wrong key, 402 no credit, 404 unknown model
                raise LLMUnavailableError(f"OpenRouter API error (not retried): HTTP {response.status_code}: "
                                          f"{response.text[:500]}")
            data = response.json()
            error = data.get("error")
            if error:  # OpenRouter can answer 200 with an error from the provider
                code = error.get("code") if isinstance(error, dict) else None
                if isinstance(code, int) and (code == 429 or code >= 500):
                    failures = self._count_failure(failures, f"provider error {code}: {str(error)[:300]}")
                    continue
                raise LLMUnavailableError(f"OpenRouter provider error (not retried): {str(error)[:500]}")
            return self._read(data)

    def _count_failure(self, failures: int, text: str, cause: Exception | None = None) -> int:
        if failures == self.api_max_retries:
            raise LLMUnavailableError(f"OpenRouter API still failing after {self.api_max_retries} retries: "
                                      f"{text}") from cause
        wait = self.initial_wait_seconds * 2 ** failures
        self.retry_waits.append(wait)
        self.sleep(wait)
        return failures + 1

    def _read(self, data: dict) -> str:
        """Store the exact model name, provider, finish reason and reasoning; return the answer text."""
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        self.last_response_model = data.get("model") or self.model
        self.last_upstream_provider = data.get("provider")
        reason = choice.get("finish_reason")
        self.last_finish_reason = FINISH_REASONS.get(reason, reason.upper() if reason else None)
        self.last_reasoning = message.get("reasoning")
        return message.get("content") or ""
