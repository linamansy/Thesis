"""Oracle experiment O2: 01.2, LPD-Art3-1 only, settings A-D, 3 runs each (results/debug/01.2/med_o2_*).

Run on commit da013b1, before fix C. Setting C won and became the real fix (commit 7e5680b), so after that commit
setting A already has the search-first schema and the ORDER patch below changes nothing.


A current (fix 2); B think on for CheckIfCallV2 + SecondLookCallV2; C closest_sentence before status/quote in the item
schema of both calls; D = B + C. Everything else is scripts.debug_mediation_on_passages unchanged.
Usage (from the project folder): .venv/Scripts/python.exe <this file> A|B|C|D
"""
import json
import sys
import time

sys.path.insert(0, ".")
from pydantic import BaseModel, Field

import scripts.debug_mediation_on_passages as med
from src.agents import applicability_agent_v2 as ap
from src.llm.ollama_llm import FINISH_REASONS, OllamaLLM

setting = sys.argv[1]
THINK = setting in ("B", "D")
ORDER = setting in ("C", "D")


# B: OllamaLLM.complete that also keeps Ollama's thinking text (logged as "reasoning")
def complete(self, prompt, format_schema=None):
    if self.model_digest is None:
        self.check_model()
    data = self._send("POST", "/api/chat", self.request_body(prompt, format_schema))
    self.last_response_model = data.get("model") or self.model
    self.last_prompt_tokens = data.get("prompt_eval_count")
    reason = data.get("done_reason")
    self.last_finish_reason = FINISH_REASONS.get(reason, reason.upper() if reason else None)
    self.last_reasoning = data.get("message", {}).get("thinking")
    return data.get("message", {}).get("content") or ""


OllamaLLM.complete = complete

if THINK:
    original_run = ap.ItemCheckCall.run

    def run_with_think(self, case_id, **inputs):
        self.llm.think = True
        try:
            return original_run(self, case_id, **inputs)
        finally:
            self.llm.think = False

    ap.ItemCheckCall.run = run_with_think

if ORDER:
    class ItemCheck(BaseModel):
        id: str = Field(description="The id of the item, as given in the list")
        closest_sentence: str | None = Field(description="The sentence of the process description that comes closest "
                                                         "to the statement, copied word for word, or null if none")
        status: ap.Status = Field(description="confirmed, contradicted or not_stated, judged from the description only")
        quote: str | None = Field(description="Exact words copied from the process description, or null for not_stated")

    class CheckOutputV2(BaseModel):
        results: list[ItemCheck] = Field(description="One result for every item of the list")

    ap.ItemCheckCall.output_schema = CheckOutputV2

start = time.perf_counter()
med.main(["--variant", "01.2", "--label", f"o2_{setting}", "--passages", "LPD-Art3-1", "--runs", "3"])
print(json.dumps({"setting": setting, "seconds": round(time.perf_counter() - start, 1)}))
