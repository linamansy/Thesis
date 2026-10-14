"""LLMClient: the common interface that every LLM provider must offer.

Agents only talk to this interface. Whether the answer comes from MockLLM or
from the real Anthropic API, the agent code stays exactly the same.
"""

from abc import ABC, abstractmethod


class LLMUnavailableError(RuntimeError):
    """The LLM API could not be reached even after all API retries (e.g. the daily free-tier limit is used up).

    This is NOT a result of the experiment: the run stops, the current case stays unfinished,
    and rerunning the same command later continues from that case (see src/run_folder.py).
    """


class LLMClient(ABC):
    """Abstract base class for all LLM providers.

    "Abstract" means you cannot use this class directly; you must use a
    subclass (such as MockLLM) that fills in the complete() method.
    """

    def __init__(self, model: str, temperature: float | None):
        self.model = model              # the model name requested (from config.yaml)
        self.temperature = temperature  # 0 in this project, read from config.yaml (None = not sent)
        # The exact model string the provider reported for the last answer. Written to the log;
        # stays None for providers that do not report one (then the requested name is logged).
        self.last_response_model: str | None = None
        # Why the model stopped on the last answer (e.g. "STOP", "MAX_TOKENS"); None if not reported.
        self.last_finish_reason: str | None = None

    @property
    def model_for_log(self) -> str:
        """The model name written to the log: the provider's answer if known, else the requested name."""
        return self.last_response_model or self.model

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send the prompt to the LLM and return its raw text answer."""
