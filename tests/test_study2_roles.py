"""Logic test of R3 extended to the Study 2 corpus laws (docs/C3_V2_DEVELOPMENT.md section 9, "R3 extended to the new
laws"), NO model.

Roles are decided by code, per law (config.yaml c3_v2.roles, by passage id prefix): trader / seller / service provider
by the role fact T1 (A2), consumer by the law's scope item S1, debtor / creditor by D1 / D2 (who pays whom), public
body contradicted, other not_stated. The GDPR list (default) is unchanged; its split prompt is byte-identical.
Real passages from the frozen Study 2 corpus (data/knowledge_study2_corpus/passages.jsonl); the short descriptions below
are MADE UP for this test.

Every agent answer is HAND-WRITTEN FOR LOGIC TESTING, PROVISIONAL: what an ideal agent would answer (MockLLM). The
test shows what the code does with good answers; it says nothing about qwen3:8b.
"""

import hashlib
import itertools
import json

import pytest

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, law_roles
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
from src.retrieval.passage import load_passages
from src.retrieval.sparse_retriever import BM25Retriever

CONFIG = load_config()
SETTINGS = CONFIG["c3_v2"]
CORPUS = project_path(CONFIG["study2_corpus"]["passages"])
PASSAGES = {p.id: p.text for p in load_passages(CORPUS)}
NO_KNOWLEDGE = load_no_knowledge_text(CONFIG)
RUN_IDS = itertools.count()

# MADE UP for this test only.
SHOP = ("An online shop sells clothes to private customers through its website. A private customer, buying for "
        "personal use, orders a jacket on the website and pays by card. The shop confirms the order by email and sends "
        "the jacket. Within 14 days the customer tells the shop that they withdraw from the purchase. The customer "
        "sends the jacket back. The shop refunds the payment to the customer's card.")
B2B = ("A wholesaler sells office furniture to other companies. A business customer orders desks for its offices by "
       "phone and pays the invoice. The wholesaler delivers the desks. The business customer later cancels the order "
       "and the wholesaler refunds the payment.")
SUPPLY = ("A manufacturing company buys steel from its supplier, another company. The supplier delivers the steel as "
          "ordered and sends an invoice. The company pays its supplier's invoice, sometimes after the agreed payment "
          "date.")
BAKERY = ("A bakery sells cakes to people who walk into its shop. The baker writes the order on a card. The customer "
          "pays at the counter when collecting the cake.")
MARKETPLACE = ("A company runs an online marketplace on which private customers, buying for personal use, buy clothes "
               "from other sellers. Before the customer places an order, the website shows who the seller is and how "
               "the offers are ranked. The customer orders and pays by card.")

SHOP_QUOTE = "An online shop sells clothes to private customers through its website"
PRIVATE_QUOTE = "A private customer, buying for personal use"
WITHDRAW_QUOTE = "the customer tells the shop that they withdraw from the purchase"


def relevant(law_quote: str, step: str, description_quote: str) -> dict:
    return {"law_focus": "a duty in this kind of sale", "law_quote": law_quote, "relevant": True,
            "process_step": step, "description_quote": description_quote,
            "reason": "The rule is about a kind of activity this process does."}


def result(item_id: str, status: str, quote: str | None = None) -> dict:
    return {"id": item_id, "status": status, "quote": quote}


def run_case(tmp_path, desc: str, passage_id: str, answers: list[dict]):
    """The whole case with this one passage as its only retrieved passage, so the knowledge block can be checked."""
    case_passages = [{"rank": 1, "passage_id": passage_id, "text": PASSAGES[passage_id]}]
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "C3V2ROLES", f"t{next(RUN_IDS)}")
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": case_passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), NO_KNOWLEDGE)
    out = orch.mediate_case("c", desc)
    return out["passages"][0], out["knowledge_block"], llm


def items(record: dict) -> dict:
    return {c["id"]: (c["status"], c["decided_by"]) for c in record["applicability"]["conditions"]}


def role(record: dict) -> dict:
    return record["applicability"]["conditions"][0]


