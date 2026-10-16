"""Tests for the extra-task (unsupported additions) diagnostic, with a fake matcher (no embedding model)."""

from src.config import load_config
from src.evaluate import Evaluator, split_sentences

CONFIG = load_config()


class WordMatcher:
    """Fake TaskMatcher: similarity = share of the label's words that appear in the text."""
    model_name, threshold = "fake", 0.75

    def best_similarity(self, labels, texts):
        def sim(label, text):
            words = label.lower().split()
            return sum(w in text.lower() for w in words) / len(words)
        return [max((sim(label, t) for t in texts), default=0.0) for label in labels]


def test_split_sentences():
    assert split_sentences("First sentence here. Second one is here.\n- [CRD-Art9-1] a list line here") == \
        ["First sentence here.", "Second one is here.", "[CRD-Art9-1] a list line here"]


def test_knowledge_traceable_extra_tasks(tmp_path):
    evaluator = Evaluator(CONFIG, WordMatcher())
    case_dir = tmp_path / "C2" / "19"
    case_dir.mkdir(parents=True)
    (case_dir / "knowledge_block.txt").write_text(
        "[CRD-Art9-1] The consumer shall have a period of 14 days to withdraw from a distance contract.",
        encoding="utf-8")
    extra = [{"generated_id": "t1", "generated_label": "withdraw from contract"},
             {"generated_id": "t2", "generated_label": "unrelated xyz"}]

    result = evaluator.extra_task_diagnostics("C2", "19", case_dir, extra)

    assert result["n_extra_tasks"] == 2
    assert result["n_extra_knowledge_traceable"] == 1
    assert result["extra_tasks"][0]["knowledge_traceable"] is True


def test_c1_has_no_knowledge_traceable_tasks(tmp_path):
    evaluator = Evaluator(CONFIG, WordMatcher())
    extra = [{"generated_id": "t1", "generated_label": "withdraw from contract"}]
    result = evaluator.extra_task_diagnostics("C1", "19", tmp_path, extra)
    assert result == {"n_extra_tasks": 1, "n_extra_knowledge_traceable": 0,
                      "extra_tasks": [{"label": "withdraw from contract", "knowledge_traceable": False}]}
