"""Logic test of the C3 v2 round 3 decision rules (docs/C3_V2_DEVELOPMENT.md section 9, evaluation (a)), NO model.

Real passages (data/knowledge_gdpr/passages_ch1-5.jsonl) and real descriptions (data/cases/01, 01.1, 11). Every agent
answer below is HAND-WRITTEN FOR LOGIC TESTING, PROVISIONAL: it is what an ideal agent would answer, written by hand
(MockLLM), so the test shows that the code (roles A1/R3, scope R2, quote check, second look R5, ResolverV2 R4, the
requirement checks R6) gives the expected label when the agents answer well. It says nothing about qwen3:8b (that is
evaluation (b), results/diagnostics/c3_v2_round3/).
The OR test (GDPR-Art2-1) is marked expected-failure: it documents a known limitation, the IF list is a conjunction.
"""

import itertools
import json

import pytest

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE
from src.orchestrator import IRRELEVANT
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text

CONFIG = load_config()
PASSAGES = {json.loads(line)["id"]: json.loads(line)["text"] for line in
            project_path(CONFIG["study2_gdpr"]["passages_restricted"]).read_text(encoding="utf-8").splitlines()}
RUN_IDS = itertools.count()


def description(case_id: str) -> str:
    return (project_path(CONFIG["paths"]["cases"]) / case_id / CONFIG["paths"]["case_description_file"]).read_text(
        encoding="utf-8")


def frozen(path_key: str, case_id: str) -> list[dict]:
    cases = json.loads(project_path(CONFIG["study2_gdpr"][path_key]).read_text(encoding="utf-8"))["cases"]
    return sorted(cases[case_id]["passages"], key=lambda p: p["rank"])


DESC_01 = description("01")
DESC_01_1 = description("01.1")
ORACLE_01_1 = frozen("oracle_top5", "01.1")        # Art35-9, Art7-4, Art30-2, Art12-6, Art13-1
VARIANT_01_1 = frozen("frozen_variants_rerank", "01.1")   # rank 5 = Art13-3


def orchestrator(tmp_path, answers, case_passages):
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "C3V2LOGIC", f"t{next(RUN_IDS)}")
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": case_passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), load_no_knowledge_text(CONFIG))
    return orch, llm


def run_passage(tmp_path, desc, passage_id, answers, case_passages):
    orch, llm = orchestrator(tmp_path, answers, case_passages)
    passage = {"rank": 1, "passage_id": passage_id, "text": PASSAGES[passage_id]}
    return orch.mediate_passage("c", desc, passage, case_passages), llm


def run_case(tmp_path, desc, passage_id, answers):
    """The whole case with this one passage as its only retrieved passage, so the knowledge block can be checked."""
    case_passages = [{"rank": 1, "passage_id": passage_id, "text": PASSAGES[passage_id]}]
    orch, llm = orchestrator(tmp_path, answers, case_passages)
    result = orch.mediate_case("c", desc)
    return result["passages"][0], result["knowledge_block"], llm


def block(passage_id, requirement):
    return f"REQUIREMENTS\nThese rules were checked and apply to this process.\n- [{passage_id}] {requirement}"


NO_KNOWLEDGE = load_no_knowledge_text(CONFIG)


def items(record):
    return {c["id"]: (c["status"], c["decided_by"]) for c in record["applicability"]["conditions"]}


# ---------- hand-written ideal answers (for logic testing, provisional) ----------

def relevant(law_quote, step, description_quote):
    return {"law_focus": "personal data in the process", "law_quote": law_quote, "relevant": True,
            "process_step": step, "description_quote": description_quote,
            "reason": "The rule is about a kind of activity this process does."}


IRRELEVANT_ANSWER = {"law_focus": "a situation this process does not have", "law_quote": "", "relevant": False,
                     "process_step": "", "description_quote": "", "reason": "The process has no such activity."}

CONTACT_QUOTE = "During the inquiry, the sales staff write down the customer's name, phone number and email address"

ART13_1_RELEVANT = relevant("Where personal data relating to a data subject are collected from the data subject",
                            "the sales staff write down the customer's contact details", CONTACT_QUOTE)
ART13_1_SPLIT = {"roles": ["controller"],
                 "if": ["personal data relating to a data subject are collected from the data subject"],
                 "then": "the controller must, at the time when personal data are obtained, provide the data subject "
                         "with the identity and the contact details of the controller, the contact details of the data "
                         "protection officer where applicable, the purposes and the legal basis of the processing, the "
                         "recipients of the personal data if any",
                 "exceptions": []}
