"""BaseAgent: the shared logic for every LLM-based component.

Each concrete agent (RelevanceAgent, ApplicabilityAgent, ...) inherits from
BaseAgent and only defines:
  1. output_schema: a Pydantic model describing the JSON the LLM must return
  2. prompt_key: the name of its prompt template file in config.yaml (paths section)
  3. build_prompt(): how to fill the template with the inputs

Everything else (loading the template, calling the LLM, checking the JSON,
retrying once, logging) is written once, here.
"""

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ValidationError

from src.config import load_config, project_path
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
    # Key under "paths" in config.yaml that points to the agent's prompt template file.
    prompt_key: str | None = None

    def __init__(self, llm: LLMClient, logger: RunLogger, max_retries: int | None = None,
                 template_path: Path | None = None):
        self.llm = llm
        self.logger = logger
        config = load_config()
        if max_retries is None:
            max_retries = config["llm"]["max_retries"]
        self.max_retries = max_retries
        if template_path is None and self.prompt_key:
            template_path = project_path(config["paths"][self.prompt_key])
        self.template = Path(template_path).read_text(encoding="utf-8") if template_path else None

    def schema_text(self) -> str:
        """The output schema as indented JSON, for the {schema} part of a prompt template."""
        return json.dumps(self.output_schema.model_json_schema(), indent=2)

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
                model=self.llm.model_for_log,  # the exact model string the API returned, if any
                temperature=self.llm.temperature,
                prompt=current_prompt,
                raw_output=raw_output,
                parsed_output=parsed.model_dump() if parsed else None,
                valid_json=parsed is not None,
                retries=attempt,
                duration_seconds=round(duration, 4),
                finish_reason=self.llm.last_finish_reason,
                model_digest=self.llm.model_digest,
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
