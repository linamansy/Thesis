"""MockLLM: a fake LLM that returns pre-written answers.

It lets us build and test the whole pipeline without an API key and without
cost. Its answers are clearly marked as mock output in the logs (model name
"mock-llm"), so they can never be mistaken for real results.
"""

from src.llm.base_llm import LLMClient


class MockLLM(LLMClient):
    """Returns the given responses one after another.

    Example: MockLLM(["not json", '{"answer": "yes"}']) answers "not json" to
    the first call and '{"answer": "yes"}' to every later call.
    """

    MODEL_NAME = "mock-llm"

    def __init__(self, responses: list[str], temperature: float = 0):
        super().__init__(model=self.MODEL_NAME, temperature=temperature)
        if not responses:
            raise ValueError("MockLLM needs at least one response")
        self.responses = list(responses)
        self.prompts_received: list[str] = []  # lets tests check what was sent

    def complete(self, prompt: str) -> str:
        self.prompts_received.append(prompt)
        # Use the next response; once the list is used up, keep repeating the last one.
        index = min(len(self.prompts_received) - 1, len(self.responses) - 1)
        return self.responses[index]