ART13_1_CHECK_01_1 = {"results": [
    {"id": "S1", "status": "confirmed",
     "quote": "the sales staff write down the customer's name, phone number and email address"},
    {"id": "C1", "status": "confirmed", "quote": "name, phone number and email"}]}
ART13_1_REQUIREMENT = {
    "requirement": "When the sales staff write down the customer's name, phone number and email address, the customer "
                   "is told who the company is, how to reach it, why the details are kept and who receives them, if "
                   "anyone.",
    "step_quote": CONTACT_QUOTE,
    "triggers": [{"trigger": "at the time when personal data are obtained",
                  "kept_as": "When the sales staff write down the customer's name"},
                 {"trigger": "if any", "kept_as": "if anyone"}],
    "duty": {"from_then": "provide the data subject with the identity and the contact details",
             "kept_as": "the customer is told who the company is"}}

ART30_2_RELEVANT = relevant("shall maintain a record of all categories of processing activities",
                            "the contact details are stored in the system", "store them in the system")
ART30_2_SPLIT = {"roles": ["processor"], "if": [],
                 "then": "the processor must maintain a record of all categories of processing activities carried out "
                         "on behalf of a controller", "exceptions": []}
ART30_2_CHECK_01_1 = {"results": [
    {"id": "S1", "status": "confirmed", "quote": "write down the customer's name, phone number and email address"},
    {"id": "P1", "status": "not_stated", "quote": None}]}     # the company keeps the data for itself

ART35_9_RELEVANT = relevant("seek the views of data subjects or their representatives on the intended processing",
                            "the contact details are stored in the system", "store them in the system")
ART35_9_SPLIT = {"roles": ["controller"], "if": ["it is appropriate to seek the views of data subjects"],
                 "then": "the controller must seek the views of data subjects or their representatives on the "
                         "intended processing", "exceptions": []}
ART35_9_CHECK_01_1 = {"results": [
    {"id": "S1", "status": "confirmed", "quote": "the customer's name, phone number and email address"},
    {"id": "C1", "status": "not_stated", "quote": None}]}
SECOND_LOOK_NOT_STATED = {"results": [{"id": "C1", "status": "not_stated", "quote": None}]}


# ---------- single passages ----------

def test_01_1_art13_1_applicable(tmp_path):
    record, llm = run_passage(tmp_path, DESC_01_1, "GDPR-Art13-1",
                              [ART13_1_RELEVANT, ART13_1_SPLIT, ART13_1_CHECK_01_1, ART13_1_REQUIREMENT], ORACLE_01_1)
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "code rule"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    c1 = record["applicability"]["conditions"][2]
    assert c1["quote"] == "name, phone number and email" and c1["quote_found"] is True
    assert record["requirement"]["requirement"] == ART13_1_REQUIREMENT["requirement"]
    assert record["requirement"]["attempts"][0]["problems"] == []          # word, banned, copy, step_quote, triggers
    assert len(llm.prompts_received) == 4                                   # no second look


def test_01_1_art30_2_not_applicable_processor_contradicted(tmp_path):
    record, llm = run_passage(tmp_path, DESC_01_1, "GDPR-Art30-2",
                              [ART30_2_RELEVANT, ART30_2_SPLIT, ART30_2_CHECK_01_1], ORACLE_01_1)
    assert record["label"] == NOT_APPLICABLE and record["requirement"] is None
    role = record["applicability"]["conditions"][0]
    assert (role["status"], role["decided_by"]) == ("contradicted", "code rule")
    assert role["roles"][0]["reason"].startswith("P1 not confirmed") and "is the controller" in role["roles"][0]["reason"]
    check_prompt = llm.prompts_received[2]
    assert "P1: " + CONFIG["c3_v2"]["processor_fact"] in check_prompt       # the on-behalf fact is asked
    assert len(llm.prompts_received) == 3


