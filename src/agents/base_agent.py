"""BaseAgent: the shared logic for every LLM-based component.

Each concrete agent (RelevanceAgent, ApplicabilityAgent, ...) inherits from
BaseAgent and only defines two things:
  1. output_schema: a Pydantic model describing the JSON the LLM must return
  2. build_prompt(): how to turn the inputs into a prompt

Everything else (calling the LLM, checking the JSON, retrying once, logging)
is written once, here.
"""

import json
import time
from abc import ABC, abstractmethod

from pydantic import BaseModel, ValidationError

from src.config import load_config
from src.llm.base_llm import LLMClient
from src.logger import RunLogger

RETRY_NOTE = (
    "\n\nYour previous answer could not be accepted: {error}\n"
    "Answer again with only a valid JSON object that matches the required format."
)


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    # Every subclass must set this to its own Pydantic model.
    output_schema: type[BaseModel]

    def __init__(self, llm: LLMClient, logger: RunLogger, max_retries: int | None = None):
        self.llm = llm
        self.logger = logger
        if max_retries is None:
            max_retries = load_config()["llm"]["max_retries"]
        self.max_retries = max_retries

    @abstractmethod
    def build_prompt(self, **inputs) -> str:
        """Turn the agent's inputs into the prompt text. Defined by each subclass."""

    def run(self, case_id: str, **inputs) -> BaseModel | None:
        """Call the LLM and return a validated output, or None if every attempt fails.

        Attempt 0 uses the normal prompt. If the answer is not valid, each retry
        sends the same prompt plus a note with the validation error.
        Every attempt is logged as its own record.
        """
        prompt = self.build_prompt(**inputs)
        current_prompt = prompt

        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            raw_output = self.llm.complete(current_prompt)
            duration = time.perf_counter() - start

            parsed, error = self.parse_output(raw_output)
            self.logger.log_call(
                case_id=case_id,
                component=type(self).__name__,
                model=self.llm.model,
                temperature=self.llm.temperature,
                prompt=current_prompt,
                raw_output=raw_output,
                parsed_output=parsed.model_dump() if parsed else None,
                valid_json=parsed is not None,
                retries=attempt,
                duration_seconds=round(duration, 4),
            )
            if parsed is not None:
                return parsed
            current_prompt = prompt + RETRY_NOTE.format(error=error)

        return None

    def parse_output(self, raw_output: str) -> tuple[BaseModel | None, str | None]:
        """Check the raw text against output_schema.

        Returns (validated object, None) on success, or (None, error message) on failure.
        """
        text = strip_code_fence(raw_output)
        try:
            data = json.loads(text)
            return self.output_schema.model_validate(data), None
        except json.JSONDecodeError as e:
            return None, f"not valid JSON ({e.msg})"
        except ValidationError as e:
            return None, f"JSON does not match the schema ({e.error_count()} error(s): {e.errors()[0]['msg']})"


def strip_code_fence(text: str) -> str:
    """Remove a surrounding ```json ... ``` block, which LLMs often add around JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