def block(passage_id: str, requirement: str) -> str:
    return f"REQUIREMENTS\nThese rules were checked and apply to this process.\n- [{passage_id}] {requirement}"


# ---------- the fixed texts ----------

def test_role_lists_per_law_and_role_facts():
    roles = SETTINGS["roles"]
    assert {law: list(roles[law]["names"]) for law in roles} == {
        "default": ["controller", "processor", "public body", "other"],
        "CRD-": ["trader", "consumer", "public body", "other"],
        "SGD-": ["seller", "consumer", "public body", "other"],
        "ECD-": ["service provider", "public body", "other"],
        "LPD-": ["debtor", "creditor", "public body", "other"]}
    assert law_roles(roles, "GDPR-Art13-1") is roles["default"] and law_roles(roles, "P-1") is roles["default"]
    assert law_roles(roles, "CRD-Art6a-1-a") is roles["CRD-"] and law_roles(roles, "LPD-Art3-1") is roles["LPD-"]
    assert SETTINGS["role_facts"]["P1"] == SETTINGS["processor_fact"]                # GDPR P1 unchanged
    # every role text and fact is in the committed doc
    doc = project_path("docs/C3_V2_DEVELOPMENT.md").read_text(encoding="utf-8")
    for law in ("CRD-", "SGD-", "ECD-", "LPD-"):
        for name, rule in roles[law]["names"].items():
            assert f"| {name} | {rule['means']} |" in doc
    for fact_id in ("T1", "D1", "D2"):
        assert f"| {fact_id} | {SETTINGS['role_facts'][fact_id]} |" in doc


GDPR_SPLIT_PROMPT_SHA256 = {   # measured before the per-law role list was added (round 3 split prompt)
    "GDPR-Art13-1": "285f75eac477f91ceb359b2cc5d61a7516332499920fc958c35043e05709ee57",
    "GDPR-Art30-2": "72463df1fcfebccdedb8190438c59aa7e0360a80c482f295c50925023fb05bd6"}


@pytest.mark.parametrize("passage_id", GDPR_SPLIT_PROMPT_SHA256)
def test_gdpr_split_prompt_byte_identical(tmp_path, passage_id):
    agent = ApplicabilityAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "C3V2ROLES", f"t{next(RUN_IDS)}"))
    prompt = agent.split_call.build_prompt(passage_id=passage_id, passage_text=PASSAGES[passage_id])
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == GDPR_SPLIT_PROMPT_SHA256[passage_id]


def test_split_of_a_crd_passage_offers_only_crd_roles(tmp_path):
    # "controller" is not a CRD role: the answer fails the schema and gets the one JSON retry
    llm = MockLLM([json.dumps({"roles": ["controller"], "if": [], "then": "x", "exceptions": []}),
                   json.dumps({"roles": ["trader"], "if": [], "then": "x", "exceptions": []}),
                   json.dumps({"results": [result("S1", "not_stated"), result("T1", "not_stated")]})])
    agent = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "C3V2ROLES", f"t{next(RUN_IDS)}"))
    record = agent.first_look("c", SHOP, "CRD-Art13-1", PASSAGES["CRD-Art13-1"])
    assert record["split"]["roles"] == ["trader"] and len(llm.prompts_received) == 3
    split_prompt = llm.prompts_received[0]
    assert '  - "trader": ' + SETTINGS["roles"]["CRD-"]["names"]["trader"]["means"] + ",\n" in split_prompt
    assert '"controller"' not in split_prompt.split("JSON SCHEMA")[1]               # not in the schema
    assert "T1: " + SETTINGS["role_facts"]["T1"] in llm.prompts_received[2]          # the A2 fact is asked
    assert (record["conditions"][0]["status"], record["label"]) == ("not_stated", INDETERMINATE)


# ---------- CRD-Art13-1: the trader refunds after a withdrawal ----------

ART13_RELEVANT = relevant("The trader shall reimburse all payments received from the consumer",
                          "the shop refunds the payment", "The shop refunds the payment to the customer's card")
