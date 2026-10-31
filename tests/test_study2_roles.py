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

pytestmark = pytest.mark.usefixtures("verifier_yes")   # written before the verifier (fix verifier); see conftest.py

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
    return {"id": item_id, "closest_sentence": None, "status": status, "quotes": [quote] if quote else []}


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


GDPR_SPLIT_PROMPT_SHA256 = {   # measured before the per-law role list was added (round 3 split prompt); re-measured
    # after the split prompt changed on purpose in design round 1 (D4a: AND/OR groups; D4b: special cases; D5: item kinds)
    # and in design round 2 (F1: duty_type; F2a: narrowed case events); F1 'no duty' example reworded (no corpus words)
    "GDPR-Art13-1": "0d3e08054b498c657ffa95379a84d8e009fe6084d46780e568b6e8bf95480753",
    "GDPR-Art30-2": "eef47dfaea0658965a83384c29cf725aa4df2c18fb72ffce6520fc3a21450ab7"}


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
    "triggers": [{"trigger": "not later than 14 days", "kept_as": "within 14 days"}],
    "duty": {"from_then": "reimburse all payments received from the consumer",
             "kept_as": "the shop pays back everything the customer paid"}}


def test_crd_art13_trader_selling_to_private_customers_applicable(tmp_path):
    check = {"results": [result("S1", "confirmed", PRIVATE_QUOTE), result("T1", "confirmed", SHOP_QUOTE),
                         result("C1", "confirmed", WITHDRAW_QUOTE)]}
    record, knowledge, llm = run_case(tmp_path, SHOP, "CRD-Art13-1",
                                      [ART13_RELEVANT, ART13_SPLIT, check, ART13_REQUIREMENT])
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    assert role(record)["roles"][0]["reason"] == "T1 confirmed with a checked quote"
    assert role(record)["quotes_canonical"] == [SHOP_QUOTE] and role(record)["quote_found"] is True
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
                   "triggers": [{"trigger": "not later than 14 days", "kept_as": "within 14 days"}],
                   "duty": {"from_then": "send back the goods", "kept_as": "the customer sends the jacket back"}}
    answers = [relevant("the consumer shall send back the goods", "the customer sends the jacket back",
                        "The customer sends the jacket back"), split, check, requirement]
    record, knowledge, llm = run_case(tmp_path, SHOP, "CRD-Art14-1", answers)
    assert record["label"] == APPLICABLE
    assert items(record) == {"R1": ("confirmed", "first look"), "S1": ("confirmed", "first look"),
                             "C1": ("confirmed", "first look")}
    assert role(record)["roles"][0]["reason"] == "the scope item S1 is confirmed"   # consumer = S1
    assert role(record)["quotes_canonical"] == [PRIVATE_QUOTE] and record["applicability"]["role_facts"] == []
    assert len(llm.prompts_received) == 4
    assert knowledge == block("CRD-Art14-1", requirement["requirement"])


# ---------- LPD-Art3-1: who pays whom ----------
# "Member States shall ensure that ... the creditor is entitled to interest": by D1 (design round 1) the duty holder is
# the creditor, whatever role the split names, so the role is decided by D2 (the organisation is paid).

LPD_SPLIT = {"roles": ["debtor"],
             "if": ["the creditor has fulfilled its contractual and legal obligations",
                    "the creditor has not received the amount due on time"],
             "then": "the creditor is entitled to interest for late payment without the necessity of a reminder",
             "exceptions": ["the debtor is not responsible for the delay"]}
SUPPLIER = ("A steel supplier sells steel to manufacturing companies. The supplier delivers the steel as ordered and "
            "sends an invoice. Some companies pay the invoice after the agreed payment date.")


