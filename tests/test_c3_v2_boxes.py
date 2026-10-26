"""Tests for C3 v2 boxes 2-4: ApplicabilityAgentV2 (split, check-IF, quote check, first and second look), ResolverV2,
RequirementAgentV2, the C3 v2 knowledge block and the OrchestratorV2 audit trail (MockLLM answers only, no Ollama).
"""

import itertools
import json

from src.agents.applicability_agent_v2 import SPLIT_INVALID, ApplicabilityAgentV2
from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.agents.requirement_agent_v2 import RequirementAgentV2, RequirementOutputV2
from src.c3_version import changed_items
from src.config import load_config, project_path
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE
from src.mediation.requirement_checker_v2 import RequirementCheckerV2
from src.mediation.resolver_v2 import ResolverV2
from src.orchestrator import IRRELEVANT, MEDIATION_FAILED
from src.orchestrator_v2 import OrchestratorV2
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text

CONFIG = load_config()
DESCRIPTION = "The customer chooses a product. The customer pays by card. The shop sends the product."
PASSAGE = "If a customer pays by card, the shop must give a receipt, unless the customer declines it."
OTHER_PASSAGE = "A card means a payment card issued by a bank."

SPLIT = {"roles": ["controller"], "if": ["a customer pays by card"], "then": "the shop must give a receipt",
         "exceptions": ["the customer declines the receipt"]}
CONFIRMED = {"results": [{"id": "C1", "status": "confirmed", "quote": "The customer pays by card"},
                         {"id": "E1", "status": "not_stated", "quote": None}]}
NOT_STATED = {"results": [{"id": "C1", "status": "not_stated", "quote": None},
                          {"id": "E1", "status": "not_stated", "quote": None}]}
RELEVANT = {"law_focus": "card payments", "law_quote": "a customer pays by card", "relevant": True,
            "process_step": "the customer pays by card", "description_quote": "The customer pays by card",
            "reason": "The process has a card payment step."}
REQUIREMENT = {"requirement": "After the customer pays by card, a receipt is handed to the customer.",
               "step_quote": "The customer pays by card", "triggers": []}
BAD_REQUIREMENT = {"requirement": "The controller must give a receipt.", "step_quote": "The customer pays by card",
                   "triggers": []}

RUN_IDS = itertools.count()   # every agent gets its own log file (RunLogger never writes into an existing one)


def mock(answers) -> MockLLM:
    return MockLLM([json.dumps(a) if isinstance(a, dict) else a for a in answers])


def logger(tmp_path) -> RunLogger:
    return RunLogger(tmp_path, "C3V2", f"t{next(RUN_IDS)}")


def first_look(tmp_path, answers):
    llm = mock(answers)
    record = ApplicabilityAgentV2(llm, logger(tmp_path)).first_look("x", DESCRIPTION, "P-1", PASSAGE)
    return record, llm


def orchestrator(tmp_path, answers, passages=None):
    llm = mock(answers)
    log = logger(tmp_path)
    passages = passages or [{"rank": 1, "passage_id": "P-1", "text": PASSAGE}]
    orch = OrchestratorV2(RelevanceAgentV2(llm, log), ApplicabilityAgentV2(llm, log), RequirementAgentV2(llm, log),
                          {"c": {"passages": passages}}, tmp_path / "mediation",
                          load_c3_block_template(CONFIG, "c3_block_template_v2"), load_no_knowledge_text(CONFIG))
    return orch, llm


# ---------- box 2: split ----------

def test_valid_split(tmp_path):
    record, llm = first_look(tmp_path, [SPLIT, CONFIRMED])
    assert record["split_valid"] is True and record["split"] == SPLIT
    assert [(c["id"], c["kind"], c["text"]) for c in record["conditions"]] == \
        [("R1", "role", "the duty is on: controller"), ("C1", "situation", "a customer pays by card")]
    assert [(e["id"], e["text"]) for e in record["exceptions"]] == [("E1", "the customer declines the receipt")]
    split_prompt, check_prompt = llm.prompts_received
    assert PASSAGE in split_prompt and DESCRIPTION not in split_prompt          # the split sees the law text only
    assert DESCRIPTION in check_prompt and PASSAGE not in check_prompt          # the check sees the IF list only
    assert "C1: a customer pays by card" in check_prompt and "E1: the customer declines the receipt" in check_prompt


