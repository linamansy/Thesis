"""AnthropicLLM: calls the real Claude API through the official anthropic SDK.

  - The API key is read from the .env file (ANTHROPIC_API_KEY); it never appears in code.
    If it is missing, the program stops with a clear message.
  - Model name, temperature and max_tokens come from config.yaml. The temperature is only
    sent when config.yaml gives one (temperature: null leaves it out).
  - After every answer, the exact model string returned by the API is stored in
    last_response_model, and BaseAgent writes it to the log.
  - Temporary API errors (rate limit, overload, server errors, timeouts, connection
    problems) are retried with increasing waits: 2, 4, 8, 16, 32 seconds (up to 5 retries,
    numbers from config.yaml).
  - Every API error ends in LLMUnavailableError, which stops the run without recording a result
    for the case: a temporary error that still fails after all retries, and any other API error
    (e.g. a bad request or an unknown model) at once, without retrying.
    This is separate from BaseAgent's single retry for invalid JSON: an API retry repeats
    the identical request because the server did not answer, a JSON retry asks again
    because the answer was unusable.
  - The SDK's own automatic retries are switched off (max_retries=0) so that only the
    retries described here happen, and each one is recorded in retry_waits.
"""

import os
import time
from typing import Callable

import anthropic
from dotenv import load_dotenv

from src.config import project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError

PLACEHOLDER_MODEL = "MODEL_NAME_PLACEHOLDER"

# Errors that are worth retrying because they are temporary.
RETRYABLE_ERRORS = (
    anthropic.RateLimitError,           # 429: too many requests
    anthropic.OverloadedError,          # 529: API temporarily overloaded
    anthropic.ServiceUnavailableError,  # 503
    anthropic.InternalServerError,      # other 5xx server errors
    anthropic.APIConnectionError,       # network problems, including APITimeoutError
)


class MissingAPIKeyError(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is not set."""


class AnthropicLLM(LLMClient):
    """LLMClient for the Anthropic Messages API."""

    def __init__(self, model: str, temperature: float | None, max_tokens: int,
                 api_max_retries: int, initial_wait_seconds: float,
                 client=None, sleep: Callable[[float], None] = time.sleep):
        """client and sleep can be replaced in tests, so no real API call and no real waiting happens."""
        super().__init__(model=model, temperature=temperature)
        if not model or model == PLACEHOLDER_MODEL:
            raise ValueError("Set model.name in config.yaml to a real Claude model id before using the Anthropic API.")
        self.max_tokens = max_tokens
        self.api_max_retries = api_max_retries
        self.initial_wait_seconds = initial_wait_seconds
        self.sleep = sleep
        self.retry_waits: list[float] = []      # every wait that happened, for inspection
        self.last_stop_reason: str | None = None
        if client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise MissingAPIKeyError(
                    "ANTHROPIC_API_KEY is not set. Create a file .env in the project root (see .env.example) "
                    "with the line ANTHROPIC_API_KEY=<your key>, or set model.provider to mock in config.yaml.")
            client = anthropic.Anthropic(api_key=api_key, max_retries=0)
        self.client = client

    @classmethod
    def from_config(cls, config: dict, client=None) -> "AnthropicLLM":
        load_dotenv(project_path(config["paths"]["env_file"]))  # puts ANTHROPIC_API_KEY into the environment
        llm = config["llm"]
        return cls(config["model"]["name"], llm["temperature"], llm["max_tokens"], llm["api_max_retries"],
                   llm["api_initial_wait_seconds"], client=client)

    def request(self, prompt: str) -> dict:
        """The exact parameters sent to the API for one prompt."""
        params = {"model": self.model, "max_tokens": self.max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if self.temperature is not None:
            params["temperature"] = self.temperature
        return params

    def complete(self, prompt: str) -> str:
        params = self.request(prompt)
        for attempt in range(self.api_max_retries + 1):
            try:
                response = self.client.messages.create(**params)
            except RETRYABLE_ERRORS as e:
                if attempt == self.api_max_retries:
                    raise LLMUnavailableError(f"Anthropic API still failing after {self.api_max_retries} retries: "
                                              f"{type(e).__name__}: {e}") from e
                wait = self.initial_wait_seconds * 2 ** attempt
                self.retry_waits.append(wait)
                self.sleep(wait)
                continue
            except anthropic.APIError as e:  # any other API error: not retried
                raise LLMUnavailableError(f"Anthropic API error (not retried): {type(e).__name__}: {e}") from e
            self.last_response_model = response.model
            self.last_stop_reason = response.stop_reason
            # Only text blocks form the answer (thinking blocks, if any, are not part of it).
            return "".join(block.text for block in response.content if block.type == "text")