def test_01_1_art13_3_indeterminate_new_purpose_not_stated(tmp_path):
    split = {"roles": ["controller"],
             "if": ["the controller intends to further process the personal data for a purpose other than that for "
                    "which the personal data were collected"],
             "then": "the controller must provide the data subject, prior to that further processing, with information "
                     "on that other purpose", "exceptions": []}
    check = {"results": [{"id": "S1", "status": "confirmed", "quote": "the customer's name, phone number and email address"},
                         {"id": "C1", "status": "not_stated", "quote": None}]}
    answers = [relevant("further process the personal data for a purpose other than that for which the personal data "
                        "were collected", "the contact details are stored in the system", "store them in the system"),
               split, check, SECOND_LOOK_NOT_STATED]
    record, llm = run_passage(tmp_path, DESC_01_1, "GDPR-Art13-3", answers, VARIANT_01_1)
    assert record["label"] == INDETERMINATE and record["applicability"]["look"] == "second"
    assert items(record) == {"R1": ("confirmed", "code rule"), "S1": ("confirmed", "first look"),
                             "C1": ("not_stated", None)}
    assert len(llm.prompts_received) == 4                                   # no requirement call


def test_01_art35_6_not_applicable_public_body(tmp_path):
    split = {"roles": ["public body"],
             "if": ["the lists involve processing activities related to the offering of goods or services to data "
                    "subjects in several Member States"],
             "then": "the competent supervisory authority must apply the consistency mechanism prior to the adoption "
                     "of the lists", "exceptions": []}
    check = {"results": [{"id": "S1", "status": "not_stated", "quote": None},
                         {"id": "C1", "status": "not_stated", "quote": None}]}
    answers = [relevant("processing activities which are related to the offering of goods or services",
                        "the customer inquires about a product or service",
                        "a potential customer inquires about a product or service"), split, check]
    record, llm = run_passage(tmp_path, DESC_01, "GDPR-Art35-6", answers, frozen("frozen_retrieval", "01"))
    assert record["label"] == NOT_APPLICABLE
    assert items(record)["R1"] == ("contradicted", "code rule")
    assert len(llm.prompts_received) == 3                                   # decided: no second look


def test_01_art13_1_indeterminate_no_identifiable_people(tmp_path):
    # case 01 has no sentence about information on identifiable people; the 5 passages for the second look are case
    # 01's frozen top 5 with rank 5 replaced by GDPR-Art13-1 (as the oracle set of 01.1)
    case_passages = frozen("frozen_retrieval", "01")[:4] + [{"rank": 5, "passage_id": "GDPR-Art13-1",
                                                             "text": PASSAGES["GDPR-Art13-1"]}]
    check = {"results": [{"id": "S1", "status": "not_stated", "quote": None},
                         {"id": "C1", "status": "not_stated", "quote": None}]}
    answers = [relevant("Where personal data relating to a data subject are collected from the data subject",
                        "sales staff collect information from the customer",
                        "Sales staff or customer support collects relevant information"),
               ART13_1_SPLIT, check, SECOND_LOOK_NOT_STATED]
    record, llm = run_passage(tmp_path, DESC_01, "GDPR-Art13-1", answers, case_passages)
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert items(record) == {"R1": ("confirmed", "code rule"), "S1": ("not_stated", None), "C1": ("not_stated", None)}
    second_prompt = llm.prompts_received[3]
    conditions_part = second_prompt.split("CONDITIONS\n")[-1]
    assert conditions_part.startswith("C1: ") and "S1" not in conditions_part   # R5: situational items only


def test_stated_exception_gives_not_applicable(tmp_path):
    # GDPR-Art19-1 ("..., unless this proves impossible or involves disproportionate effort") on case 11. The two
    # sentences added to the case 11 description are MADE UP for this test (no real description states the exception).
    added = ("When the subscription is deactivated, the customer's personal data are erased. The customer's data were "
             "earlier passed on to partner companies, but no list of them was kept, so telling each partner about the "
             "erasure is impossible.")
    desc = description("11").rstrip("\n") + "\n" + added
    split = {"roles": ["controller"],
             "if": ["personal data have been rectified or erased, or their processing restricted",
                    "the personal data have been disclosed to recipients"],
             "then": "the controller must communicate the rectification, erasure or restriction to each recipient",
             "exceptions": ["communicating it to each recipient proves impossible or involves disproportionate effort"]}
    check = {"results": [
        {"id": "S1", "status": "confirmed", "quote": "entering personal and payment information"},
        {"id": "C1", "status": "confirmed", "quote": "the customer's personal data are erased"},
        {"id": "C2", "status": "confirmed", "quote": "The customer's data were earlier passed on to partner companies"},
        {"id": "E1", "status": "confirmed", "quote": "telling each partner about the erasure is impossible"}]}
    answers = [relevant("communicate any rectification or erasure of personal data",
                        "the subscription is deactivated", "the subscription is deactivated by the support team"),
               split, check]
    record, knowledge, llm = run_case(tmp_path, desc, "GDPR-Art19-1", answers)
    assert record["resolution"]["if_label"] == APPLICABLE                   # every IF item confirmed ...
    assert record["label"] == NOT_APPLICABLE                                # ... but the stated exception applies (R4)
    assert record["resolution"]["reason"] == "a stated exception applies" and record["requirement"] is None
    assert record["resolution"]["exceptions_applying"] == split["exceptions"]
    assert len(llm.prompts_received) == 3                                   # dropped: no requirement call
    assert knowledge == NO_KNOWLEDGE                                        # not passed on