def test_obligation_word_in_if_is_rejected(tmp_path):
    for item in ["the trader shall provide the price", "the trader MUST inform", "the trader is required to inform"]:
        record, llm = first_look(tmp_path, [dict(SPLIT, **{"if": ["a consumer", item]}), CONFIRMED])
        assert (record["split_valid"], record["label"], record["rejected_if"]) == (False, SPLIT_INVALID, [item])
        assert len(llm.prompts_received) == 1                                    # no check-IF call
    record, _ = first_look(tmp_path, [dict(SPLIT, **{"if": ["a shallow mustard dish"]}), NOT_STATED])
    assert record["split_valid"] is True                                         # whole words only


def test_empty_if_list(tmp_path):
    # round 3 (R1): a duty with no situation has only the role item; the controller role is decided by code (A1)
    record, llm = first_look(tmp_path, [dict(SPLIT, **{"if": [], "exceptions": []})])
    assert (record["split_valid"], record["label"], [c["id"] for c in record["conditions"]]) == (True, APPLICABLE, ["R1"])
    assert record["conditions"][0]["decided_by"] == "code rule"
    assert len(llm.prompts_received) == 1                                        # nothing needs a quote: no check call
    assert ResolverV2().resolve(record)["label"] == APPLICABLE
    record, llm = first_look(tmp_path, [dict(SPLIT, **{"if": [], "roles": ["other"], "exceptions": []})])
    assert record["label"] == INDETERMINATE and record["conditions"][0]["status"] == "not_stated"


# ---------- box 2: check-IF, quote check, first look ----------

def test_real_quote_confirms_and_fake_quote_becomes_not_stated(tmp_path):
    record, _ = first_look(tmp_path, [SPLIT, CONFIRMED])
    c1 = record["conditions"][1]
    assert (c1["status"], c1["quote_found"], c1["downgraded"], record["label"]) == ("confirmed", True, False, APPLICABLE)
    assert c1["decided_by"] == "first look"

    fake = {"results": [{"id": "C1", "status": "confirmed", "quote": "The customer pays in cash"},
                        {"id": "E1", "status": "not_stated", "quote": None}]}
    record, _ = first_look(tmp_path, [SPLIT, fake])
    c1 = record["conditions"][1]
    assert (c1["original_status"], c1["status"], c1["quote_found"], c1["downgraded"]) == \
        ("confirmed", "not_stated", False, True)
    assert record["label"] == INDETERMINATE

    no_quote = {"results": [{"id": "C1", "status": "confirmed", "quote": None}, NOT_STATED["results"][1]]}
    record, _ = first_look(tmp_path, [SPLIT, no_quote])
    assert (record["conditions"][1]["status"], record["conditions"][1]["quote_found"]) == ("not_stated", None)


def test_contradicted_gives_not_applicable(tmp_path):
    split = dict(SPLIT, **{"if": ["a customer pays by card", "the customer collects the product in the shop"]})
    answer = {"results": [CONFIRMED["results"][0],
                          {"id": "C2", "status": "contradicted", "quote": "The shop sends the product"},
                          {"id": "E1", "status": "not_stated", "quote": None}]}
    record, _ = first_look(tmp_path, [split, answer])
    assert record["first_look_label"] == NOT_APPLICABLE
    assert ResolverV2().resolve(record)["label"] == NOT_APPLICABLE


def test_malformed_json_gets_one_retry(tmp_path):
    record, llm = first_look(tmp_path, ["not json", SPLIT, CONFIRMED])
    assert record["label"] == APPLICABLE and len(llm.prompts_received) == 3
    assert "not valid JSON" in llm.prompts_received[1]                           # the retry note
    wrong_ids = {"results": [{"id": "C9", "status": "confirmed", "quote": "The customer pays by card"}]}
    record, llm = first_look(tmp_path, [SPLIT, wrong_ids, CONFIRMED])            # missing ids also count as invalid
    assert record["label"] == APPLICABLE and "C1, E1" in llm.prompts_received[2]
    record, _ = first_look(tmp_path, ["not json", "still not"])
    assert (record["failed_step"], record["label"]) == ("split", None)


# ---------- box 2: second look (orchestrator) ----------

