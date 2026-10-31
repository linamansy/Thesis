"""Tests for C3 v2 design round 1 (31 Oct 2026), one section per fix (MockLLM answers only, no Ollama):
  D1 substantive duty holder of a "Member States shall ensure" rule (code)
  D2 relevance prompt: a rule that could govern a step (e.g. the step that triggers its duty) is relevant
  D3 verifier prompt: ordinary reading, an everyday equivalent of a legal concept counts
  D4a the split marks IF item groups "all" (AND) or "any" (OR); an OR group is one unit for the label
  D4b a special-case clause becomes a sub-rule with its own IF/THEN, label and requirement
  D5 IF items are process facts or case events; case events need not be confirmed (Applicable (conditional))
     but the requirement must keep each as its If/When trigger
Passages and descriptions below are made up unless a real passage id is named.
"""

import itertools
import json

import pytest

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, duty_roles, substantive_duty_holder
from src.config import load_config
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.prompt_texts import load_no_knowledge_text

pytestmark = pytest.mark.usefixtures("verifier_yes")   # the verifier says "yes"; it is tested in test_verifier_v2.py

CONFIG = load_config()
RUN_IDS = itertools.count()
ECD_ROLES = CONFIG["c3_v2"]["roles"]["ECD-"]["names"]
LPD_ROLES = CONFIG["c3_v2"]["roles"]["LPD-"]["names"]
NO_KNOWLEDGE = load_no_knowledge_text(CONFIG)


def agent(tmp_path, answers, **switches):
    llm = MockLLM([json.dumps(a) for a in answers])
    return ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"), **switches), llm


# ---------- D1: substantive duty holder ----------

SHALL_ENSURE_PASSAGE = ("1. Member States shall ensure, except when otherwise agreed, that in cases where a recipient "
                        "orders a parcel, the service provider has to confirm the order.")


def test_d1_first_role_after_shall_ensure_is_the_duty_holder():
    assert substantive_duty_holder(SHALL_ENSURE_PASSAGE, ECD_ROLES) == (True, "service provider")


def test_d1_the_first_named_role_wins_and_plurals_count():
    text = "Member States shall ensure that creditors may charge debtors interest."
    assert substantive_duty_holder(text, LPD_ROLES) == (True, "creditor")
    text = "Member State shall ensure that the debtor pays the creditor."
    assert substantive_duty_holder(text, LPD_ROLES) == (True, "debtor")


def test_d1_does_not_apply_without_shall_ensure():
    assert substantive_duty_holder("The service provider shall confirm the order.", ECD_ROLES) == (False, None)
    assert duty_roles(["public body"], "Each Member State shall publish the list.", ECD_ROLES) == (["public body"], None)


def test_d1_never_a_public_body_even_without_a_named_role():
    roles, d1 = duty_roles(["public body"], "Member States shall ensure that the list is published.", ECD_ROLES)
    assert roles == ["other"] and d1["role_found"] is None and d1["split_roles"] == ["public body"]
    roles, _ = duty_roles(["public body", "service provider"], "Member States shall ensure that lists exist.", ECD_ROLES)
    assert roles == ["service provider"]


def test_d1_replaces_the_split_roles_in_the_record(tmp_path):
    split = {"roles": ["public body"], "if": ["a recipient orders a parcel"], "then": "confirm the order",
             "exceptions": []}
    description = "A shop sells parcels online to companies. A recipient orders a parcel on the website."
    check = {"results": [
        {"id": "S1", "closest_sentence": None, "status": "not_stated", "quotes": []},
        {"id": "T1", "closest_sentence": None, "status": "confirmed",
         "quotes": ["A shop sells parcels online to companies"]},
        {"id": "C1", "closest_sentence": None, "status": "confirmed",
         "quotes": ["A recipient orders a parcel on the website"]}]}
    a, llm = agent(tmp_path, [split, check])
    record = a.first_look("x", description, "ECD-Art99-1", SHALL_ENSURE_PASSAGE)
    r1 = record["conditions"][0]
    assert r1["text"] == "the duty is on: service provider" and r1["status"] == "confirmed"   # by T1, not contradicted
    assert record["duty_holder"]["split_roles"] == ["public body"]
    assert record["role_binding"] == {"service provider": "the organisation running the described process"}
    assert "T1:" in llm.prompts_received[1]