@pytest.mark.parametrize("answer", [
    IRRELEVANT_ANSWER,
    # the model says relevant, but its description quote is not in the description -> Irrelevant by code
    relevant("conditions for consent", "the customer gives consent", "the customer ticks the consent box")],
    ids=["model_says_irrelevant", "description_quote_not_found"])
def test_irrelevant_never_reaches_applicability(tmp_path, answer):
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art7-4", [answer])
    assert record["label"] == IRRELEVANT and record["relevance"]["final_relevant"] is False
    assert record["applicability"] is None and record["resolution"] is None and record["requirement"] is None
    assert len(llm.prompts_received) == 1                                   # only the relevance call
    assert knowledge == NO_KNOWLEDGE


# Two tiny descriptions MADE UP for this test only (no real case has an organisation working for another one).
DESC_PAYROLL = ("A payroll service company handles the salary data of employees on behalf of another organisation, its "
                "client. Each month the payroll staff enter each employee's name and bank account number into the "
                "payroll system and send the payslips.")
DESC_SENSORS = ("A logistics company measures the temperature in warehouses on behalf of another organisation, its "
                "client. Every hour the sensors write the readings into the monitoring system.")
PAYROLL_STEP = "the payroll staff enter each employee's name and bank account number into the payroll system"


def test_processor_confirmed_by_on_behalf_quote_applicable(tmp_path):
    check = {"results": [
        {"id": "S1", "status": "confirmed", "quote": "each employee's name and bank account number"},
        {"id": "P1", "status": "confirmed",
         "quote": "handles the salary data of employees on behalf of another organisation"}]}
    requirement = {
        "requirement": "When the payroll staff enter the employee details, the company keeps a list of every kind of "
                       "data handling it carries out for its client.",
        "step_quote": PAYROLL_STEP,
        "triggers": [{"trigger": "carried out on behalf of a controller", "kept_as": "it carries out for its client"}],
        "duty": {"from_then": "maintain a record of all categories of processing activities",
                 "kept_as": "the company keeps a list of every kind of data handling"}}
    answers = [relevant("shall maintain a record of all categories of processing activities",
                        "the payroll staff enter the employee details", PAYROLL_STEP),
               ART30_2_SPLIT, check, requirement]
    record, knowledge, llm = run_case(tmp_path, DESC_PAYROLL, "GDPR-Art30-2", answers)
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look")}
    assert record["applicability"]["role_facts"][0]["quote_found"] is True
    assert record["applicability"]["conditions"][0]["roles"][0]["reason"] == "P1 confirmed with a checked quote"
    assert len(llm.prompts_received) == 4
    assert knowledge == block("GDPR-Art30-2", requirement["requirement"])


def test_scope_not_stated_indeterminate_although_role_holds(tmp_path):
    check = {"results": [
        {"id": "S1", "status": "not_stated", "quote": None},       # temperatures, no identifiable people
        {"id": "P1", "status": "confirmed",
         "quote": "measures the temperature in warehouses on behalf of another organisation"}]}
    answers = [relevant("shall maintain a record of all categories of processing activities",
                        "the sensors write the readings", "the sensors write the readings into the monitoring system"),
               ART30_2_SPLIT, check]
    record, knowledge, llm = run_case(tmp_path, DESC_SENSORS, "GDPR-Art30-2", answers)
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("not_stated", None)}
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert record["resolution"]["reason"] == "not every IF item is confirmed"
    assert record["applicability"]["look"] == "first"                      # R5: scope is never looked at again
    assert len(llm.prompts_received) == 3
    assert knowledge == NO_KNOWLEDGE


