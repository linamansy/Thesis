"""Tests for RelevanceAgent, ApplicabilityAgent and RequirementAgent, using MockLLM with prepared answers."""

import json

import pytest

from src.agents.applicability_agent import ApplicabilityAgent, ApplicabilityOutput
from src.agents.relevance_agent import RelevanceAgent, RelevanceOutput
from src.agents.requirement_agent import RequirementAgent, RequirementOutput
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger

CONFIG = load_config()
DESCRIPTION = (project_path(CONFIG["paths"]["cases"]) / "19" / "description.txt").read_text(encoding="utf-8")
FROZEN = json.loads(project_path(CONFIG["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))
PASSAGE = next(p for p in FROZEN["cases"]["19"]["passages"] if p["passage_id"] == "CRD-Art8-2")
PASSAGE_INPUT = {"passage_id": PASSAGE["passage_id"], "passage_text": PASSAGE["text"]}

RELEVANCE_ANSWER = {
    "relevant": True,
    "reason": "The process is an online purchase that obliges the user to pay, which is what the passage regulates.",
    "evidence_process": "Consider a process for purchasing items from an online shop.",
    "evidence_passage": "places the consumer under an obligation to pay",
}
APPLICABILITY_ANSWER = {
    "conditions": [
        {"condition": "The contract is a distance contract concluded by electronic means",
         "status": "satisfied", "evidence": "purchasing items from an online shop"},
        {"condition": "The contract places the consumer under an obligation to pay",
         "status": "satisfied", "evidence": "the user either pays or completes an installment agreement"},
        {"condition": "The buyer is a consumer", "status": "not_stated", "evidence": None},
    ]
}
REQUIREMENT_ANSWER = {
    "actor": "the trader",
    "action": "ensure that the consumer explicitly acknowledges that the order implies an obligation to pay",
    "condition": "a distance contract concluded by electronic means places the consumer under an obligation to pay",
    "ordering": "directly before the user places the order",
}


def make(agent_class, tmp_path, *answers):
    responses = [a if isinstance(a, str) else json.dumps(a) for a in answers]
    logger = RunLogger(tmp_path, "C3", "test")
    return agent_class(MockLLM(responses), logger), logger


def log_records(logger):
    return [json.loads(line) for line in open(logger.log_path, encoding="utf-8")]


# ---------- RelevanceAgent ----------

def test_relevance_agent_parses_answer_and_logs(tmp_path):
    agent, logger = make(RelevanceAgent, tmp_path, RELEVANCE_ANSWER)
    result = agent.run(case_id="19", description=DESCRIPTION, **PASSAGE_INPUT)

    assert result == RelevanceOutput(**RELEVANCE_ANSWER)
    record = log_records(logger)[0]
    assert record["component"] == "RelevanceAgent" and record["case_id"] == "19"


def test_relevance_prompt_contains_both_texts_and_schema(tmp_path):
    agent, _ = make(RelevanceAgent, tmp_path, RELEVANCE_ANSWER)
    prompt = agent.build_prompt(description=DESCRIPTION, **PASSAGE_INPUT)
    assert "The user starts an order by logging in to their account." in prompt
    assert f"[CRD-Art8-2] {PASSAGE['text']}" in prompt
    assert '"evidence_passage"' in prompt
    assert prompt.index("PROCESS DESCRIPTION") < prompt.index("LEGAL PASSAGE")


def test_relevance_irrelevant_answer_with_null_evidence(tmp_path):
    answer = {"relevant": False, "reason": "The passage is about telephone sales.",
              "evidence_process": None, "evidence_passage": None}
    agent, _ = make(RelevanceAgent, tmp_path, answer)
    assert agent.run(case_id="19", description=DESCRIPTION, **PASSAGE_INPUT).relevant is False


def test_relevance_retries_once_on_invalid_answer(tmp_path):
    agent, logger = make(RelevanceAgent, tmp_path, '{"relevant": "maybe"}', RELEVANCE_ANSWER)
    assert agent.run(case_id="19", description=DESCRIPTION, **PASSAGE_INPUT).relevant is True
    assert [r["valid_json"] for r in log_records(logger)] == [False, True]


# ---------- ApplicabilityAgent ----------

def test_applicability_agent_parses_conditions(tmp_path):
    agent, _ = make(ApplicabilityAgent, tmp_path, APPLICABILITY_ANSWER)
    result = agent.run(case_id="19", description=DESCRIPTION, **PASSAGE_INPUT)

    assert isinstance(result, ApplicabilityOutput)
    assert [c.status for c in result.conditions] == ["satisfied", "satisfied", "not_stated"]
    assert result.conditions[2].evidence is None


def test_applicability_rejects_unknown_status_and_empty_list(tmp_path):
    bad_status = {"conditions": [{"condition": "x", "status": "probably", "evidence": None}]}
    agent, logger = make(ApplicabilityAgent, tmp_path, bad_status, {"conditions": []})
    assert agent.run(case_id="19", description=DESCRIPTION, **PASSAGE_INPUT) is None  # both attempts invalid
    assert [r["valid_json"] for r in log_records(logger)] == [False, False]


def test_applicability_prompt_explains_statuses_and_exact_quotes(tmp_path):
    agent, _ = make(ApplicabilityAgent, tmp_path, APPLICABILITY_ANSWER)
    prompt = agent.build_prompt(description=DESCRIPTION, **PASSAGE_INPUT)
    for word in ('"satisfied"', '"contradicted"', '"not_stated"', "word for word"):
        assert word in prompt


def test_applicability_prompt_revision(tmp_path):
    agent, _ = make(ApplicabilityAgent, tmp_path, APPLICABILITY_ANSWER)
    prompt = agent.build_prompt(description=DESCRIPTION, **PASSAGE_INPUT)
    assert ('"satisfied": the description states that the condition holds, in the same or different words. '
            'Example: "orders through an online shop" satisfies "contract concluded by electronic means at a '
            'distance".') in prompt
    assert '"a customer" does not show that the buyer is a "consumer"' in prompt
    assert "write the exception as a condition that must not be the case" in prompt
    instructions = prompt.split("JSON SCHEMA")[0]  # the passage itself may contain "explicitly"
    assert "explicitly" not in instructions and "Do not assume or infer" not in instructions  # old wording gone
    # The exception instruction comes right after the first (splitting) instruction.
    assert prompt.index("Split the rule") < prompt.index("If the rule contains an exception") < \
        prompt.index("For each condition, choose its status")


def test_requirement_prompt_asks_for_the_main_obligation(tmp_path):
    agent, _ = make(RequirementAgent, tmp_path, REQUIREMENT_ANSWER)
    prompt = agent.build_prompt(description=DESCRIPTION, satisfied_conditions=SATISFIED, **PASSAGE_INPUT)
    assert ("Turn the rule into one concrete requirement. If the rule contains several obligations, choose the "
            "main obligation that adds or changes a step in the process.") in prompt


# ---------- RequirementAgent ----------

SATISFIED = [{"condition": c["condition"], "evidence": c["evidence"]}
             for c in APPLICABILITY_ANSWER["conditions"] if c["status"] == "satisfied"]


def test_requirement_agent_parses_answer(tmp_path):
    agent, logger = make(RequirementAgent, tmp_path, REQUIREMENT_ANSWER)
    result = agent.run(case_id="19", description=DESCRIPTION, satisfied_conditions=SATISFIED, **PASSAGE_INPUT)

    assert result == RequirementOutput(**REQUIREMENT_ANSWER)
    assert log_records(logger)[0]["component"] == "RequirementAgent"


def test_requirement_condition_and_ordering_may_be_null(tmp_path):
    answer = dict(REQUIREMENT_ANSWER, condition=None, ordering=None)
    agent, _ = make(RequirementAgent, tmp_path, answer)
    result = agent.run(case_id="19", description=DESCRIPTION, satisfied_conditions=SATISFIED, **PASSAGE_INPUT)
    assert result.condition is None and result.ordering is None


def test_requirement_prompt_forbids_additions_and_lists_conditions(tmp_path):
    agent, _ = make(RequirementAgent, tmp_path, REQUIREMENT_ANSWER)
    prompt = agent.build_prompt(description=DESCRIPTION, satisfied_conditions=SATISFIED, **PASSAGE_INPUT)
    assert "Use only what the legal rule says. Do not add any obligation" in prompt
    assert '- The contract places the consumer under an obligation to pay (evidence: "the user either pays' in prompt


def test_requirement_agent_refuses_without_satisfied_conditions(tmp_path):
    agent, _ = make(RequirementAgent, tmp_path, REQUIREMENT_ANSWER)
    with pytest.raises(ValueError):
        agent.build_prompt(description=DESCRIPTION, satisfied_conditions=[], **PASSAGE_INPUT)


# ---------- shared ----------

@pytest.mark.parametrize("agent_class", [RelevanceAgent, ApplicabilityAgent, RequirementAgent])
def test_prompt_templates_have_no_unfilled_placeholders(tmp_path, agent_class):
    agent, _ = make(agent_class, tmp_path, "{}")
    extra = {"satisfied_conditions": SATISFIED} if agent_class is RequirementAgent else {}
    prompt = agent.build_prompt(description=DESCRIPTION, **PASSAGE_INPUT, **extra)
    for placeholder in ("{schema}", "{description}", "{passage}", "{conditions}"):
        assert placeholder not in prompt