def test_d1_leaves_other_rules_unchanged(tmp_path):
    split = {"roles": ["controller"], "if": [], "then": "keep a list", "exceptions": []}
    a, _ = agent(tmp_path, [split])
    record = a.first_look("x", "The shop keeps a list.", "P-1", "The controller shall keep a list.")
    assert record["duty_holder"] is None and record["conditions"][0]["text"] == "the duty is on: controller"


# ---------- D2: relevance covers the step that triggers a duty ----------

def test_d2_relevance_prompt_counts_the_triggering_step_and_keeps_the_json_fields(tmp_path):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2, RelevanceOutputV2
    a = RelevanceAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    prompt = a.build_prompt(description="The tenant hands back the keys.", passage_id="P-1", passage_text="A rule.")
    assert "could govern an activity, an actor or an object of this process" in prompt
    assert "even when the duty itself is not performed" in prompt and "A missing duty step is not a reason for false" in prompt
    assert "EXAMPLE WITH A MISSING DUTY STEP (made up, from another domain)" in prompt
    assert list(RelevanceOutputV2.model_fields) == ["law_focus", "law_quote", "relevant", "process_step",
                                                    "description_quote", "reason"]          # same JSON fields


def test_d2_a_rule_whose_duty_step_is_missing_stays_relevant_after_the_code_check(tmp_path):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.mediation.relevance_v2_checker import RelevanceV2Checker
    description = "The tenant hands back the keys. The agent checks the flat for damage. The agent closes the file."
    passage = "When a tenant moves out, the landlord must return the deposit within 30 days."
    answer = {"law_focus": "a tenant moving out", "law_quote": "When a tenant moves out", "relevant": True,
              "process_step": "the tenant hands back the keys", "description_quote": "The tenant hands back the keys",
              "reason": "The process has the moving out; the deposit return is missing."}
    a = RelevanceAgentV2(MockLLM([json.dumps(answer)]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    out = a.run("x", description=description, passage_id="P-1", passage_text=passage)
    assert RelevanceV2Checker().check(out, passage, description)["final_relevant"] is True


# ---------- D3: verifier judges under an ordinary reading ----------

def test_d3_verifier_prompt_ordinary_reading_everyday_equivalent_and_different_event(tmp_path):
    from src.agents.applicability_agent_v2 import VerifierCallV2
    call = VerifierCallV2(MockLLM(["{}"]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    prompt = call.build_prompt(statement="the buyer is a consumer", quotes=["The shop sells to private persons"],
                               truth="true")
    assert "Under an ordinary reading" in prompt and "state that the statement is true?" in prompt
    assert "an everyday equivalent of a legal concept counts as stating it" in prompt
    assert "A sentence about a different event never confirms the statement." in prompt         # kept
    assert "EXAMPLE (made up, from another domain)" in prompt
    example = prompt.split("EXAMPLE (made up, from another domain)")[1].split("JSON SCHEMA")[0].lower()
    for word in ("consumer", "trader", "personal data", "controller", "payment", "order", "service"):
        assert word not in example, word                                   # the example is outside the corpus
    assert "- The shop sells to private persons" in prompt and prompt.count("{") > 0


# ---------- D4a: AND / OR groups of IF items ----------

SHOP = "The customer chooses a product. The customer pays by card. The shop sends the product."
OR_PASSAGE = "Where a customer pays by card or by cash, the shop must give a receipt."
OR_SPLIT = {"roles": ["controller"],
            "if": [{"logic": "any", "items": ["a customer pays by card", "a customer pays by cash"]}],
            "then": "the shop must give a receipt", "exceptions": []}


def result(item_id, status, quote=None):
    return {"id": item_id, "closest_sentence": None, "status": status, "quotes": [quote] if quote else []}


def first_look(tmp_path, answers, passage=OR_PASSAGE):
    a, llm = agent(tmp_path, answers)
    return a, a.first_look("x", SHOP, "P-1", passage), llm


def test_d4a_or_group_confirmed_by_one_item_with_a_checked_quote(tmp_path):
    from src.mediation.resolver_v2 import ResolverV2
    _, record, _ = first_look(tmp_path, [OR_SPLIT, {"results": [
        result("C1", "confirmed", "The customer pays by card"), result("C2", "not_stated")]}])
    assert [(c["id"], c["group"], c["logic"]) for c in record["conditions"][1:]] == [("C1", "G1", "any"),
                                                                                    ("C2", "G1", "any")]
    assert record["first_look_label"] == "Applicable"
    resolution = ResolverV2().resolve(record)
    assert resolution["label"] == "Applicable"
    assert resolution["units"][1] == {"id": "G1", "logic": "any", "status": "confirmed", "case_event": False,
                                      "items": ["C1", "C2"]}


def test_d4a_or_item_with_a_fake_quote_does_not_confirm_the_group(tmp_path):
    _, record, _ = first_look(tmp_path, [OR_SPLIT, {"results": [
        result("C1", "confirmed", "The customer pays with a voucher"), result("C2", "not_stated")]}])
    assert record["conditions"][1]["status"] == "not_stated" and record["first_look_label"] == "Indeterminate"


def test_d4a_or_group_contradicted_only_when_all_items_are(tmp_path):
    _, record, _ = first_look(tmp_path, [OR_SPLIT, {"results": [
        result("C1", "contradicted", "The customer pays by card"), result("C2", "not_stated")]}])
    assert record["first_look_label"] == "Indeterminate"                    # one alternative still open
    _, record, _ = first_look(tmp_path, [OR_SPLIT, {"results": [
        result("C1", "contradicted", "The customer pays by card"),
        result("C2", "contradicted", "The customer pays by card")]}])
    assert record["first_look_label"] == "Not applicable"


def test_d4a_and_group_needs_every_item(tmp_path):
    split = {**OR_SPLIT, "if": [{"logic": "all", "items": ["a customer pays by card", "a customer pays by cash"]}]}
    _, record, _ = first_look(tmp_path, [split, {"results": [
        result("C1", "confirmed", "The customer pays by card"), result("C2", "not_stated")]}])
    assert record["first_look_label"] == "Indeterminate"


def test_d4a_plain_texts_are_read_as_and_items(tmp_path):
    split = {**OR_SPLIT, "if": ["a customer pays by card", "a customer pays by cash"]}
    _, record, _ = first_look(tmp_path, [split, {"results": [
        result("C1", "confirmed", "The customer pays by card"), result("C2", "not_stated")]}])
    assert record["split"]["if"] == [{"logic": "all", "items": [{"text": "a customer pays by card", "kind": "process_fact"}]},
                                     {"logic": "all", "items": [{"text": "a customer pays by cash", "kind": "process_fact"}]}]
    assert record["first_look_label"] == "Indeterminate"


def test_d4a_second_look_skips_alternatives_of_a_group_that_holds(tmp_path):
    split = {**OR_SPLIT, "if": OR_SPLIT["if"] + [{"logic": "all", "items": ["the shop is open"]}]}
    a, record, _ = first_look(tmp_path, [split, {"results": [
        result("C1", "confirmed", "The customer pays by card"), result("C2", "not_stated"),
        result("C3", "not_stated")]}])
    assert [c["id"] for c in a.open_conditions(record)] == ["C3"]


def test_d4a_split_prompt_and_schema_mark_all_and_any_groups(tmp_path):
    a, _ = agent(tmp_path, ["{}"])
    prompt = a.split_call.build_prompt(passage_id="P-1", passage_text=OR_PASSAGE)
    assert '"any": the items are alternatives and at least one of them must hold' in prompt
    assert "EXAMPLE WITH ALTERNATIVES (made up, for the format only)" in prompt
    group = a.split_call.output_schema.model_json_schema()["$defs"]["IfGroup"]
    assert group["properties"]["logic"]["enum"] == ["all", "any"]


# ---------- D4b: a special-case clause becomes its own sub-rule ----------

VASES = ("The customer chooses a product. The customer pays by card. The shop sends the product. Most products are "
         "glass vases, which break easily.")
SPECIAL_PASSAGE = ("Where the customer asks for express shipping, the shop shall send the product within one day. In "
                   "the case of fragile products, the shop shall pack the product in a padded box.")
SPECIAL_SPLIT = {"roles": ["controller"],
                 "if": [{"logic": "all", "items": ["the customer asks for express shipping"]}],
                 "then": "the shop must send the product within one day", "exceptions": [],
                 "special_cases": [{"clause": "In the case of fragile products", "roles": ["controller"],
                                    "if": [{"logic": "all", "items": ["the products are fragile"]}],
                                    "then": "the shop must pack the product in a padded box"}]}
SPECIAL_RELEVANT = {"law_focus": "sending products", "law_quote": "the shop shall send the product", "relevant": True,
                    "process_step": "the shop sends the product", "description_quote": "The shop sends the product",
                    "reason": "The process sends products."}
MAIN_OPEN = {"results": [result("C1", "not_stated")]}
SUB_CONFIRMED = {"results": [result("C1", "confirmed", "Most products are glass vases, which break easily")]}
SUB_REQUIREMENT = {"requirement": "When a glass vase is sent, the shop first packs it in a padded box.",
                   "step_quote": "The shop sends the product",
                   "triggers": [{"trigger": "In the case of fragile products", "kept_as": "When a glass vase is sent"}],
                   "duty": {"from_then": "pack the product in a padded box", "kept_as": "packs it in a padded box"}}


def special_orchestrator(tmp_path, answers):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.agents.requirement_agent_v2 import RequirementAgentV2
    from src.orchestrator_v2 import OrchestratorV2
    from src.prompt_texts import load_c3_block_template, load_no_knowledge_text
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}")
    passages = [{"rank": 1, "passage_id": "P-1", "text": SPECIAL_PASSAGE}]
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log, sub_rules=True),
                          RequirementAgentV2(llm, log),
                          {"c": {"passages": passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), load_no_knowledge_text(CONFIG))
    return orch, llm


def test_d4b_special_case_is_a_sub_rule_with_its_own_if_then_and_check(tmp_path):
    a, llm = agent(tmp_path, [SPECIAL_SPLIT, MAIN_OPEN, SUB_CONFIRMED], sub_rules=True)
    record = a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)
    assert [c["text"] for c in record["conditions"]] == ["the duty is on: controller",
                                                         "the customer asks for express shipping"]
    sub = record["sub_rules"][0]
    assert (sub["id"], sub["clause"], sub["then"]) == ("K1", "In the case of fragile products",
                                                      "the shop must pack the product in a padded box")
    assert [(c["id"], c["text"], c["status"]) for c in sub["conditions"]] == [
        ("R1", "the duty is on: controller", "confirmed"), ("C1", "the products are fragile", "confirmed")]
    assert record["first_look_label"] == "Indeterminate" and sub["first_look_label"] == "Applicable"
    main_check, sub_check = llm.prompts_received[1], llm.prompts_received[2]
    assert "C1: the customer asks for express shipping" in main_check and "fragile" not in main_check
    assert "C1: the products are fragile" in sub_check and "express" not in sub_check


def test_d4b_orchestrator_resolves_the_sub_rule_and_passes_its_requirement_on(tmp_path):
    orch, llm = special_orchestrator(tmp_path, [SPECIAL_RELEVANT, SPECIAL_SPLIT, MAIN_OPEN, SUB_CONFIRMED,
                                                {"results": [result("C1", "not_stated")]}, SUB_REQUIREMENT])
    result_ = orch.mediate_case("c", VASES)
    record = result_["passages"][0]
    assert record["label"] == "Indeterminate" and record["requirement"] is None      # the main rule
    sub = record["applicability"]["sub_rules"][0]
    assert sub["label"] == "Applicable" and sub["requirement"]["requirement"] == SUB_REQUIREMENT["requirement"]
    assert sub["resolution"]["reason"] == "every IF item confirmed and no stated exception applies"
    assert result_["knowledge_block"] == ("REQUIREMENTS\nThese rules were checked and apply to this process.\n"
                                          "- [P-1] " + SUB_REQUIREMENT["requirement"])
    assert "OBLIGATION\nthe shop must pack the product in a padded box" in llm.prompts_received[5]
    assert len(llm.prompts_received) == 6


def test_d4b_obligation_word_in_a_special_case_makes_the_split_invalid(tmp_path):
    bad = {**SPECIAL_SPLIT, "special_cases": [{**SPECIAL_SPLIT["special_cases"][0],
                                               "if": ["the shop must use a padded box"]}]}
    a, _ = agent(tmp_path, [bad], sub_rules=True)
    record = a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)
    assert record["label"] == "Split invalid" and record["rejected_if"] == ["the shop must use a padded box"]