TWO_PASSAGES = [{"rank": 1, "passage_id": "P-1", "text": PASSAGE},
                {"rank": 2, "passage_id": "P-2", "text": OTHER_PASSAGE}]


def test_second_look_resolves(tmp_path):
    second = {"results": [{"id": "C1", "status": "confirmed", "quote": "pays by card"}]}
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, NOT_STATED, second, REQUIREMENT], passages=TWO_PASSAGES)
    record = orch.mediate_passage("c", DESCRIPTION, TWO_PASSAGES[0], TWO_PASSAGES)
    a = record["applicability"]
    assert (a["first_look_label"], a["look"], a["second_look_decided"], a["label"]) == \
        (INDETERMINATE, "second", True, APPLICABLE)
    assert (a["conditions"][1]["first_look_status"], a["conditions"][1]["status"]) == ("not_stated", "confirmed")
    assert a["conditions"][1]["decided_by"] == "second look"
    assert record["label"] == APPLICABLE and record["requirement"]["requirement"] == REQUIREMENT["requirement"]
    second_prompt = llm.prompts_received[3]
    assert "[P-1] " + PASSAGE in second_prompt and "[P-2] " + OTHER_PASSAGE in second_prompt   # all passages
    assert DESCRIPTION in second_prompt and "C1: a customer pays by card" in second_prompt
    assert "E1" not in second_prompt and "R1" not in second_prompt              # only open situational conditions


def test_second_look_stays_indeterminate(tmp_path):
    second = {"results": [{"id": "C1", "status": "confirmed", "quote": "The customer pays in cash"}]}   # fake quote
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, NOT_STATED, second], passages=TWO_PASSAGES)
    record = orch.mediate_passage("c", DESCRIPTION, TWO_PASSAGES[0], TWO_PASSAGES)
    a = record["applicability"]
    assert (a["look"], a["second_look_decided"], a["conditions"][1]["downgraded"]) == ("second", False, True)
    assert record["label"] == INDETERMINATE and record["requirement"] is None
    assert len(llm.prompts_received) == 4                                        # no requirement call


def test_first_look_decision_has_no_second_look(tmp_path):
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, CONFIRMED, REQUIREMENT])
    record = orch.mediate_case("c", DESCRIPTION)["passages"][0]
    assert (record["applicability"]["look"], record["applicability"]["second_look"]) == ("first", None)
    assert len(llm.prompts_received) == 4


# ---------- box 3: resolver ----------

ROLE_OK = {"id": "R1", "kind": "role", "text": "the duty is on: controller", "status": "confirmed",
           "decided_by": "code rule"}


def test_resolver_with_exception():
    conditions = [ROLE_OK, {"id": "C1", "kind": "situation", "text": "a customer pays by card", "status": "confirmed",
                            "quote_found": True, "decided_by": "first look"}]
    declines = {"text": "the customer declines", "status": "confirmed", "quote_found": True}
    result = ResolverV2().resolve({"conditions": conditions, "exceptions": [declines]})
    assert (result["label"], result["if_label"], result["exceptions_applying"]) == \
        (NOT_APPLICABLE, APPLICABLE, ["the customer declines"])
    assert result["decided_by"] == {"R1": "code rule", "C1": "first look"}
    unknown = {"conditions": conditions, "exceptions": [dict(declines, status="not_stated", quote_found=None)]}
    assert ResolverV2().resolve(unknown)["label"] == APPLICABLE                  # an unstated exception does not block
    open_if = {"conditions": [ROLE_OK, {"id": "C1", "text": "x", "status": "not_stated"}], "exceptions": []}
    assert ResolverV2().resolve(open_if)["label"] == INDETERMINATE


def test_resolver_needs_quote_or_code_rule_and_a_role_item():
    unchecked = {"id": "C1", "kind": "situation", "text": "x", "status": "confirmed", "quote_found": False}
    assert ResolverV2().resolve({"conditions": [ROLE_OK, unchecked], "exceptions": []})["label"] == INDETERMINATE
    no_role = {"id": "C1", "kind": "situation", "text": "x", "status": "confirmed", "quote_found": True}
    result = ResolverV2().resolve({"conditions": [no_role], "exceptions": []})
    assert (result["label"], result["reason"]) == (INDETERMINATE, "the IF list has no role item (R1)")