def test_lpd_art3_supplier_paid_late_applicable(tmp_path):
    check = {"results": [result("S1", "confirmed", "A steel supplier sells steel to manufacturing companies"),
                         result("D2", "confirmed", "Some companies pay the invoice after the agreed payment date"),
                         result("C1", "confirmed", "The supplier delivers the steel as ordered"),
                         result("C2", "confirmed", "Some companies pay the invoice after the agreed payment date"),
                         result("E1", "not_stated")]}
    requirement = {"requirement": "When a company pays the invoice after the agreed date, the supplier charges it "
                                  "interest for the late payment, even without a reminder.",
                   "step_quote": "The supplier delivers the steel as ordered and sends an invoice",
                   "triggers": [{"trigger": "without the necessity of a reminder",
                                 "kept_as": "even without a reminder"}],
                   "duty": {"from_then": "entitled to interest for late payment",
                            "kept_as": "the supplier charges it interest for the late payment"}}
    answers = [relevant("the creditor is entitled to interest for late payment", "the supplier sends an invoice",
                        "sends an invoice"), LPD_SPLIT, check, requirement]
    record, knowledge, llm = run_case(tmp_path, SUPPLIER, "LPD-Art3-1", answers)
    assert record["label"] == APPLICABLE
    assert role(record)["text"] == "the duty is on: creditor"                     # D1, not the split's "debtor"
    assert role(record)["roles"][0]["reason"] == "D2 confirmed with a checked quote"   # the organisation is paid
    assert [f["id"] for f in record["applicability"]["role_facts"]] == ["D2"]
    check_prompt = llm.prompts_received[2]
    assert "D2: " + SETTINGS["role_facts"]["D2"] in check_prompt and "D1: " not in check_prompt
    assert knowledge == block("LPD-Art3-1", requirement["requirement"])


def test_lpd_art3_no_payment_between_businesses_indeterminate(tmp_path):
    check = {"results": [result(i, "not_stated") for i in ("S1", "D2", "C1", "C2", "E1")]}
    second = {"results": [result("C1", "not_stated"), result("C2", "not_stated")]}
    answers = [relevant("the creditor is entitled to interest for late payment", "the customer pays",
                        "The customer pays at the counter"), LPD_SPLIT, check, second]
    record, knowledge, llm = run_case(tmp_path, BAKERY, "LPD-Art3-1", answers)
    assert items(record) == {"R1": ("not_stated", None), "S1": ("not_stated", None), "C1": ("not_stated", None),
                             "C2": ("not_stated", None)}
    assert role(record)["roles"][0]["reason"] == "D2 not stated"               # no assumption decides a creditor
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
                   "triggers": [{"trigger": "without undue delay", "kept_as": "by email without delay"},
                                {"trigger": "by electronic means", "kept_as": "shop confirms by email"}],
                   "duty": {"from_then": "acknowledge the receipt of the recipient's order",
                            "kept_as": "the shop confirms by email without delay that it has received the order"}}
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
                                 "kept_as": "Before the customer places an order"}],
                   "duty": {"from_then": "provide the consumer with general information on the main parameters "
                                         "determining ranking of offers",
                            "kept_as": "the website explains in plain words how the offers are ranked"}}
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


# ---------- fix F2: role names in C and E items bound to the actor in the process ----------

def test_role_binding_comes_from_the_role_config():
    from src.agents.applicability_agent_v2 import CUSTOMER, ORGANISATION, role_binding
    roles = SETTINGS["roles"]
    assert ORGANISATION in SETTINGS["role_facts"]["D2"] and ORGANISATION in SETTINGS["role_facts"]["T1"]
    assert role_binding(["creditor"], roles["LPD-"]["names"]) == {"creditor": ORGANISATION}
    assert role_binding(["trader"], roles["CRD-"]["names"]) == {"trader": ORGANISATION, "consumer": CUSTOMER}
    assert role_binding(["controller"], roles["default"]["names"]) == {"controller": ORGANISATION}
    assert role_binding(["public body", "other"], roles["CRD-"]["names"]) == {"consumer": CUSTOMER}


def test_bind_roles_replaces_whole_role_names_only():
    from src.agents.applicability_agent_v2 import bind_roles
    binding = {"service provider": "the organisation", "consumer": "its customer"}
    assert bind_roles("The service provider informs a consumer", binding) == "the organisation informs its customer"
    assert bind_roles("the consumers and the provider", binding) == "the consumers and the provider"


