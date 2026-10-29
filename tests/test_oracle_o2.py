"""scripts/oracle_o2.py (fix nodoc): real classes only, and the target's whole article from the corpus as input."""

from pathlib import Path

from scripts.oracle_o2 import TARGET, article_ids
from src.agents.applicability_agent_v2 import article_of
from src.config import load_config


def test_input_is_the_target_and_every_other_paragraph_of_its_article():
    ids = article_ids(load_config(), TARGET)
    assert ids[0] == TARGET and len(ids) == len(set(ids)) > 1
    assert all(article_of(i) == article_of(TARGET) for i in ids)


def test_no_redefined_schema_or_patch():
    source = Path("scripts/oracle_o2.py").read_text(encoding="utf-8")
    for forbidden in ("class ItemCheck", "BaseModel", "output_schema =", "OllamaLLM.complete =", ".run ="):
        assert forbidden not in source