def test_stated_exception_blocks_requirement_in_orchestrator(tmp_path):
    exception_holds = {"results": [CONFIRMED["results"][0],
                                   {"id": "E1", "status": "confirmed", "quote": "The shop sends the product"}]}
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, exception_holds, REQUIREMENT])
    result = orch.mediate_case("c", DESCRIPTION)
    assert result["passages"][0]["label"] == NOT_APPLICABLE and result["passages"][0]["requirement"] is None
    assert result["knowledge_block"] == load_no_knowledge_text(CONFIG)


# ---------- box 4: requirement and knowledge block ----------

def test_requirement_prompt_has_then_and_step(tmp_path):
    agent = RequirementAgentV2(mock([REQUIREMENT]), logger(tmp_path))
    output = agent.run("x", description=DESCRIPTION, passage_id="P-1", passage_text=PASSAGE,
                       then="the shop must give a receipt", process_step="the customer pays by card",
                       description_quote="The customer pays by card")
    assert output == RequirementOutputV2(**REQUIREMENT)
    prompt = agent.llm.prompts_received[0]
    assert "OBLIGATION\nthe shop must give a receipt" in prompt
    assert 'the customer pays by card ("The customer pays by card")' in prompt


def test_c3_block_has_confirmed_requirements_only(tmp_path):
    passages = TWO_PASSAGES
    irrelevant = dict(RELEVANT, relevant=False, process_step="", description_quote="")
    orch, _ = orchestrator(tmp_path, [RELEVANT, SPLIT, CONFIRMED, REQUIREMENT, irrelevant], passages=passages)
    result = orch.mediate_case("c", DESCRIPTION)
    assert [p["label"] for p in result["passages"]] == [APPLICABLE, IRRELEVANT]
    assert result["knowledge_block"] == ("REQUIREMENTS\nThese rules were checked and apply to this process.\n"
                                         "- [P-1] After the customer pays by card, a receipt is handed to the customer.")


def test_empty_c3_block_is_c1_text(tmp_path):
    second = {"results": [NOT_STATED["results"][0]]}
    orch, _ = orchestrator(tmp_path, [RELEVANT, SPLIT, NOT_STATED, second])
    result = orch.mediate_case("c", DESCRIPTION)
    assert result["passages"][0]["label"] == INDETERMINATE
    assert result["knowledge_block"] == load_no_knowledge_text(CONFIG) == "No domain knowledge provided."
    assert "P-1" not in result["knowledge_block"]                                # Indeterminate is never passed on


# ---------- audit trail and failures ----------

def test_audit_trail_saves_every_step_and_is_reused(tmp_path):
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, CONFIRMED, REQUIREMENT])
    result = orch.mediate_case("c", DESCRIPTION)
    saved = json.loads((tmp_path / "mediation" / "c.json").read_text(encoding="utf-8"))
    assert saved == result and saved["c3_version"] == "v2"
    p = saved["passages"][0]
    assert p["relevance"]["final_relevant"] is True and p["applicability"]["split"] == SPLIT
    assert p["applicability"]["check"] == CONFIRMED and p["resolution"]["label"] == APPLICABLE
    assert p["requirement"]["requirement"] == REQUIREMENT["requirement"] and not p["requirement"]["requirement_invalid"]
    calls = len(llm.prompts_received)
    assert orch.mediate_case("c", DESCRIPTION) == result and len(llm.prompts_received) == calls


def test_failed_call_gives_mediation_failed(tmp_path):
    orch, _ = orchestrator(tmp_path, [RELEVANT, SPLIT, "bad", "bad"])
    record = orch.mediate_case("c", DESCRIPTION)["passages"][0]
    assert (record["label"], record["failed_step"]) == (MEDIATION_FAILED, "check")


def test_v1_is_unchanged():
    assert changed_items(CONFIG) == []                                           # C3 v1 = its frozen hashes


# ---------- round 1 fixes (docs/C3_V2_DEVELOPMENT.md section 7) ----------

CHECKER = RequirementCheckerV2(CONFIG)
REQ_INPUTS = dict(description=DESCRIPTION, passage_id="P-1", passage_text=PASSAGE, then="the shop must give a receipt",
                  process_step="the customer pays by card", description_quote="The customer pays by card")


