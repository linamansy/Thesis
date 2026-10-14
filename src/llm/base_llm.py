"""LLMClient: the common interface that every LLM provider must offer.

Agents only talk to this interface. Whether the answer comes from MockLLM or
from the real Anthropic API, the agent code stays exactly the same.
"""

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Abstract base class for all LLM providers.

    "Abstract" means you cannot use this class directly; you must use a
    subclass (such as MockLLM) that fills in the complete() method.
    """

    def __init__(self, model: str, temperature: float):
        self.model = model              # model name and version, written to every log record
        self.temperature = temperature  # 0 in this project, read from config.yaml

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send the prompt to the LLM and return its raw text answer."""