def test_d4b_a_failed_sub_rule_call_fails_only_the_sub_rule(tmp_path):
    orch, _ = special_orchestrator(tmp_path, [SPECIAL_RELEVANT, SPECIAL_SPLIT, MAIN_OPEN, "not json", "not json",
                                              {"results": [result("C1", "not_stated")]}])
    record = orch.mediate_case("c", VASES)["passages"][0]
    assert record["label"] == "Indeterminate"
    sub = record["applicability"]["sub_rules"][0]
    assert sub["label"] == "Mediation failed" and sub["failed_step"] == "check"


# ---------- D5: process facts and case events ----------

RETURN_PASSAGE = "If a customer returns a product, the shop must refund the price within 14 days."
RETURN_SPLIT = {"roles": ["controller"],
                "if": [{"logic": "all", "items": [{"text": "a customer buys a product", "kind": "process_fact"},
                                                  {"text": "the customer returns the product", "kind": "case_event"}]}],
                "then": "the shop must refund the price within 14 days", "exceptions": []}
RETURN_RELEVANT = {"law_focus": "returns of products", "law_quote": "a customer returns a product", "relevant": True,
                   "process_step": "the customer chooses a product", "description_quote": "The customer chooses a product",
                   "reason": "The process sells products."}
BUY_CONFIRMED_RETURN_OPEN = {"results": [result("C1", "confirmed", "The customer chooses a product"),
                                         result("C2", "not_stated")]}
