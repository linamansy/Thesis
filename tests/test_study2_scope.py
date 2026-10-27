"""Logic test of R2 extended to the Study 2 corpus laws (docs/STUDY2_CORPUS_RULE.md section 5), NO model.

Code adds one scope item S1 to every passage, chosen by its id prefix (config.yaml c3_v2.scope_conditions):
CRD- consumer buyer, SGD- goods sold to a consumer, ECD- offered online / by electronic means, LPD- payment between
businesses, GDPR- identifiable people (unchanged). Real passages from the frozen Study 2 corpus
(data/knowledge_study2_corpus/passages.jsonl); the three short descriptions below are MADE UP for this test.

Every agent answer is HAND-WRITTEN FOR LOGIC TESTING, PROVISIONAL: what an ideal agent would answer (MockLLM). The
test shows what the code does with good answers; it says nothing about qwen3:8b.

The splits here name the duty holder "other", which code leaves not_stated, so a rule with its scope confirmed stays
Indeterminate. The roles of the new laws (trader, seller, service provider, consumer, debtor, creditor; R3 extended)
are tested in tests/test_study2_roles.py.
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
from src.mediation.applicability_resolver import INDETERMINATE, NOT_APPLICABLE
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text

CONFIG = load_config()
SCOPE = CONFIG["c3_v2"]["scope_conditions"]
PASSAGES = {json.loads(line)["id"]: json.loads(line)["text"] for line in
            project_path(CONFIG["study2_corpus"]["passages"]).read_text(encoding="utf-8").splitlines()}
NO_KNOWLEDGE = load_no_knowledge_text(CONFIG)
RUN_IDS = itertools.count()

# MADE UP for this test only.
WEBSHOP = ("An online shop sells kitchen appliances to private customers through its website. A private customer, "
           "buying for personal use at home, chooses an appliance, clicks the order button and pays by card. The shop "
           "sends an order confirmation by email. If the appliance is faulty, the shop repairs or replaces the "
           "appliance.")
B2B = ("A wholesaler sells office furniture to other companies. A business customer orders desks for its offices by "
       "phone. The wholesaler delivers the desks and sends an invoice. Sometimes the business customer pays the "
       "invoice late.")
COUNTER = ("A bakery sells cakes in its shop. Orders are taken only in person at the shop counter; nothing is sold "
           "online. The baker writes the order on a card and the customer pays when collecting the cake.")


# One rule per new law: the passage, an ideal split (duty holder "other"), and a description where the scope holds
# (with its S1 quote and the quote for the situational item C1) and one where the description states the opposite.
LAWS = {
    "CRD": {"passage": "CRD-Art8-2", "law_quote": "the trader shall make the consumer aware",
            "if": "a distance contract concluded by electronic means places the consumer under an obligation to pay",
            "then": "the trader must make the consumer aware of the main information directly before the order",
            "in_scope": WEBSHOP, "s1_quote": "A private customer, buying for personal use at home",
            "c1_quote": "clicks the order button and pays by card",
            "out_of_scope": B2B, "against_quote": "A business customer orders desks for its offices"},
    "SGD": {"passage": "SGD-Art14-1", "law_quote": "Repairs or replacements shall be carried out",
            "if": "the goods are repaired or replaced",
            "then": "the seller must repair or replace the goods free of charge and within a reasonable time",
            "in_scope": WEBSHOP, "s1_quote": "sells kitchen appliances to private customers",
            "c1_quote": "the shop repairs or replaces the appliance",
            "out_of_scope": B2B, "against_quote": "A wholesaler sells office furniture to other companies"},
    "ECD": {"passage": "ECD-Art11-1", "law_quote": "the service provider has to acknowledge the receipt",
            "if": "the recipient of the service places his order through technological means",
            "then": "the service provider must acknowledge the receipt of the order without undue delay",
            "in_scope": WEBSHOP, "s1_quote": "sells kitchen appliances to private customers through its website",
            "c1_quote": "clicks the order button",
            "out_of_scope": COUNTER, "against_quote": "Orders are taken only in person at the shop counter"},
    "LPD": {"passage": "LPD-Art3-1", "law_quote": "the creditor is entitled to interest for late payment",
            "if": "the creditor has not received the amount due on time",
            "then": "the debtor must pay interest for late payment without a reminder",
            "in_scope": B2B, "s1_quote": "A wholesaler sells office furniture to other companies",
            "c1_quote": "the business customer pays the invoice late",
            "out_of_scope": WEBSHOP, "against_quote": "A private customer, buying for personal use at home"},
}


def relevant(law: dict, description_quote: str) -> dict:
    return {"law_focus": "a duty in this kind of sale", "law_quote": law["law_quote"], "relevant": True,
            "process_step": "the customer orders", "description_quote": description_quote,
            "reason": "The rule is about a kind of activity this process does."}


def split(law: dict) -> dict:
    return {"roles": ["other"], "if": [law["if"]], "then": law["then"], "exceptions": []}


def check(s1_status: str, s1_quote: str | None, c1_status: str, c1_quote: str | None) -> dict:
    return {"results": [{"id": "S1", "status": s1_status, "quote": s1_quote},
                        {"id": "C1", "status": c1_status, "quote": c1_quote}]}


def run_case(tmp_path, desc: str, passage_id: str, answers: list[dict]):
    """The whole case with this one passage as its only retrieved passage, so the knowledge block can be checked."""
    case_passages = [{"rank": 1, "passage_id": passage_id, "text": PASSAGES[passage_id]}]
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "C3V2SCOPE", f"t{next(RUN_IDS)}")
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": case_passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), load_no_knowledge_text(CONFIG))
    result = orch.mediate_case("c", desc)
    return result["passages"][0], result["knowledge_block"], llm


def items(record: dict) -> dict:
    return {c["id"]: (c["status"], c["decided_by"]) for c in record["applicability"]["conditions"]}


# ---------- the fixed texts ----------

def test_scope_texts_are_the_approved_ones():
    assert set(SCOPE) == {"GDPR-", "CRD-", "SGD-", "ECD-", "LPD-"}
    assert SCOPE["GDPR-"] == "the process handles information about identifiable people"     # R2 unchanged
    for doc in ("docs/STUDY2_CORPUS_RULE.md", "docs/C3_V2_DEVELOPMENT.md"):
        text = project_path(doc).read_text(encoding="utf-8")
        for prefix, scope in SCOPE.items():
            assert f"| {prefix} | {scope} |" in text or (prefix == "GDPR-" and f"| {prefix} | {scope} (unchanged" in text)


@pytest.mark.parametrize("passage_id", ["GDPR-Art13-1", "CRD-Art8-2", "SGD-Art14-1", "ECD-Art11-1", "LPD-Art3-1"])
def test_each_passage_gets_exactly_its_own_laws_scope_item(tmp_path, passage_id):
    llm = MockLLM([json.dumps(split(LAWS["CRD"])), json.dumps(check("not_stated", None, "not_stated", None))])
    agent = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "C3V2SCOPE", f"t{next(RUN_IDS)}"))
    record = agent.first_look("c", WEBSHOP, passage_id, PASSAGES[passage_id])
    own = SCOPE[passage_id.split("-")[0] + "-"]
    assert [(c["id"], c["text"]) for c in record["conditions"] if c["kind"] == "scope"] == [("S1", own)]
    check_prompt = llm.prompts_received[1]
    assert f"S1: {own}" in check_prompt
    assert all(other not in check_prompt for other in SCOPE.values() if other != own)


# ---------- scope stated against the law -> Not applicable ----------

@pytest.mark.parametrize("law", LAWS, ids=list(LAWS))
def test_description_stating_out_of_scope_gives_not_applicable(tmp_path, law):
    # e.g. CRD passage + "A business customer orders desks for its offices" -> the buyer is not a consumer
    rule = LAWS[law]
    answers = [relevant(rule, rule["against_quote"]), split(rule),
               check("contradicted", rule["against_quote"], "not_stated", None)]
    record, knowledge, llm = run_case(tmp_path, rule["out_of_scope"], rule["passage"], answers)
    assert items(record)["S1"] == ("contradicted", "first look")
    assert record["applicability"]["conditions"][1]["quote_found"] is True
    assert record["label"] == NOT_APPLICABLE and record["resolution"]["reason"] == "an IF item is contradicted"
    assert record["requirement"] is None and record["applicability"]["look"] == "first"   # decided: no second look
    assert len(llm.prompts_received) == 3                                    # relevance, split, check-IF
    assert knowledge == NO_KNOWLEDGE


# ---------- scope stated for the law -> scope confirmed ----------

@pytest.mark.parametrize("law", LAWS, ids=list(LAWS))
def test_description_stating_scope_confirms_it(tmp_path, law):
    # e.g. CRD passage + "A private customer, buying for personal use at home" -> scope confirmed
    rule = LAWS[law]
    answers = [relevant(rule, rule["c1_quote"]), split(rule),
               check("confirmed", rule["s1_quote"], "confirmed", rule["c1_quote"])]
    record, knowledge, llm = run_case(tmp_path, rule["in_scope"], rule["passage"], answers)
    assert items(record) == {"R1": ("not_stated", None),                    # duty holder "other": not decided by code
                             "S1": ("confirmed", "first look"), "C1": ("confirmed", "first look")}
    assert record["applicability"]["conditions"][1]["text"] == SCOPE[law + "-"]
    # known limitation (module comment): R1 stays open, so the rule is Indeterminate, never passed on
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert len(llm.prompts_received) == 3                                    # no open situational item: no second look
    assert knowledge == NO_KNOWLEDGE and SCOPE[law + "-"] not in knowledge


def test_out_of_scope_claim_without_a_real_quote_is_not_trusted(tmp_path):
    # the "business buyer" quote is not in the webshop description -> quote check makes S1 not_stated, not contradicted
    rule = LAWS["CRD"]
    answers = [relevant(rule, rule["c1_quote"]), split(rule),
               check("contradicted", "A business customer orders desks for its offices", "confirmed", rule["c1_quote"])]
    record, knowledge, llm = run_case(tmp_path, WEBSHOP, rule["passage"], answers)
    s1 = record["applicability"]["conditions"][1]
    assert (s1["status"], s1["original_status"], s1["downgraded"]) == ("not_stated", "contradicted", True)
    assert record["label"] == INDETERMINATE
    assert len(llm.prompts_received) == 3                                    # scope is never looked at again (R5)


def test_scope_not_stated_gives_indeterminate(tmp_path):
    # the bakery description says nothing about payments between businesses
    rule = LAWS["LPD"]
    answers = [relevant(rule, "the customer pays when collecting the cake"), split(rule),
               check("not_stated", None, "not_stated", None), {"results": [{"id": "C1", "status": "not_stated",
                                                                             "quote": None}]}]
    record, knowledge, llm = run_case(tmp_path, COUNTER, rule["passage"], answers)
    assert items(record)["S1"] == ("not_stated", None)
    assert record["label"] == INDETERMINATE and record["applicability"]["look"] == "second"
    second_prompt = llm.prompts_received[3]
    assert "S1" not in second_prompt.split("CONDITIONS\n")[-1]               # R5: situational items only
    assert knowledge == NO_KNOWLEDGE
