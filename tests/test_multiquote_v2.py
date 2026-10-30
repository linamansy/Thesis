"""Tests for multi-quote evidence (fix multiquote, 30 Oct 2026): CheckIfCallV2 and SecondLookCallV2 answer with
"quotes", a list of 1-3 sentences of the description. Each quote is checked on its own by match_quote; confirmed or
contradicted needs at least one quote that is found; the verifier gets all found quotes together. MockLLM answers only.
"""

import itertools
import json

import pytest
from pydantic import ValidationError

from src.agents.applicability_agent_v2 import ApplicabilityAgentV2, CheckOutputV2
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE

DESCRIPTION = ("The customer chooses a product. The shop sends the customer a bill. "
               "The customer pays the bill by card. The shop sends the product.")
PASSAGE = "If the customer has received a bill and has paid, the shop must give a receipt."
SPLIT = {"roles": ["controller"], "if": ["the customer has received a bill and has paid it"],
         "then": "the shop must give a receipt", "exceptions": []}
YES = {"answer": "yes", "reason": "Together the sentences say the bill was sent and paid."}
NO = {"answer": "no", "reason": "The sentences do not say it."}
RUN_IDS = itertools.count()


def check(status, quotes):
    return {"results": [{"id": "C1", "closest_sentence": None, "status": status, "quotes": quotes}]}


def first_look(tmp_path, answers):
    llm = MockLLM([json.dumps(a) for a in answers])
    agent = ApplicabilityAgentV2(llm, RunLogger(tmp_path, "C3V2", f"m{next(RUN_IDS)}"))
    record = agent.first_look("x", DESCRIPTION, "P-1", PASSAGE)
    return agent, record, llm, record["conditions"][1]


def test_two_quotes_are_checked_and_saved_as_a_list(tmp_path):
    quotes = ["the shop sends the customer a bill", "The customer PAYS the bill by card"]
    _, record, _, c1 = first_look(tmp_path, [SPLIT, check("confirmed", quotes), YES])
    assert c1["quotes"] == quotes and c1["quotes_found"] == [True, True]
    assert c1["quotes_canonical"] == ["The shop sends the customer a bill", "The customer pays the bill by card"]
    assert (c1["status"], c1["quote_found"], record["label"]) == ("confirmed", True, APPLICABLE)


def test_the_verifier_gets_all_valid_quotes_together_in_one_call(tmp_path):
    quotes = ["The shop sends the customer a bill", "The customer pays in cash", "The customer pays the bill by card"]
    _, _, llm, c1 = first_look(tmp_path, [SPLIT, check("confirmed", quotes), YES])
    assert len(llm.prompts_received) == 3                                      # split, check, ONE verifier call
    prompt = llm.prompts_received[2]
    assert "- The shop sends the customer a bill\n- The customer pays the bill by card\n" in prompt
    assert "pays in cash" not in prompt                                        # a quote not found is not sent
    assert "taken together, state that the statement is true?" in prompt
    assert c1["quotes_found"] == [True, False, True] and c1["status"] == "confirmed"


def test_one_valid_quote_is_enough(tmp_path):
    _, _, _, c1 = first_look(tmp_path, [SPLIT, check("confirmed", ["The customer pays in cash",
                                                                   "The customer pays the bill by card"]), YES])
    assert (c1["status"], c1["quote_found"], c1["quotes_canonical"]) == \
        ("confirmed", True, ["The customer pays the bill by card"])


def test_no_valid_quote_is_downgraded_without_a_verifier_call(tmp_path):
    _, record, llm, c1 = first_look(tmp_path, [SPLIT, check("confirmed", ["The customer pays in cash",
                                                                          "The bill is lost"])])
    assert (c1["status"], c1["quote_found"], c1["downgrade_cause"], c1["verifier"]) == \
        ("not_stated", False, "quote not found", None)
    assert len(llm.prompts_received) == 2 and record["label"] == INDETERMINATE


def test_an_empty_list_is_no_quote(tmp_path):
    _, _, _, c1 = first_look(tmp_path, [SPLIT, check("confirmed", [])])
    assert (c1["status"], c1["quote_found"], c1["quotes_canonical"]) == ("not_stated", None, [])


def test_the_verifier_rejects_the_quotes_together(tmp_path):
    _, record, _, c1 = first_look(tmp_path, [SPLIT, check("confirmed", ["The shop sends the customer a bill"]), NO])
    assert (c1["status"], c1["downgrade_cause"], c1["quotes_canonical"]) == \
        ("not_stated", "verifier rejected", ["The shop sends the customer a bill"])
    assert record["label"] == INDETERMINATE


def test_the_same_quote_twice_is_sent_once(tmp_path):
    _, _, llm, c1 = first_look(tmp_path, [SPLIT, check("confirmed", ["The shop sends the customer a bill",
                                                                     "the shop sends the customer a bill"]), YES])
    assert c1["quotes_canonical"] == ["The shop sends the customer a bill"]
    assert llm.prompts_received[2].count("The shop sends the customer a bill") == 1


def test_the_second_look_uses_quotes_too(tmp_path):
    agent, record, llm, c1 = first_look(tmp_path, [SPLIT, check("not_stated", []),
                                                   check("confirmed", ["The shop sends the customer a bill",
                                                                       "The customer pays the bill by card"]), YES])
    agent.second_look("x", DESCRIPTION, record, "P-1", [])
    assert (c1["status"], c1["decided_by"], len(c1["quotes_canonical"])) == ("confirmed", "second look", 2)
    assert record["label"] == APPLICABLE and "taken together" in llm.prompts_received[3]


def test_at_most_three_quotes():
    with pytest.raises(ValidationError):
        CheckOutputV2.model_validate(check("confirmed", ["a b c", "d e f", "g h i", "j k l"]))
    assert CheckOutputV2.model_json_schema()["$defs"]["ItemCheck"]["properties"]["quotes"]["maxItems"] == 3


def test_both_prompts_ask_for_a_list_of_quotes(tmp_path):
    agent = ApplicabilityAgentV2(MockLLM(["{}"]), RunLogger(tmp_path, "C3V2", "p"))
    for call in (agent.check_call, agent.second_look_call):
        assert "a list of 1 to 3 sentences of the process description" in call.template
        assert '"quote":' not in call.template and "use null" not in call.template