ART13_SPLIT = {"roles": ["trader"], "if": ["the trader is informed of the consumer's decision to withdraw from the contract"],
               "then": "the trader must reimburse all payments received from the consumer, including the costs of "
                       "delivery, without undue delay and not later than 14 days from the day on which he is informed "
                       "of the decision to withdraw", "exceptions": []}
ART13_REQUIREMENT = {
    "requirement": "When the customer withdraws from the purchase, the shop pays back everything the customer paid, "
                   "delivery included, within 14 days.",
    "step_quote": "The shop refunds the payment to the customer's card",
    "triggers": [{"trigger": "not later than 14 days", "kept_as": "within 14 days"}]}


def test_crd_art13_trader_selling_to_private_customers_applicable(tmp_path):
    check = {"results": [result("S1", "confirmed", PRIVATE_QUOTE), result("T1", "confirmed", SHOP_QUOTE),
                         result("C1", "confirmed", WITHDRAW_QUOTE)]}
    record, knowledge, llm = run_case(tmp_path, SHOP, "CRD-Art13-1",
                                      [ART13_RELEVANT, ART13_SPLIT, check, ART13_REQUIREMENT])
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    assert role(record)["roles"][0]["reason"] == "T1 confirmed with a checked quote"
    assert role(record)["quote"] == SHOP_QUOTE and role(record)["quote_found"] is True
    assert [f["id"] for f in record["applicability"]["role_facts"]] == ["T1"]
    assert record["requirement"]["attempts"][0]["problems"] == []
    assert len(llm.prompts_received) == 4                                    # no second look
    assert knowledge == block("CRD-Art13-1", ART13_REQUIREMENT["requirement"])
    assert SETTINGS["role_facts"]["T1"] not in knowledge and SETTINGS["scope_conditions"]["CRD-"] not in knowledge


def test_crd_art13_business_customer_not_applicable_by_scope(tmp_path):
    check = {"results": [result("S1", "contradicted", "A business customer orders desks for its offices"),
                         result("T1", "confirmed", "A wholesaler sells office furniture to other companies"),
                         result("C1", "confirmed", "The business customer later cancels the order")]}
    answers = [relevant("The trader shall reimburse all payments received from the consumer",
                        "the wholesaler refunds the payment", "the wholesaler refunds the payment"), ART13_SPLIT, check]
    record, knowledge, llm = run_case(tmp_path, B2B, "CRD-Art13-1", answers)
    assert items(record)["S1"] == ("contradicted", "first look") and items(record)["R1"] == ("confirmed", "first look")
    assert record["label"] == NOT_APPLICABLE and record["resolution"]["reason"] == "an IF item is contradicted"
    assert record["requirement"] is None and len(llm.prompts_received) == 3
    assert knowledge == NO_KNOWLEDGE


# ---------- CRD-Art14-1: the consumer sends the goods back ----------

def test_crd_art14_consumer_withdrawal_applicable(tmp_path):
    split = {"roles": ["consumer"],
             "if": ["the consumer has communicated his decision to withdraw from the contract to the trader"],
             "then": "the consumer must send back the goods or hand them over to the trader, without undue delay and "
                     "not later than 14 days from the day on which he has communicated his decision to withdraw",
             "exceptions": ["the trader has offered to collect the goods himself"]}
    check = {"results": [result("S1", "confirmed", PRIVATE_QUOTE), result("C1", "confirmed", WITHDRAW_QUOTE),
                         result("E1", "not_stated")]}
    requirement = {"requirement": "After telling the shop about the withdrawal, the customer sends the jacket back "
                                  "within 14 days.",
                   "step_quote": "The customer sends the jacket back",
                   "triggers": [{"trigger": "not later than 14 days", "kept_as": "within 14 days"}]}
    answers = [relevant("the consumer shall send back the goods", "the customer sends the jacket back",
                        "The customer sends the jacket back"), split, check, requirement]
    record, knowledge, llm = run_case(tmp_path, SHOP, "CRD-Art14-1", answers)
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    assert role(record)["roles"][0]["reason"] == "the scope item S1 is confirmed"   # consumer = S1
    assert role(record)["quote"] == PRIVATE_QUOTE and record["applicability"]["role_facts"] == []
    assert len(llm.prompts_received) == 4
    assert knowledge == block("CRD-Art14-1", requirement["requirement"])


