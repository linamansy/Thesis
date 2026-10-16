"""OllamaLLM: calls a local Ollama server (qwen3:8b) for the C3 mediation agents.

Why Ollama: the BPMN generator (BPMNGen) runs qwen3:8b on Ollama, and the mediation agents use the
SAME model, so C3 cannot win just by borrowing a stronger model's knowledge (fairness decision,
16 Oct 2026). Generator and agents share one model; only the knowledge processing differs.

  - Native endpoint POST <base_url>/api/chat, not streamed (one JSON answer).
  - Settings from config.yaml (llm section): model, temperature (0 for the agents), num_ctx
    (context window; Ollama's default is small and would silently cut long prompts), timeout.
  - Thinking is switched off ("think": false), the same choice BPMNGen makes with "/no_think".
    Any <think>...</think> block that still appears is removed before the answer is returned.
  - "format": "json" makes Ollama return a JSON object; BaseAgent still validates it with Pydantic.
  - After every answer: the model name Ollama reports -> last_response_model, and done_reason
    ("stop", or "length" when the context window was full) -> last_finish_reason; both are logged.
  - A connection error or timeout is retried (waits 2, 4, 8, ... s). If it still fails, or Ollama
    returns an HTTP error (e.g. 404 model not pulled), LLMUnavailableError stops the run without
    recording a result, exactly like the Gemini client.
"""

import re
import time
from typing import Callable

import httpx

from src.llm.base_llm import LLMClient, LLMUnavailableError

THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)


def strip_think(text: str) -> str:
    return THINK_BLOCK.sub("", text).strip()


class OllamaLLM(LLMClient):
    """LLMClient for a local Ollama server."""

    def __init__(self, model: str, temperature: float | None, base_url: str, num_ctx: int,
                 timeout_seconds: float, api_max_retries: int, initial_wait_seconds: float,
                 json_format: bool = True, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        """client and sleep can be replaced in tests: no real server and no real waiting."""
        super().__init__(model=model, temperature=temperature)
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.json_format = json_format
        self.sleep = sleep
        self.retry_waits: list[float] = []
        self.client = client or httpx.Client(timeout=timeout_seconds)
        # Token counts of the last answer (for checking the context window).
        self.last_prompt_tokens: int | None = None
        self.last_output_tokens: int | None = None

    @classmethod
    def from_config(cls, config: dict, client: httpx.Client | None = None) -> "OllamaLLM":
        llm = config["llm"]
        return cls(llm["model"], llm["temperature"], llm["ollama_base_url"], llm["ollama_num_ctx"],
                   llm["ollama_timeout_seconds"], llm["ollama_api_max_retries"], llm["api_initial_wait_seconds"],
                   client=client)

    def request_body(self, prompt: str) -> dict:
        """The exact request sent for every call."""
        options = {"num_ctx": self.num_ctx}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "stream": False, "think": False, "options": options}
        if self.json_format:
            body["format"] = "json"
        return body

    def complete(self, prompt: str) -> str:
        for attempt in range(self.api_max_retries + 1):
            try:
                response = self.client.post(f"{self.base_url}/api/chat", json=self.request_body(prompt))
            except httpx.TransportError as e:  # connection refused, timeout, network error
                if attempt == self.api_max_retries:
                    raise LLMUnavailableError(f"Ollama not reachable after {self.api_max_retries} retries "
                                              f"({self.base_url}): {type(e).__name__}: {e}") from e
                wait = self.initial_wait_seconds * 2 ** attempt
                self.retry_waits.append(wait)
                self.sleep(wait)
                continue
            if response.status_code != 200:
                raise LLMUnavailableError(f"Ollama error {response.status_code}: {response.text[:300]}")
            data = response.json()
            self.last_response_model = data.get("model") or self.model
            self.last_finish_reason = data.get("done_reason")
            self.last_prompt_tokens = data.get("prompt_eval_count")
            self.last_output_tokens = data.get("eval_count")
            return strip_think((data.get("message") or {}).get("content") or "")


def ollama_model_digest(base_url: str, model: str, client: httpx.Client | None = None) -> str | None:
    """The digest (exact version) of an installed Ollama model, from GET /api/tags; None if not found.

    A tag such as "qwen3:8b" can point to a newer file after `ollama pull`; the digest cannot.
    It is stored in run_info.json, so all parts and conditions of a run provably used the same model.
    """
    client = client or httpx.Client(timeout=30)
    try:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
    except httpx.TransportError as e:
        raise LLMUnavailableError(f"Ollama not reachable at {base_url}: {e}") from e
    for entry in response.json().get("models", []):
        if entry.get("name") == model or entry.get("model") == model:
            return entry.get("digest")
    return None
