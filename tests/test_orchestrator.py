"""Tests for the Orchestrator (C3 mediation) and condition C3 in run_experiment.py."""

import json

from run_experiment import MEDIATION_ROLES, ExperimentRunner, create_llm
from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.orchestrator import IRRELEVANT, MEDIATION_FAILED, NO_MEDIATED_KNOWLEDGE_TEXT, Orchestrator
from src.retrieval.passage import load_passages

CONFIG = load_config()
CASE = "19"
DESCRIPTION = (project_path(CONFIG["paths"]["cases"]) / CASE / "description.txt").read_text(encoding="utf-8")
FROZEN = json.loads(project_path(CONFIG["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
TITLES = {p.id: p.title for p in load_passages(project_path(CONFIG["paths"]["passages"]))}
PASSAGE_IDS = [p["passage_id"] for p in sorted(FROZEN[CASE]["passages"], key=lambda p: p["rank"])]

RELEVANT = {"relevant": True, "reason": "online purchase", "evidence_process": "logging in to their account",
            "evidence_passage": None}
NOT_RELEVANT = {"relevant": False, "reason": "unrelated", "evidence_process": None, "evidence_passage": None}
APPLICABLE = {"conditions": [{"condition": "distance contract", "status": "satisfied",
                              "evidence": "purchasing items from an online shop"}]}
INDETERMINATE = {"conditions": [{"condition": "buyer is a consumer", "status": "not_stated", "evidence": None}]}
NOT_APPLICABLE = {"conditions": [{"condition": "concluded by telephone", "status": "contradicted",
                                  "evidence": "The user starts an order by logging in to their account."}]}
REQUIREMENT = {"actor": "the trader", "action": "label the order button", "condition": None,
               "ordering": "before the user pays"}


class FailingLLM(MockLLM):
    """Raises an error on the first call (like an API failure), then answers normally."""

    def complete(self, prompt):
        if not self.prompts_received:
            self.prompts_received.append(prompt)
            raise RuntimeError("API unavailable")
        return super().complete(prompt)


def as_text(answers):
    return [a if isinstance(a, str) else json.dumps(a) for a in answers]


def make(tmp_path, relevance, applicability, requirement=(REQUIREMENT,), llm_class=MockLLM):
    logger = RunLogger(tmp_path / "logs", "C3", "test")
    llms = {"relevance": llm_class(as_text(relevance)), "applicability": MockLLM(as_text(applicability)),
            "requirement": MockLLM(as_text(requirement))}
    orchestrator = Orchestrator(RelevanceAgent(llms["relevance"], logger),
                                ApplicabilityAgent(llms["applicability"], logger),
                                RequirementAgent(llms["requirement"], logger),
                                FROZEN, TITLES, tmp_path / "mediation")
    return orchestrator, llms


def labels(result):
    return [p["label"] for p in result["passages"]]


# ---------- irrelevant passages stop at step 1 ----------

def test_irrelevant_passage_never_reaches_applicability_agent(tmp_path):
    orchestrator, llms = make(tmp_path, [NOT_RELEVANT], [APPLICABLE])
    result = orchestrator.mediate_case(CASE, DESCRIPTION)

    assert labels(result) == [IRRELEVANT] * 5
    assert llms["applicability"].prompts_received == []
    assert llms["requirement"].prompts_received == []
    assert result["knowledge_block"] == NO_MEDIATED_KNOWLEDGE_TEXT


# ---------- the requirement step runs only for Applicable rules ----------

def test_requirement_agent_runs_only_for_applicable_passages(tmp_path):
    # One applicability answer per passage, in rank order.
    orchestrator, llms = make(tmp_path, [RELEVANT],
                              [APPLICABLE, INDETERMINATE, NOT_APPLICABLE, APPLICABLE, INDETERMINATE])
    result = orchestrator.mediate_case(CASE, DESCRIPTION)

    assert labels(result) == ["Applicable", "Indeterminate", "Not applicable", "Applicable", "Indeterminate"]
    prompts = llms["requirement"].prompts_received
    assert len(prompts) == 2
    assert f"[{PASSAGE_IDS[0]}]" in prompts[0] and f"[{PASSAGE_IDS[3]}]" in prompts[1]
    assert [p["requirement"] is not None for p in result["passages"]] == [True, False, False, True, False]


def test_knowledge_block_lists_requirements_and_unconfirmed_rules(tmp_path):
    orchestrator, _ = make(tmp_path, [RELEVANT],
                           [APPLICABLE, INDETERMINATE, NOT_APPLICABLE, APPLICABLE, INDETERMINATE])
    block = orchestrator.mediate_case(CASE, DESCRIPTION)["knowledge_block"]
    requirement_line = ("Actor: the trader. Action: label the order button. Condition: none stated. "
                        "Ordering: before the user pays.")
    assert block == "\n".join([
        "REQUIREMENTS",
        f"- [{PASSAGE_IDS[0]}] {requirement_line}",
        f"- [{PASSAGE_IDS[3]}] {requirement_line}",
        "",
        "RULES WITH UNCONFIRMED APPLICABILITY",
        f"- [{PASSAGE_IDS[1]}] {TITLES[PASSAGE_IDS[1]]}",
        f"- [{PASSAGE_IDS[4]}] {TITLES[PASSAGE_IDS[4]]}",
    ])
    assert PASSAGE_IDS[2] not in block  # Not applicable is left out


def test_only_unconfirmed_rules_gives_only_that_section(tmp_path):
    orchestrator, _ = make(tmp_path, [RELEVANT], [INDETERMINATE])
    block = orchestrator.mediate_case(CASE, DESCRIPTION)["knowledge_block"]
    assert block.startswith("RULES WITH UNCONFIRMED APPLICABILITY\n") and "REQUIREMENTS" not in block


def test_made_up_quote_makes_rule_indeterminate_and_no_requirement(tmp_path):
    made_up = {"conditions": [{"condition": "c", "status": "satisfied", "evidence": "the buyer is a consumer"}]}
    orchestrator, llms = make(tmp_path, [RELEVANT], [made_up])
    result = orchestrator.mediate_case(CASE, DESCRIPTION)
    assert labels(result) == ["Indeterminate"] * 5
    assert llms["requirement"].prompts_received == []
    assert result["passages"][0]["resolution"]["conditions"][0]["downgraded"] is True


# ---------- a failing agent does not stop the case ----------

def test_invalid_answers_fail_one_passage_and_the_case_continues(tmp_path):
    # Passage 1: relevance answer invalid twice (attempt + retry). The next passages get valid answers.
    orchestrator, _ = make(tmp_path, ["not json", "still not json", RELEVANT], [INDETERMINATE])
    result = orchestrator.mediate_case(CASE, DESCRIPTION)

    assert labels(result) == [MEDIATION_FAILED] + ["Indeterminate"] * 4
    first = result["passages"][0]
    assert first["failed_step"] == "relevance" and "no valid output" in first["error"]
    assert PASSAGE_IDS[0] not in result["knowledge_block"]


def test_exception_in_an_agent_fails_one_passage_and_the_case_continues(tmp_path):
    orchestrator, _ = make(tmp_path, [RELEVANT], [INDETERMINATE], llm_class=FailingLLM)
    result = orchestrator.mediate_case(CASE, DESCRIPTION)

    assert labels(result) == [MEDIATION_FAILED] + ["Indeterminate"] * 4
    assert result["passages"][0]["error"] == "RuntimeError: API unavailable"


def test_failed_requirement_step_keeps_the_resolver_label_as_provenance(tmp_path):
    orchestrator, _ = make(tmp_path, [RELEVANT], [APPLICABLE], requirement=["bad"])
    first = orchestrator.mediate_case(CASE, DESCRIPTION)["passages"][0]
    assert first["label"] == MEDIATION_FAILED and first["failed_step"] == "requirement"
    assert first["resolution"]["label"] == "Applicable"


# ---------- saved files ----------

def test_mediation_files_are_saved(tmp_path):
    # Passages 3-5 all get NOT_APPLICABLE (MockLLM repeats its last answer).
    orchestrator, _ = make(tmp_path, [RELEVANT], [APPLICABLE, INDETERMINATE, NOT_APPLICABLE])
    result = orchestrator.mediate_case(CASE, DESCRIPTION)
    saved = json.loads((tmp_path / "mediation" / f"{CASE}.json").read_text(encoding="utf-8"))
    assert saved == result
    first = saved["passages"][0]
    assert first["passage_text"] == FROZEN[CASE]["passages"][0]["text"]
    assert first["relevance"]["quote_found"] is True
    assert set(first) >= {"passage_id", "label", "relevance", "applicability", "resolution", "requirement"}

    summary = orchestrator.save_run_summary("test")
    assert summary == json.loads((tmp_path / "mediation" / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["n_passages"] == 5 and summary["cases"] == [CASE]
    assert summary["passages_per_label"] == {"Applicable": 1, "Indeterminate": 1, "Not applicable": 3,
                                             "Irrelevant": 0, "Mediation failed": 0}
    assert summary["relevance_evidence_checker"] == {"process_quotes_checked": 5, "process_quotes_not_found": 0}
    assert summary["applicability_resolver"]["conditions_checked"] == 5


# ---------- condition C3 in run_experiment.py ----------

def make_runner(tmp_path, condition):
    paths = dict(CONFIG["paths"], results=str(tmp_path / "results"), mediation=str(tmp_path / "mediation"))
    config = dict(CONFIG, paths=paths)
    agent_llms = {role: create_llm(config, role) for role in MEDIATION_ROLES} if condition == "C3" else None
    return ExperimentRunner(config, condition, create_llm(config), RunLogger(tmp_path / "logs", condition, "t"),
                            agent_llms)


def test_c3_prompt_equals_c1_prompt_except_knowledge_block(tmp_path):
    c1_runner, c3_runner = make_runner(tmp_path, "C1"), make_runner(tmp_path, "C3")
    c1 = c1_runner.generator.build_prompt(DESCRIPTION, c1_runner.knowledge_block(CASE, DESCRIPTION))
    c3 = c3_runner.generator.build_prompt(DESCRIPTION, c3_runner.knowledge_block(CASE, DESCRIPTION))

    block = json.loads((tmp_path / "mediation" / f"{CASE}.json").read_text(encoding="utf-8"))["knowledge_block"]
    assert c1.count(NO_KNOWLEDGE_TEXT) == 1
    assert c1.replace(NO_KNOWLEDGE_TEXT, block) == c3


def test_c3_run_writes_outputs_and_mediation(tmp_path):
    runner = make_runner(tmp_path, "C3")
    runner.case_ids = [CASE]
    record = runner.run_all()[0]

    assert record["condition"] == "C3" and record["valid"] is True
    assert sorted(p.name for p in (tmp_path / "results" / "C3" / CASE).iterdir()) == \
        ["generated.bpmn", "generated.json", "validation.json"]
    assert (tmp_path / "mediation" / f"{CASE}.json").exists()
    assert (tmp_path / "mediation" / "run_summary.json").exists()
    components = {json.loads(line)["component"] for line in open(runner.logger.log_path, encoding="utf-8")}
    assert components == {"RelevanceAgent", "ApplicabilityAgent", "RequirementAgent", "BPMNGenerator"}