ART13_1_CHECK_C1_OPEN = {"results": [
    {"id": "S1", "status": "confirmed", "quote": "the customer's name, phone number and email address"},
    {"id": "C1", "status": "not_stated", "quote": None}]}


def test_second_look_resolves_situation_applicable(tmp_path):
    second = {"results": [{"id": "C1", "status": "confirmed",
                           "quote": "write down the customer's name, phone number and email address"}]}
    answers = [ART13_1_RELEVANT, ART13_1_SPLIT, ART13_1_CHECK_C1_OPEN, second, ART13_1_REQUIREMENT]
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art13-1", answers)
    assert record["applicability"]["first_look_label"] == INDETERMINATE
    assert record["applicability"]["look"] == "second" and record["applicability"]["second_look_decided"] is True
    assert items(record) == {"R1": ("confirmed", "code rule"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "second look")}
    assert record["label"] == APPLICABLE
    assert len(llm.prompts_received) == 5
    assert knowledge == block("GDPR-Art13-1", ART13_1_REQUIREMENT["requirement"])


def test_second_look_still_unsure_indeterminate(tmp_path):
    answers = [ART13_1_RELEVANT, ART13_1_SPLIT, ART13_1_CHECK_C1_OPEN, SECOND_LOOK_NOT_STATED]
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art13-1", answers)
    assert record["applicability"]["look"] == "second" and record["applicability"]["second_look_decided"] is False
    assert items(record)["C1"] == ("not_stated", None)
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert len(llm.prompts_received) == 4                                   # no requirement call
    assert knowledge == NO_KNOWLEDGE


# GDPR-Art30-4: "... shall make the record available to the supervisory authority on request."
ART30_4_ANSWERS = [
    relevant("shall make the record available to the supervisory authority on request",
             "the contact details are stored in the system", "store them in the system"),
    {"roles": ["controller", "processor"], "if": [],
     "then": "the controller or the processor must make the record available to the supervisory authority on request",
     "exceptions": []},
    {"results": [{"id": "S1", "status": "confirmed", "quote": "the customer's name, phone number and email address"},
                 {"id": "P1", "status": "not_stated", "quote": None}]}]
ART30_4_KEPT = {
    "requirement": "When the contact details are stored in the system, the company shows its list of this data "
                   "handling to the data protection authority if the authority asks.",
    "step_quote": "store them in the system",
    "triggers": [{"trigger": "on request", "kept_as": "if the authority asks"}],
    "duty": {"from_then": "make the record available to the supervisory authority",
             "kept_as": "the company shows its list of this data handling to the data protection authority"}}
ART30_4_DROPPED = {**ART30_4_KEPT,       # "on request" is gone from the requirement, so its kept_as is not found
                   "requirement": "When the contact details are stored in the system, the company shows its list of "
                                  "this data handling to the data protection authority."}
DROPPED_PROBLEM = 'the kept_as words "if the authority asks" are not copied word for word from the requirement'


def test_requirement_dropping_trigger_rejected_then_fixed_on_retry(tmp_path):
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art30-4",
                                      ART30_4_ANSWERS + [ART30_4_DROPPED, ART30_4_KEPT])
    assert record["label"] == APPLICABLE
    assert [a["problems"] for a in record["requirement"]["attempts"]] == [[DROPPED_PROBLEM], []]
    assert DROPPED_PROBLEM in llm.prompts_received[4]                       # the retry gets the reason
    assert record["requirement"]["requirement_invalid"] is False
    assert knowledge == block("GDPR-Art30-4", ART30_4_KEPT["requirement"])


def test_requirement_dropping_trigger_twice_requirement_invalid(tmp_path):
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art30-4",
                                      ART30_4_ANSWERS + [ART30_4_DROPPED, ART30_4_DROPPED])
    assert record["label"] == APPLICABLE                                    # the rule applies ...
    assert record["requirement"]["requirement_invalid"] is True             # ... but its requirement is not passed on
    assert record["requirement"]["requirement"] is None
    assert [a["problems"] for a in record["requirement"]["attempts"]] == [[DROPPED_PROBLEM], [DROPPED_PROBLEM]]
    assert len(llm.prompts_received) == 5                                   # one retry only
    assert knowledge == NO_KNOWLEDGE