RETURN_REQUIREMENT = {"requirement": "If the customer returns the product, the shop refunds the price within 14 days.",
                      "step_quote": "The customer chooses a product",
                      "triggers": [{"trigger": "within 14 days", "kept_as": "within 14 days"}],
                      "duty": {"from_then": "refund the price within 14 days", "kept_as": "the shop refunds the price"},
                      "case_events": [{"id": "C2", "kept_as": "If the customer returns the product"}]}
CONDITIONAL = "Applicable (conditional)"


def return_orchestrator(tmp_path, answers, passage=RETURN_PASSAGE):
    from src.agents.relevance_agent_v2 import RelevanceAgentV2
    from src.agents.requirement_agent_v2 import RequirementAgentV2
    from src.orchestrator_v2 import OrchestratorV2
    from src.prompt_texts import load_c3_block_template
    llm = MockLLM([json.dumps(a) for a in answers])
    log = RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}")
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": [{"rank": 1, "passage_id": "P-1", "text": passage}]}},
                          tmp_path / "mediation", load_c3_block_template(CONFIG, "c3_block_template_v2"),
                          NO_KNOWLEDGE)
    return orch, llm


def test_d5_case_event_not_stated_gives_applicable_conditional_with_its_requirement(tmp_path):
    orch, llm = return_orchestrator(tmp_path, [RETURN_RELEVANT, RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN,
                                               RETURN_REQUIREMENT])
    out = orch.mediate_case("c", SHOP)
    record = out["passages"][0]
    assert [(c["id"], c.get("item_kind")) for c in record["applicability"]["conditions"]] == [
        ("R1", None), ("C1", "process_fact"), ("C2", "case_event")]
    assert record["label"] == CONDITIONAL and record["applicability"]["look"] == "first"   # no second look
    assert record["resolution"]["case_events"] == [{"id": "C2", "text": "the customer returns the product"}]
    assert record["requirement"]["requirement"] == RETURN_REQUIREMENT["requirement"]
    assert record["requirement"]["requirement_invalid"] is False
    assert "CASE EVENTS\nC2: the customer returns the product" in llm.prompts_received[3]
    assert out["knowledge_block"].endswith("- [P-1] " + RETURN_REQUIREMENT["requirement"])


