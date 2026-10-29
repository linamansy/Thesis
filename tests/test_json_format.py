"""Fix 1 (Study 2 debugging): Ollama structured output ("format").

The JSON agents of Study 2 send their output schema as Ollama's "format"; every other call (Study 1 agents, silver
annotator, legacy generator) sends no "format" key; the BPMNGen generator request is not touched.
"""

import re
from pathlib import Path

import pytest

from src.agents.applicability_agent_v2 import CheckIfCallV2, SecondLookCallV2, SplitCallV2
from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent import RequirementAgent
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.agents.silver_annotator import SilverAnnotator
from src.generator import BPMNGenerator
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.rag_v3_steps import RoutingAgent, StepsAgent
from tests.test_ollama_llm import Agent, FakeClient, chat, make_llm

JSON_AGENTS = [StepsAgent, RoutingAgent, RelevanceAgentV2, SplitCallV2, CheckIfCallV2, SecondLookCallV2,
               RequirementAgentV2]
OTHER_AGENTS = [RelevanceAgent, ApplicabilityAgent, RequirementAgent, SilverAnnotator, BPMNGenerator]


def test_only_the_study2_json_agents_ask_for_a_schema():
    assert all(agent.json_format for agent in JSON_AGENTS)
    assert not any(agent.json_format for agent in OTHER_AGENTS)


def test_ollama_adds_format_only_when_a_schema_is_given():
    client = FakeClient(chat(), chat())
    llm, _ = make_llm(client)
    llm.complete("p")
    llm.complete("p", format_schema={"type": "object"})
    plain, with_schema = client.chat_calls()
    assert "format" not in plain
    assert with_schema["format"] == {"type": "object"}
    assert {k: v for k, v in with_schema.items() if k != "format"} == plain   # nothing else changes


def test_json_agent_sends_exactly_its_output_schema(tmp_path):
    client = FakeClient(chat())
    llm, _ = make_llm(client)
    agent = Agent(llm, RunLogger(tmp_path, "C3", "test"), max_retries=0)
    agent.json_format = True
    agent.run(case_id="01", question="?")
    assert client.chat_calls()[0]["format"] == agent.output_schema.model_json_schema()


def test_agent_without_json_format_sends_no_format_key(tmp_path):
    client = FakeClient(chat())
    llm, _ = make_llm(client)
    Agent(llm, RunLogger(tmp_path, "C3", "test"), max_retries=0).run(case_id="01", question="?")
    assert "format" not in client.chat_calls()[0]


@pytest.mark.parametrize("agent_class", [StepsAgent, RoutingAgent, RelevanceAgentV2, RequirementAgentV2,
                                         CheckIfCallV2, SecondLookCallV2])
def test_schema_has_the_fields_the_parser_expects(tmp_path, agent_class):
    agent = agent_class(MockLLM(["{}"]), RunLogger(tmp_path, "C3", "test"), max_retries=0)
    schema = agent.format_schema()
    assert set(schema["properties"]) == {f.alias or name for name, f in agent.output_schema.model_fields.items()}
    assert set(schema["required"]) == set(schema["properties"])


def test_split_schema_uses_the_parsers_names_and_the_laws_roles(tmp_path):
    llm = MockLLM(["{}"])
    agent = SplitCallV2(llm, RunLogger(tmp_path, "C3", "test"), max_retries=0)
    agent.run(case_id="01", passage_id="GDPR-Art13-1", passage_text="text")
    schema = llm.schemas_received[0]
    assert set(schema["properties"]) == {"roles", "if", "then", "exceptions"}   # "if" as the parser reads it
    assert schema == agent.output_schema.model_json_schema()


def test_provider_without_format_support_gets_the_plain_call(tmp_path):
    class PlainLLM(MockLLM):
        accepts_format_schema = False

        def complete(self, prompt):   # the old signature: no format_schema
            return super().complete(prompt)

    llm = PlainLLM(['{"answer": "yes"}'])
    agent = Agent(llm, RunLogger(tmp_path, "C3", "test"), max_retries=0)
    agent.json_format = True
    assert agent.run(case_id="01", question="?").answer == "yes"
    assert llm.schemas_received == [None]


def test_generator_request_is_unchanged():
    """The BPMNGen harness changes BPMNGen's request only by think; it never adds "format"."""
    harness = Path(__file__).resolve().parents[1] / "bpmngen_harness" / "run_bpmngen.ts"
    text = harness.read_text(encoding="utf-8")
    assert re.findall(r"(?<![\w.])body\.(\w+)\s*=(?!=)", text) == ["think"]