def test_split_prompt_has_role_field_and_examples():
    # round 3 (R1): roles in their own field, every situational condition in "if"
    text = project_path(CONFIG["paths"]["applicability_split_prompt_v2"]).read_text(encoding="utf-8")
    assert "Never put a role into \"if\"; roles go into \"roles\"" in text
    assert "EXAMPLE WITH NO SITUATIONAL CONDITION" in text and '{{"roles": ["processor"], "if": []' in text
    assert 'must not contain the words "must", "shall" or "is required to"' in text   # obligation check unchanged


def test_unknown_role_name_gets_the_json_retry(tmp_path):
    record, llm = first_look(tmp_path, [dict(SPLIT, roles=["trader"]), SPLIT, CONFIRMED])
    assert record["label"] == APPLICABLE and len(llm.prompts_received) == 3
    record, llm = first_look(tmp_path, [dict(SPLIT, roles=[]), dict(SPLIT, roles=[])])
    assert record["failed_step"] == "split"                                      # at least one role is required


def test_checker_passes_plain_requirement():
    assert CHECKER.problems(REQUIREMENT["requirement"], PASSAGE) == []


def test_checker_word_limit():
    long = "The customer is told about the receipt " + "and the shop waits " * 10 + "."
    assert CHECKER.measure(long, PASSAGE)["n_words"] > 40
    assert any("words" in p for p in CHECKER.problems(long, PASSAGE))


def test_checker_sentence_limit():
    three = "The customer pays. A receipt is printed. The receipt is handed over."
    assert CHECKER.measure(three, PASSAGE)["n_sentences"] == 3
    assert any("sentences" in p for p in CHECKER.problems(three, PASSAGE))


def test_checker_banned_words():
    for text, word in [("The controller tells the customer.", "controller"), ("Data subjects are told.", "data subject"),
                       ("The shop shall tell the customer.", "shall"), ("Processors keep a list.", "processor")]:
        assert CHECKER.measure(text, PASSAGE)["banned_found"] == [word]
        assert any("not allowed" in p for p in CHECKER.problems(text, PASSAGE))
    assert CHECKER.measure("The shallow shelf is checked.", PASSAGE)["banned_found"] == []   # whole words only


def test_checker_copied_share():
    copied = "If a customer pays by card, the shop must give a receipt."
    m = CHECKER.measure(copied, PASSAGE)
    assert m["n_copied_ngrams"] == m["n_ngrams"] == 8 and m["copied_share"] == 1.0
    assert any("copied" in p for p in CHECKER.problems(copied, PASSAGE))
    assert CHECKER.measure("Paid.", PASSAGE)["copied_share"] == 0.0                          # fewer than 5 words


def test_requirement_prompt_has_limits_and_no_check_note(tmp_path):
    agent = RequirementAgentV2(mock([REQUIREMENT]), logger(tmp_path))
    result = agent.write("x", **REQ_INPUTS)
    assert result == {"requirement": REQUIREMENT["requirement"], "requirement_invalid": False,
                      "attempts": result["attempts"]} and len(result["attempts"]) == 1
    prompt = agent.llm.prompts_received[0]
    assert "at most 40 words" in prompt and '"shall", "controller", "data subject" or "processor"' in prompt
    assert "could not be accepted" not in prompt and "Art" not in prompt.split("JSON SCHEMA")[0]


def test_failed_check_gets_one_retry_with_reason(tmp_path):
    bad = BAD_REQUIREMENT
    agent = RequirementAgentV2(mock([bad, REQUIREMENT]), logger(tmp_path))
    result = agent.write("x", **REQ_INPUTS)
    assert result["requirement"] == REQUIREMENT["requirement"] and result["requirement_invalid"] is False
    assert len(agent.llm.prompts_received) == 2 and [bool(a["problems"]) for a in result["attempts"]] == [True, False]
    assert "uses the word(s) controller" in agent.llm.prompts_received[1]
    assert agent.llm.prompts_received[1].startswith(agent.llm.prompts_received[0])


