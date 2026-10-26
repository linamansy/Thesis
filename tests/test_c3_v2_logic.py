"""Logic test of the C3 v2 round 3 decision rules (docs/C3_V2_DEVELOPMENT.md section 9, evaluation (a)), NO model.

Real passages (data/knowledge_gdpr/passages_ch1-5.jsonl) and real descriptions (data/cases/01, 01.1, 11). Every agent
answer below is HAND-WRITTEN FOR LOGIC TESTING, PROVISIONAL: it is what an ideal agent would answer, written by hand
(MockLLM), so the test shows that the code (roles A1/R3, scope R2, quote check, second look R5, ResolverV2 R4, the
requirement checks R6) gives the expected label when the agents answer well. It says nothing about qwen3:8b (that is
evaluation (b), results/diagnostics/c3_v2_round3/).
"""

import itertools
import json

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
                 {"trigger": "if any", "kept_as": "if anyone"}]}

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
    record, llm = run_passage(tmp_path, desc, "GDPR-Art19-1", answers, frozen("frozen_retrieval", "11"))
    assert record["resolution"]["if_label"] == APPLICABLE                   # every IF item confirmed ...
    assert record["label"] == NOT_APPLICABLE                                # ... but the stated exception applies (R4)
    assert record["resolution"]["reason"] == "a stated exception applies" and record["requirement"] is None
    assert len(llm.prompts_received) == 3                                   # dropped: no requirement call


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