def test_d5_every_case_event_confirmed_is_still_conditional(tmp_path):
    a, _ = agent(tmp_path, [RETURN_SPLIT, {"results": [result("C1", "confirmed", "The customer chooses a product"),
                                                       result("C2", "confirmed", "The shop sends the product")]}])
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert record["first_look_label"] == CONDITIONAL


def test_d5_a_contradicted_case_event_gives_not_applicable(tmp_path):
    description = SHOP + " Products can never be returned."
    a, _ = agent(tmp_path, [RETURN_SPLIT, {"results": [
        result("C1", "confirmed", "The customer chooses a product"),
        result("C2", "contradicted", "Products can never be returned")]}])
    record = a.first_look("x", description, "P-1", RETURN_PASSAGE)
    assert record["first_look_label"] == "Not applicable"


def test_d5_a_process_fact_not_stated_keeps_the_rule_indeterminate(tmp_path):
    a, _ = agent(tmp_path, [RETURN_SPLIT, {"results": [result("C1", "not_stated"), result("C2", "not_stated")]}])
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert record["first_look_label"] == "Indeterminate"


def test_d5_or_group_of_case_events_is_one_case_event(tmp_path):
    from src.mediation.resolver_v2 import ResolverV2
    split = {**RETURN_SPLIT, "if": [
        {"logic": "all", "items": [{"text": "a customer buys a product", "kind": "process_fact"}]},
        {"logic": "any", "items": [{"text": "the customer returns the product", "kind": "case_event"},
                                   {"text": "the customer complains", "kind": "case_event"}]}]}
    a, _ = agent(tmp_path, [split, {"results": [result("C1", "confirmed", "The customer chooses a product"),
                                                result("C2", "not_stated"), result("C3", "not_stated")]}])
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    resolution = ResolverV2().resolve(record)
    assert resolution["label"] == CONDITIONAL
    assert resolution["case_events"] == [{"id": "G2", "text": "one of: the customer returns the product; "
                                                              "the customer complains"}]