# ---------- LPD-Art3-1: who pays whom ----------

LPD_SPLIT = {"roles": ["debtor"],
             "if": ["the creditor has fulfilled its contractual and legal obligations",
                    "the creditor has not received the amount due on time"],
             "then": "the creditor is entitled to interest for late payment without the necessity of a reminder",
             "exceptions": ["the debtor is not responsible for the delay"]}


def test_lpd_art3_company_pays_supplier_applicable(tmp_path):
    check = {"results": [result("S1", "confirmed", "buys steel from its supplier, another company"),
                         result("D1", "confirmed", "The company pays its supplier's invoice"),
                         result("C1", "confirmed", "The supplier delivers the steel as ordered"),
                         result("C2", "confirmed", "sometimes after the agreed payment date"),
                         result("E1", "not_stated")]}
    requirement = {"requirement": "When the company pays the supplier's invoice after the agreed date, it also pays "
                                  "the supplier interest for the late payment, even without a reminder.",
                   "step_quote": "The company pays its supplier's invoice",
                   "triggers": [{"trigger": "without the necessity of a reminder", "kept_as": "even without a reminder"}]}
    answers = [relevant("the creditor is entitled to interest for late payment", "the company pays the invoice",
                        "The company pays its supplier's invoice"), LPD_SPLIT, check, requirement]
    record, knowledge, llm = run_case(tmp_path, SUPPLY, "LPD-Art3-1", answers)
    assert record["label"] == APPLICABLE
    assert role(record)["roles"][0]["reason"] == "D1 confirmed with a checked quote"   # the organisation is the debtor
    assert [f["id"] for f in record["applicability"]["role_facts"]] == ["D1"]
    check_prompt = llm.prompts_received[2]
    assert "D1: " + SETTINGS["role_facts"]["D1"] in check_prompt and "D2: " not in check_prompt
    assert knowledge == block("LPD-Art3-1", requirement["requirement"])


def test_lpd_art3_no_payment_between_businesses_indeterminate(tmp_path):
    check = {"results": [result(i, "not_stated") for i in ("S1", "D1", "C1", "C2", "E1")]}
    second = {"results": [result("C1", "not_stated"), result("C2", "not_stated")]}
    answers = [relevant("the creditor is entitled to interest for late payment", "the customer pays",
                        "The customer pays at the counter"), LPD_SPLIT, check, second]
    record, knowledge, llm = run_case(tmp_path, BAKERY, "LPD-Art3-1", answers)
    assert items(record) == {"R1": ("not_stated", None), "S1": ("not_stated", None), "C1": ("not_stated", None),
                             "C2": ("not_stated", None)}
    assert role(record)["roles"][0]["reason"] == "D1 not stated"               # no assumption decides a debtor
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert len(llm.prompts_received) == 4                                     # second look for C1, C2 only
    assert knowledge == NO_KNOWLEDGE


# ---------- ECD-Art11-1: the service provider acknowledges the order ----------

def test_ecd_art11_online_order_applicable(tmp_path):
    split = {"roles": ["service provider"],
             "if": ["the recipient of the service places his order through technological means"],
             "then": "the service provider has to acknowledge the receipt of the recipient's order without undue delay "
                     "and by electronic means",
             "exceptions": ["parties who are not consumers have agreed otherwise"]}
    check = {"results": [result("S1", "confirmed", SHOP_QUOTE), result("T1", "confirmed", SHOP_QUOTE),
                         result("C1", "confirmed", "orders a jacket on the website"), result("E1", "not_stated")]}
    requirement = {"requirement": "When the customer orders on the website, the shop confirms by email without delay "
                                  "that it has received the order.",
                   "step_quote": "The shop confirms the order by email",
                   "triggers": [{"trigger": "without undue delay", "kept_as": "without delay"},
                                {"trigger": "by electronic means", "kept_as": "by email"}]}
    answers = [relevant("the service provider has to acknowledge the receipt of the recipient's order",
                        "the shop confirms the order", "The shop confirms the order by email"), split, check, requirement]
    record, knowledge, llm = run_case(tmp_path, SHOP, "ECD-Art11-1", answers)
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    assert record["applicability"]["conditions"][1]["text"] == SETTINGS["scope_conditions"]["ECD-"]
    assert knowledge == block("ECD-Art11-1", requirement["requirement"])