def test_check_and_second_look_get_bound_items_and_the_original_text_is_kept(tmp_path):
    split = dict(LPD_SPLIT, roles=["creditor"], exceptions=[])
    check = {"results": [result(i, "not_stated") for i in ("S1", "D2", "C1", "C2")]}
    second = {"results": [result("C1", "not_stated"), result("C2", "not_stated")]}
    answers = [relevant("the creditor is entitled to interest for late payment", "the customer pays",
                        "The customer pays at the counter"), split, check, second]
    record, _, llm = run_case(tmp_path, BAKERY, "LPD-Art3-1", answers)
    c2 = record["applicability"]["conditions"][3]
    assert c2["text"] == "the creditor has not received the amount due on time"
    assert c2["text_sent"] == "the organisation running the described process has not received the amount due on time"
    assert "C2: " + c2["text_sent"] in llm.prompts_received[2]                 # check-IF: bound text
    assert "C2: " + c2["text_sent"] in llm.prompts_received[3]                 # second look: same bound text (fix 2)
    assert "C2: " + c2["text"] not in llm.prompts_received[3]
    assert record["applicability"]["role_binding"] == {"creditor": "the organisation running the described process"}


def test_check_and_second_look_prompts_share_the_everyday_words_rules():
    """Fix 2: the same wording on legal terms vs everyday words, quotes and not_stated in both prompts."""
    config = load_config()
    texts = [project_path(config["paths"][k]).read_text(encoding="utf-8")
             for k in ("applicability_check_prompt_v2", "applicability_second_look_prompt_v2")]
    rules = ['A statement in legal terms is "confirmed" when the description states the same fact in everyday words.',
             '"confirmed" needs a quote that itself states that fact; a sentence about a different event never confirms it.',
             '"not_stated": use this only when no sentence of the description speaks to the statement.',
             "EXAMPLE OF EVERYDAY WORDS (made up, from another domain)"]
    for rule in rules:
        assert all(rule in t for t in texts), rule
    example = texts[0][texts[0].index("EXAMPLE OF EVERYDAY WORDS"):texts[0].index("JSON SCHEMA")]
    assert example in texts[1]


# ---------- fix sameart: the second look sees only the other paragraphs of the same article ----------

def test_article_of_and_same_article_passages():
    from src.agents.applicability_agent_v2 import article_of, same_article_passages
    assert article_of("GDPR-Art13-2-a") == "GDPR-Art13" and article_of("LPD-Art3-1") == "LPD-Art3"
    found = [{"passage_id": i} for i in ("GDPR-Art13-1", "GDPR-Art1-2", "GDPR-Art13-2-a", "GDPR-Art131-1", "LPD-Art13-1")]
    assert same_article_passages("GDPR-Art13-1", found) == [{"passage_id": "GDPR-Art13-2-a"}]
    assert same_article_passages("GDPR-Art1-2", found) == []


def run_second_look(tmp_path, ids: list[str]):
    """BAKERY with LPD-Art3-1 checked (rank 1) and the other ids retrieved too; every other passage is irrelevant."""
    split = dict(LPD_SPLIT, roles=["creditor"], exceptions=[])
    check = {"results": [result(i, "not_stated") for i in ("S1", "D2", "C1", "C2")]}
    second = {"results": [result("C1", "not_stated"), result("C2", "not_stated")]}
    other = dict(relevant("x", "y", "z"), relevant=False)
    answers = [relevant("the creditor is entitled to interest for late payment", "the customer pays",
                        "The customer pays at the counter"), split, check, second] + [other] * (len(ids) - 1)
    case_passages = [{"rank": n, "passage_id": i, "text": PASSAGES[i]} for n, i in enumerate(ids, 1)]
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "C3V2ROLES", f"t{next(RUN_IDS)}")
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": case_passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), NO_KNOWLEDGE)
    orch.mediate_case("c", BAKERY)
    return llm.prompts_received[3]


def test_second_look_gets_only_the_other_paragraphs_of_the_same_article(tmp_path):
    prompt = run_second_look(tmp_path, ["LPD-Art3-1", "CRD-Art9-1", "LPD-Art3-3", "LPD-Art4-1"])
    passages = prompt[prompt.index("LEGAL PASSAGES"):prompt.index("CONDITIONS")]
    assert "[LPD-Art3-3] " + PASSAGES["LPD-Art3-3"].strip() in passages
    assert "[LPD-Art3-1]" not in passages and "[CRD-Art9-1]" not in passages and "[LPD-Art4-1]" not in passages


def test_second_look_gets_no_passage_when_its_article_has_no_other_paragraph(tmp_path):
    prompt = run_second_look(tmp_path, ["LPD-Art3-1", "CRD-Art9-1"])
    assert prompt[prompt.index("LEGAL PASSAGES"):prompt.index("CONDITIONS")].strip() == "LEGAL PASSAGES"