def test_d5_requirement_without_its_case_event_is_retried_then_invalid(tmp_path):
    dropped = {**RETURN_REQUIREMENT, "case_events": []}
    orch, llm = return_orchestrator(tmp_path, [RETURN_RELEVANT, RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN,
                                               dropped, dropped])
    out = orch.mediate_case("c", SHOP)
    record = out["passages"][0]
    problem = record["requirement"]["attempts"][0]["problems"][0]
    assert problem.startswith('the case event C2 ("the customer returns the product") is not kept')
    assert problem in llm.prompts_received[4]                                   # the retry gets the reason
    assert record["requirement"]["requirement_invalid"] is True and out["knowledge_block"] == NO_KNOWLEDGE


def test_d5_case_event_kept_as_must_start_with_if_or_when_and_be_in_the_requirement():
    from src.agents.requirement_agent_v2 import RequirementOutputV2
    from src.mediation.requirement_checker_v2 import RequirementCheckerV2
    checker, events = RequirementCheckerV2(CONFIG), [{"id": "C2", "text": "the customer returns the product"}]
    ok = RequirementOutputV2.model_validate(RETURN_REQUIREMENT)
    assert checker.case_event_problems(ok, events) == []
    not_if = RequirementOutputV2.model_validate({**RETURN_REQUIREMENT, "case_events": [
        {"id": "C2", "kept_as": "the customer returns the product"}]})
    assert checker.case_event_problems(not_if, events) == [
        'the kept_as words "the customer returns the product" of case event C2 must start with "If" or "When"']
    invented = RequirementOutputV2.model_validate({**RETURN_REQUIREMENT, "case_events": [
        {"id": "C2", "kept_as": "When the customer complains"}, {"id": "C9", "kept_as": "If the customer returns"}]})
    assert checker.case_event_problems(invented, events) == [
        "case_events names C9, which is not a listed case event",
        'the kept_as words "When the customer complains" of case event C2 are not copied word for word from the '
        'requirement']
    assert checker.case_event_problems(ok, []) == ["case_events names C2, which is not a listed case event"]


