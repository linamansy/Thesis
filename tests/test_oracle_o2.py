"""scripts/oracle_o2.py (fix nodoc): real classes only, and the target's whole article from the corpus as input."""

from pathlib import Path

from scripts.oracle_o2 import TARGET, article_ids
from src.agents.applicability_agent_v2 import article_of
from src.config import load_config


def test_input_is_the_target_and_every_other_paragraph_of_its_article():
    ids = article_ids(load_config(), TARGET)
    assert ids[0] == TARGET and len(ids) == len(set(ids)) > 1
    assert all(article_of(i) == article_of(TARGET) for i in ids)


def test_no_redefined_schema_or_patch():
    source = Path("scripts/oracle_o2.py").read_text(encoding="utf-8")
    for forbidden in ("class ItemCheck", "BaseModel", "output_schema =", "OllamaLLM.complete =", ".run ="):
        assert forbidden not in source


# ---------- --think-calls (setting B, debug only) ----------

import json

import httpx
import pytest

from scripts.oracle_o2 import ThinkingOllamaLLM, give_thinking, thinking_llm
from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger


def test_give_thinking_changes_only_the_named_calls(tmp_path):
    base, think = MockLLM(["{}"]), MockLLM(["{}"])
    agent = ApplicabilityAgentV2(base, RunLogger(tmp_path, "DEBUG", "t"))
    give_thinking(agent, ["CheckIfCallV2", "SecondLookCallV2"], think)
    assert agent.check_call.llm is think and agent.second_look_call.llm is think and agent.split_call.llm is base


def test_give_thinking_refuses_an_unknown_call(tmp_path):
    agent = ApplicabilityAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "DEBUG", "t"))
    with pytest.raises(ValueError, match="NoSuchCall"):
        give_thinking(agent, ["NoSuchCall"], MockLLM(["{}"]))


def test_thinking_client_sends_think_true_and_keeps_the_thinking_text():
    llm = thinking_llm(load_config())
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"model": llm.model, "done_reason": "stop",
                                         "message": {"content": "{}", "thinking": "step by step"}})
    llm.client = httpx.Client(base_url="http://ollama.test", transport=httpx.MockTransport(handle))
    llm.model_digest = "known"   # skip the digest check: no real Ollama
    assert isinstance(llm, ThinkingOllamaLLM) and llm.complete("p", format_schema={"type": "object"}) == "{}"
    body = sent[0]
    assert body["think"] is True and body["options"]["temperature"] == load_config()["llm"]["temperature"]
    assert llm.last_reasoning == "step by step"


def test_without_think_calls_the_requests_are_unchanged():
    source = Path("scripts/oracle_o2.py").read_text(encoding="utf-8")
    assert "if think_calls:\n        give_thinking(" in source and 'default=""' in source