def test_failing_twice_gives_requirement_invalid_not_passed_on(tmp_path):
    bad = BAD_REQUIREMENT
    orch, llm = orchestrator(tmp_path, [RELEVANT, SPLIT, CONFIRMED, bad, bad])
    result = orch.mediate_case("c", DESCRIPTION)
    p = result["passages"][0]
    assert p["label"] == APPLICABLE and p["requirement"]["requirement_invalid"] is True
    assert p["requirement"]["requirement"] is None and len(p["requirement"]["attempts"]) == 2
    assert len(llm.prompts_received) == 5                                        # no third requirement call
    assert result["knowledge_block"] == load_no_knowledge_text(CONFIG)


def test_round1_eval_counts(tmp_path):
    from src.c3_v2_round1_eval import log_calls, metrics
    bad = BAD_REQUIREMENT
    orch, _ = orchestrator(tmp_path, ["bad", RELEVANT, SPLIT, CONFIRMED, bad, REQUIREMENT])
    record = {"set": "s", "case_id": "c"} | orch.mediate_passage("c", DESCRIPTION, {"rank": 1, "passage_id": "P-1",
                                                                                  "text": PASSAGE}, [])
    log = log_calls(tmp_path)
    assert log == {"calls": 5, "calls_with_retry": 1, "calls_failed_after_retry": 0, "max_retries_seen": 1,
                   "valid_share": 1.0}
    m = metrics([record], orch.applicability_agent.obligation_pattern, log, CONFIG["c3_v2"]["requirement_checks"])
    assert (m["c1_usable_split"], m["c2_if_items_with_obligation_word"], m["requirements_passed_on"],
            m["requirements_needing_check_retry"], m["c5_banned_word"]) == (1, 0, 1, 1, 0)


# ---------- round 2 (section 8): public body, role definitions, triggers kept ----------

ROLE_DEFINITIONS = ("- controller: an organisation that decides why and how personal data is used, for its own purposes.\n"
                    "- processor: an organisation that handles personal data on behalf of another organisation, which "
                    "decides why and how the data is used.")


def test_split_prompt_has_public_body_role_and_example():
    text = project_path(CONFIG["paths"]["applicability_split_prompt_v2"]).read_text(encoding="utf-8")
    assert '"public body": the Commission, a supervisory authority, a Member State' in text
    assert '{{"roles": ["public body"]' in text


def test_public_body_role_contradicted_by_code_gives_not_applicable(tmp_path):
    split = {"roles": ["public body"], "if": [], "then": "the authority must publish a list", "exceptions": []}
    orch, llm = orchestrator(tmp_path, [RELEVANT, split])
    p = orch.mediate_case("c", DESCRIPTION)["passages"][0]
    assert p["label"] == NOT_APPLICABLE and p["requirement"] is None
    assert p["applicability"]["conditions"][0]["decided_by"] == "code rule"
    assert len(llm.prompts_received) == 2                                        # no check, second look or requirement


def test_check_prompt_has_fixed_role_definitions(tmp_path):
    other = "The supplier receives an order. The supplier ships the goods."
    prompts = []
    for description in (DESCRIPTION, other):
        llm = mock([SPLIT, NOT_STATED])
        ApplicabilityAgentV2(llm, logger(tmp_path)).first_look("x", description, "P-1", PASSAGE)
        prompts.append(llm.prompts_received[1])
    for prompt in prompts:                                                       # the same text for every case
        assert "ROLE DEFINITIONS (fixed, the same for every process)\n" + ROLE_DEFINITIONS in prompt
        assert "never confirms it" in prompt
        assert '{"id": "C2", "status": "not_stated", "quote": null}' in prompt  # example: "processed" is no processor


def test_role_definitions_never_reach_the_generator(tmp_path):
    orch, _ = orchestrator(tmp_path, [RELEVANT, SPLIT, CONFIRMED, REQUIREMENT])
    block = orch.mediate_case("c", DESCRIPTION)["knowledge_block"]
    assert REQUIREMENT["requirement"] in block
    assert "ROLE DEFINITIONS" not in block and "on behalf of another organisation" not in block


def test_requirement_prompt_keeps_triggers(tmp_path):
    agent = RequirementAgentV2(mock([REQUIREMENT]), logger(tmp_path))
    agent.write("x", **REQ_INPUTS)
    prompt = agent.llm.prompts_received[0]
    assert 'Keep every trigger and condition the obligation states, for example "on request"' in prompt
    assert '"requirement": "If the customer asks, the customer is told in writing' in prompt
