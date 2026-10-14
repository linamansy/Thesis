"""GeminiLLM: calls Google's Gemini API (free tier) through the official google-genai library.

  - The API key is read from the .env file (GEMINI_API_KEY); it never appears in code.
    If it is missing, the program stops with a clear message.
  - Model name, temperature (0) and max_tokens come from config.yaml. The model must be a fixed
    model version, so that all runs use exactly the same model.
  - After every answer, the exact model version returned by the API (response.model_version)
    is stored in last_response_model, and BaseAgent writes it to the log.
  - Pause between calls: the free tier allows only a limited number of requests per minute.
    llm.gemini_pause_between_calls_seconds makes sure at least that many seconds pass between
    the start of two calls (0 = no pause).
  - Temporary API errors are retried with increasing waits (2, 4, 8, ... seconds; the number of retries is llm.gemini_api_max_retries):
      429 / RESOURCE_EXHAUSTED   rate limit or quota
      500 / 502 / 503 / 504      server error, overload (UNAVAILABLE), timeout on the server side
      network errors and timeouts on our side (httpx)
  - Every API error ends in LLMUnavailableError, which stops the run without recording a result
    for the case, so the case stays unfinished and can be resumed later:
      - a temporary error that still fails after all retries (e.g. the daily free-tier limit);
      - any other API error at once, without retrying (e.g. 404 model not found, 400 bad request,
        wrong key). Such an error is about the API call, not an answer of the model.
  - The library's own automatic retries are switched off, so only the retries described here happen.
"""

import os
import time
from typing import Callable

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from src.config import project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError

PLACEHOLDER_MODEL = "MODEL_NAME_PLACEHOLDER"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class MissingGeminiKeyError(RuntimeError):
    """Raised when GEMINI_API_KEY is not set."""


def is_temporary(error: Exception) -> bool:
    """True for errors worth retrying: rate limit/quota, overload, server errors, timeouts, network errors."""
    if isinstance(error, errors.APIError):
        return error.code in RETRYABLE_STATUS_CODES or error.status in ("RESOURCE_EXHAUSTED", "UNAVAILABLE")
    return isinstance(error, httpx.TransportError)  # includes httpx.TimeoutException and connection errors


class GeminiLLM(LLMClient):
    """LLMClient for the Gemini API."""

    def __init__(self, model: str, temperature: float | None, max_tokens: int, api_max_retries: int,
                 initial_wait_seconds: float, pause_between_calls_seconds: float = 0,
                 client=None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        """client, sleep and clock can be replaced in tests: no real API call and no real waiting."""
        super().__init__(model=model, temperature=temperature)
        if not model or model == PLACEHOLDER_MODEL:
            raise ValueError("Set llm.model in config.yaml to a fixed Gemini model version before using the API.")
        self.max_tokens = max_tokens
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.pause_between_calls_seconds = pause_between_calls_seconds
        self.sleep = sleep
        self.clock = clock
        self.retry_waits: list[float] = []   # every retry wait that happened, for inspection
        self.pause_waits: list[float] = []   # every pause between calls that happened
        self.last_call_started: float | None = None
        if client is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise MissingGeminiKeyError(
                    "GEMINI_API_KEY is not set. Add the line GEMINI_API_KEY=<your key> to the .env file in the "
                    "project root (see .env.example), or set llm.provider to mock in config.yaml.")
            no_retries = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
            client = genai.Client(api_key=api_key, http_options=no_retries)
        self.client = client

    @classmethod
    def from_config(cls, config: dict, client=None) -> "GeminiLLM":
        load_dotenv(project_path(config["paths"]["env_file"]))  # puts GEMINI_API_KEY into the environment
        llm = config["llm"]
        return cls(llm["model"], llm["temperature"], llm["max_tokens"], llm["gemini_api_max_retries"],
                   llm["api_initial_wait_seconds"], llm["gemini_pause_between_calls_seconds"], client=client)

    def generation_config(self) -> types.GenerateContentConfig:
        """The exact generation settings sent with every request."""
        return types.GenerateContentConfig(temperature=self.temperature, max_output_tokens=self.max_tokens)

    def _pause(self) -> None:
        """Wait so that at least pause_between_calls_seconds pass between the starts of two calls."""
        if self.pause_between_calls_seconds and self.last_call_started is not None:
            remaining = self.pause_between_calls_seconds - (self.clock() - self.last_call_started)
            if remaining > 0:
                self.pause_waits.append(remaining)
                self.sleep(remaining)
        self.last_call_started = self.clock()

    def complete(self, prompt: str) -> str:
        for attempt in range(self.api_max_retries + 1):
            self._pause()
            try:
                response = self.client.models.generate_content(model=self.model, contents=prompt,
                                                               config=self.generation_config())
            except Exception as e:
                if isinstance(e, errors.APIError) and not is_temporary(e):
                    raise LLMUnavailableError(f"Gemini API error (not retried): {type(e).__name__}: {e}") from e
                if not is_temporary(e):
                    raise  # not an API error (e.g. a bug in our code): raised unchanged
                if attempt == self.api_max_retries:
                    raise LLMUnavailableError(f"Gemini API still failing after {self.api_max_retries} retries: "
                                              f"{type(e).__name__}: {e}") from e
                wait = self.initial_wait_seconds * 2 ** attempt
                self.retry_waits.append(wait)
                self.sleep(wait)
                continue
            self.last_response_model = response.model_version or self.model
            candidates = response.candidates or []
            reason = candidates[0].finish_reason if candidates else None
            # The library gives an enum (FinishReason.STOP); its .name is the plain word "STOP".
            self.last_finish_reason = getattr(reason, "name", None) or (str(reason) if reason else None)
            # response.text is None when the answer was blocked or empty; BaseAgent then treats it as invalid.
            return response.text or ""