def test_requirement_with_fake_step_quote_rejected(tmp_path):
    fake = {**ART13_1_REQUIREMENT, "step_quote": "the sales staff write down the customer's postal address"}
    answers = [ART13_1_RELEVANT, ART13_1_SPLIT, ART13_1_CHECK_01_1, fake, fake]
    record, knowledge, llm = run_case(tmp_path, DESC_01_1, "GDPR-Art13-1", answers)
    problem = "the step_quote is not copied word for word from the process description"
    assert [a["problems"] for a in record["requirement"]["attempts"]] == [[problem], [problem]]
    assert record["label"] == APPLICABLE and record["requirement"]["requirement_invalid"] is True
    assert len(llm.prompts_received) == 5
    assert knowledge == NO_KNOWLEDGE


@pytest.mark.xfail(strict=True, reason="IF list is a conjunction; OR not represented")
def test_or_conditions_art2_1_known_limitation(tmp_path):
    # GDPR-Art2-1: processing "wholly or partly by automated means" OR (not by automated means) "part of a filing
    # system". One alternative holds in 01.1 (stored in the system), so the rule applies; the code needs ALL IF items
    # confirmed and gives Indeterminate. Expected to fail until OR conditions are represented.
    split = {"roles": ["controller"],
             "if": ["personal data are processed wholly or partly by automated means",
                    "personal data processed other than by automated means form part of a filing system"],
             "then": "the processing falls under the Regulation", "exceptions": []}
    check = {"results": [
        {"id": "S1", "status": "confirmed", "quote": "the customer's name, phone number and email address"},
        {"id": "C1", "status": "confirmed", "quote": "store them in the system"},
        {"id": "C2", "status": "not_stated", "quote": None}]}
    second = {"results": [{"id": "C2", "status": "not_stated", "quote": None}]}
    answers = [relevant("the processing of personal data wholly or partly by automated means",
                        "the contact details are stored in the system", "store them in the system"),
               split, check, second]
    record, _, _ = run_case(tmp_path, DESC_01_1, "GDPR-Art2-1", answers)
    assert record["label"] == APPLICABLE


# ---------- full pipeline: oracle 01.1, all 5 passages ----------

def test_full_pipeline_oracle_01_1(tmp_path):
    answers = [
        # rank 1 GDPR-Art35-9: relevant, situational item open after the first look -> second look -> Indeterminate
        ART35_9_RELEVANT, ART35_9_SPLIT, ART35_9_CHECK_01_1, SECOND_LOOK_NOT_STATED,
        # rank 2 GDPR-Art7-4: the process asks for no consent -> Irrelevant
        IRRELEVANT_ANSWER,
        # rank 3 GDPR-Art30-2: processor, no "on behalf of" fact -> Not applicable
        ART30_2_RELEVANT, ART30_2_SPLIT, ART30_2_CHECK_01_1,
        # rank 4 GDPR-Art12-6: no request by a person about their own data -> Irrelevant
        IRRELEVANT_ANSWER,
        # rank 5 GDPR-Art13-1: Applicable -> requirement
        ART13_1_RELEVANT, ART13_1_SPLIT, ART13_1_CHECK_01_1, ART13_1_REQUIREMENT]
    orch, llm = orchestrator(tmp_path, answers, ORACLE_01_1)
    result = orch.mediate_case("c", DESC_01_1)
    labels = [(p["passage_id"], p["label"]) for p in result["passages"]]
    assert labels == [("GDPR-Art35-9", INDETERMINATE), ("GDPR-Art7-4", IRRELEVANT), ("GDPR-Art30-2", NOT_APPLICABLE),
                      ("GDPR-Art12-6", IRRELEVANT), ("GDPR-Art13-1", APPLICABLE)]
    assert len(llm.prompts_received) == len(answers)                        # every answer used, none left
    assert result["passages"][0]["applicability"]["look"] == "second"
    assert [p["applicability"]["look"] for p in result["passages"] if p["applicability"]] == ["second", "first", "first"]
    assert result["knowledge_block"] == (
        "REQUIREMENTS\nThese rules were checked and apply to this process.\n"
        "- [GDPR-Art13-1] When the sales staff write down the customer's name, phone number and email address, the "
        "customer is told who the company is, how to reach it, why the details are kept and who receives them, if "
        "anyone.")
    block = result["knowledge_block"]
    assert CONFIG["c3_v2"]["controller_assumption"] not in block            # A1 and R2 never reach the generator
    assert CONFIG["c3_v2"]["scope_conditions"]["GDPR-"] not in block and "ROLE DEFINITIONS" not in block