# ---------- passage ids with a letter (CRD-Art6a-1-a, CRD-Art9-1a) ----------

def test_letter_ids_kept_as_strings_in_the_corpus():
    passages = {p.id: p for p in load_passages(CORPUS)}
    assert (passages["CRD-Art6a-1-a"].article, passages["CRD-Art6a-1-a"].paragraph) == ("6a", 1)
    assert (passages["CRD-Art9-1a"].article, passages["CRD-Art9-1a"].paragraph) == (9, "1a")
    assert (passages["CRD-Art9-1"].article, passages["CRD-Art9-1"].paragraph) == (9, 1)   # as in Study 1


def test_letter_ids_in_sparse_retrieval():
    # an in-memory index of three corpus passages (nothing frozen is read or written)
    sample = [p for p in load_passages(CORPUS) if p.id in ("CRD-Art6a-1-a", "CRD-Art9-1a", "CRD-Art9-1")]
    hits = BM25Retriever.from_config(CONFIG, sample).search("online marketplace ranking of offers", k=3)
    assert hits[0].passage.id == "CRD-Art6a-1-a"
    assert {h.passage.id for h in hits} <= {"CRD-Art6a-1-a", "CRD-Art9-1a", "CRD-Art9-1"}


def test_letter_id_art6a_applicable_and_in_the_block(tmp_path):
    split = {"roles": ["trader"], "if": ["a consumer is about to be bound by a distance contract on an online marketplace"],
             "then": "the provider of the online marketplace must, before a consumer is bound by a distance contract, "
                     "provide the consumer with general information on the main parameters determining ranking of "
                     "offers", "exceptions": []}
    check = {"results": [result("S1", "confirmed", "private customers, buying for personal use"),
                         result("T1", "confirmed", "A company runs an online marketplace"),
                         result("C1", "confirmed", "Before the customer places an order")]}
    requirement = {"requirement": "Before the customer places an order, the website explains in plain words how the "
                                  "offers are ranked.",
                   "step_quote": "the website shows who the seller is and how the offers are ranked",
                   "triggers": [{"trigger": "before a consumer is bound by a distance contract",
                                 "kept_as": "Before the customer places an order"}]}
    answers = [relevant("the provider of the online marketplace shall", "the website shows the offers",
                        "the website shows who the seller is"), split, check, requirement]
    record, knowledge, llm = run_case(tmp_path, MARKETPLACE, "CRD-Art6a-1-a", answers)
    assert record["passage_id"] == "CRD-Art6a-1-a" and record["label"] == APPLICABLE
    assert record["applicability"]["conditions"][1]["text"] == SETTINGS["scope_conditions"]["CRD-"]
    assert knowledge == block("CRD-Art6a-1-a", requirement["requirement"])


def test_letter_id_art9_1a_public_body_not_applicable(tmp_path):
    # "Member States may adopt rules ..." -> a duty on a public body
    split = {"roles": ["public body"], "if": ["contracts are concluded in the context of unsolicited visits by a trader"],
             "then": "the Member State may extend the withdrawal period to 30 days", "exceptions": []}
    check = {"results": [result("S1", "confirmed", PRIVATE_QUOTE), result("C1", "not_stated")]}
    answers = [relevant("Member States may adopt rules", "the customer withdraws", WITHDRAW_QUOTE), split, check]
    record, knowledge, llm = run_case(tmp_path, SHOP, "CRD-Art9-1a", answers)
    assert record["passage_id"] == "CRD-Art9-1a" and items(record)["R1"] == ("contradicted", "code rule")
    assert record["label"] == NOT_APPLICABLE and len(llm.prompts_received) == 3
    assert knowledge == NO_KNOWLEDGE
