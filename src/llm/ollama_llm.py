"""OllamaLLM: calls a model that runs locally in Ollama (http://localhost:11434), through its REST API.

  - No API key: the model runs on this computer. Ollama must be running (it starts with Windows,
    or start it with `ollama serve`) and the model must be downloaded (`ollama pull qwen3:8b`).
  - Every setting comes from config.yaml and is sent with every request:
      temperature 0, a fixed seed (42), num_ctx (the context window in tokens: prompt + answer),
      max_tokens (num_predict: the longest answer allowed), and thinking switched OFF (think: false),
      so Qwen3 answers directly without a hidden reasoning part.
  - Fixed model version: a name like "qwen3:8b" can point to a different file after a new
    `ollama pull`. The exact file is identified by its digest (a sha256 hash). Before the first call,
    the digest of the installed model is read from Ollama (/api/tags) and compared with
    llm.ollama_model_digest in config.yaml; if they differ, the run stops. The digest is logged
    with every call (model_digest), next to the model name.
  - finish_reason: Ollama reports "stop" (answer complete) or "length" (cut off at max_tokens).
    They are written as "STOP" and "MAX_TOKENS", the same words as for Gemini, so cut-off
    answers are found the same way for every provider.
  - Errors, as for GeminiLLM:
      temporary (retried with increasing waits 2, 4, 8, ... s, llm.ollama_api_max_retries times):
        Ollama not reachable (not running), timeouts, server errors (HTTP 5xx)
      not retried: other HTTP errors such as 404 (model not downloaded)
    Every one of them ends in LLMUnavailableError, which stops the run without recording a result
    for the case, so the case stays unfinished and is continued when the command is run again.
"""

import time
from typing import Callable

import httpx

from src.llm.base_llm import LLMClient, LLMUnavailableError

# Ollama's words for why the model stopped -> the words used in the log (same as Gemini).
FINISH_REASONS = {"stop": "STOP", "length": "MAX_TOKENS"}


def is_temporary(error: Exception) -> bool:
    """True for errors worth retrying: Ollama not reachable, timeouts, server errors."""
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)  # connection refused (Ollama not running), timeouts


class OllamaLLM(LLMClient):
    """LLMClient for a local Ollama model."""

    def __init__(self, model: str, temperature: float, max_tokens: int, seed: int, num_ctx: int,
                 think: bool, expected_digest: str | None, base_url: str, timeout_seconds: float,
                 api_max_retries: int, initial_wait_seconds: float,
                 client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        """client and sleep can be replaced in tests: no real Ollama and no real waiting."""
        super().__init__(model=model, temperature=temperature)
        self.max_tokens = max_tokens
        self.seed = seed
        self.num_ctx = num_ctx
        self.think = think
        self.expected_digest = expected_digest
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.sleep = sleep
        self.retry_waits: list[float] = []   # every retry wait that happened, for inspection
        self.last_prompt_tokens: int | None = None
        self.client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)

    @classmethod
    def from_config(cls, config: dict, client: httpx.Client | None = None) -> "OllamaLLM":
        llm = config["llm"]
        return cls(llm["model"], llm["temperature"], llm["max_tokens"], llm["seed"], llm["num_ctx"],
                   llm["think"], llm["ollama_model_digest"], llm["ollama_url"], llm["ollama_timeout_seconds"],
                   llm["ollama_api_max_retries"], llm["api_initial_wait_seconds"], client=client)

    def request_body(self, prompt: str) -> dict:
        """The exact request sent to /api/chat for every call."""
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,      # one complete answer instead of pieces
            "think": self.think,  # false: no reasoning part
            "options": {"temperature": self.temperature, "seed": self.seed,
                        "num_ctx": self.num_ctx, "num_predict": self.max_tokens},
        }

    def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        """One HTTP request to Ollama, with retries on temporary errors. Returns the JSON answer."""
        for attempt in range(self.api_max_retries + 1):
            try:
                response = self.client.request(method, path, json=body)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                if not is_temporary(e):
                    raise LLMUnavailableError(f"Ollama error (not retried): {describe(e)}") from e
                if attempt == self.api_max_retries:
                    hint = " Is Ollama running? (start it with: ollama serve)" if isinstance(e, httpx.ConnectError) else ""
                    raise LLMUnavailableError(f"Ollama still failing after {self.api_max_retries} retries: "
                                              f"{describe(e)}.{hint}") from e
                wait = self.initial_wait_seconds * 2 ** attempt
                self.retry_waits.append(wait)
                self.sleep(wait)

    def check_model(self) -> None:
        """Read the digest of the installed model and stop if it is not the one fixed in config.yaml."""
        installed = {m["name"]: m["digest"] for m in self._send("GET", "/api/tags").get("models", [])}
        if self.model not in installed:
            raise LLMUnavailableError(f"Model {self.model!r} is not downloaded in Ollama "
                                      f"(installed: {sorted(installed) or 'none'}). Run: ollama pull {self.model}")
        digest = installed[self.model]
        if self.expected_digest and digest != self.expected_digest:
            raise LLMUnavailableError(f"Model {self.model!r} in Ollama has digest {digest}, but config.yaml fixes "
                                      f"{self.expected_digest} (llm.ollama_model_digest). The model was changed.")
        self.model_digest = digest

    def complete(self, prompt: str) -> str:
        if self.model_digest is None:
            self.check_model()   # once, before the first call
        data = self._send("POST", "/api/chat", self.request_body(prompt))
        self.last_response_model = data.get("model") or self.model
        self.last_prompt_tokens = data.get("prompt_eval_count")   # prompt length in the model's own tokens
        reason = data.get("done_reason")
        self.last_finish_reason = FINISH_REASONS.get(reason, reason.upper() if reason else None)
        return data.get("message", {}).get("content") or ""


def describe(error: Exception) -> str:
    """A short description of an HTTP error, including Ollama's own error message if there is one."""
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}: {error.response.text.strip()}"
    return f"{type(error).__name__}: {error}"