def test_d5_prompts_mark_kinds_and_list_case_events(tmp_path):
    from src.agents.requirement_agent_v2 import RequirementAgentV2
    a, _ = agent(tmp_path, ["{}"])
    split_prompt = a.split_call.build_prompt(passage_id="P-1", passage_text=RETURN_PASSAGE)
    assert '"case_event": an event that happens only in some cases of the process' in split_prompt
    assert '"process_fact": a fact that holds or does not hold for the process as a whole' in split_prompt
    item = a.split_call.output_schema.model_json_schema()["$defs"]["IfItem"]
    assert item["properties"]["kind"]["enum"] == ["process_fact", "case_event"]
    req = RequirementAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"))
    inputs = dict(description=SHOP, passage_id="P-1", passage_text=RETURN_PASSAGE, then="refund the price",
                  process_step="sale", description_quote="The customer chooses a product")
    assert req.build_prompt(**inputs).rstrip().endswith("CASE EVENTS\nnone")
    assert req.build_prompt(**inputs, case_events=[{"id": "C2", "text": "the customer returns it"}]).rstrip().endswith(
        "CASE EVENTS\nC2: the customer returns it")


# ---------- ablation switches (run options --no-d5 / --no-d4b) ----------

def test_ablation_without_d5_reads_every_item_as_a_process_fact(tmp_path):
    llm = MockLLM([json.dumps(a) for a in [RETURN_SPLIT, BUY_CONFIRMED_RETURN_OPEN]])
    a = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"), case_events=False)
    record = a.first_look("x", SHOP, "P-1", RETURN_PASSAGE)
    assert [(c["id"], c.get("item_kind"), c.get("split_kind")) for c in record["conditions"]] == [
        ("R1", None, None), ("C1", "process_fact", "process_fact"),
        ("C2", "process_fact", "case_event")]
    assert record["first_look_label"] == "Indeterminate"                 # with D5: Applicable (conditional)
    assert record["split"]["if"][0]["items"][1]["kind"] == "case_event"  # the split's answer is kept as given


def test_ablation_without_d4b_never_evaluates_special_cases(tmp_path):
    llm = MockLLM([json.dumps(a) for a in [SPECIAL_SPLIT, MAIN_OPEN]])
    a = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"), sub_rules=False)
    record = a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)
    assert record["sub_rules"] == [] and len(llm.prompts_received) == 2   # split + the main rule's check only
    assert record["split"]["special_cases"][0]["clause"] == "In the case of fragile products"
    bad = {**SPECIAL_SPLIT, "special_cases": [{**SPECIAL_SPLIT["special_cases"][0],
                                               "if": ["the shop must use a padded box"]}]}
    a = ApplicabilityAgentV2(MockLLM([json.dumps(bad), json.dumps(MAIN_OPEN)]),
                             RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"), sub_rules=False)
    assert a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)["split_valid"] is True


def test_d4b_is_off_by_default_since_design_round_2(tmp_path):
    a, llm = agent(tmp_path, [SPECIAL_SPLIT, MAIN_OPEN])
    record = a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)
    assert record["sub_rules"] == [] and len(llm.prompts_received) == 2   # split + the main rule's check only
    assert a.case_events is True and a.sub_rules is False


def test_ablation_switches_leave_the_prompts_unchanged(tmp_path):
    prompts = []
    for switches in ({"sub_rules": True}, {"case_events": False, "sub_rules": False}):
        llm = MockLLM([json.dumps(a) for a in [SPECIAL_SPLIT, MAIN_OPEN, SUB_CONFIRMED]])
        a = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "ROUND1", f"r{next(RUN_IDS)}"), **switches)
        a.first_look("x", VASES, "P-1", SPECIAL_PASSAGE)
        prompts.append(llm.prompts_received[:2])
    assert prompts[0] == prompts[1]
