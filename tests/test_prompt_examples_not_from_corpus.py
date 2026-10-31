"""The made-up examples in the prompts must not copy law text.

Every prompt in prompts/ is scanned. An example block starts at a line beginning with "EXAMPLE" and ends at the next
empty line. The test fails if any 8 consecutive words of an example block appear, in the same order, in a passage of
any corpus file in config.yaml (Study 1, GDPR, the Study 2 laws and the Study 2 corpus), and names the phrase.
Words = lower-case letters and digits; punctuation is ignored.
"""

import json
import re

from src.config import load_config, project_path

N_WORDS = 8
CONFIG = load_config()
CORPUS_FILES = [CONFIG["paths"]["passages"], CONFIG["study2_gdpr"]["passages"],
                CONFIG["study2_gdpr"]["passages_restricted"], CONFIG["study2_laws"]["passages_new_laws_all"],
                CONFIG["study2_laws"]["passages_combined"], CONFIG["study2_corpus"]["passages"]]
PROMPT_DIR = project_path(CONFIG["paths"]["applicability_split_prompt_v2"]).parent


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def ngrams(text: str, n: int = N_WORDS) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def example_blocks(prompt_text: str) -> list[str]:
    """The text of every example block (the lines after an "EXAMPLE ..." heading, up to the next empty line)."""
    blocks, current = [], None
    for line in prompt_text.splitlines():
        if line.startswith("EXAMPLE"):
            current = []
            blocks.append(current)
        elif current is not None:
            if line.strip():
                current.append(line)
            else:
                current = None
    return ["\n".join(block) for block in blocks]


def corpus_ngrams() -> set[tuple[str, ...]]:
    grams = set()
    for path in CORPUS_FILES:
        for line in project_path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                grams |= ngrams(json.loads(line)["text"])
    return grams


def overlaps(prompt_texts: dict[str, str], grams: set) -> list[str]:
    found = []
    for name, text in prompt_texts.items():
        for block in example_blocks(text):
            found += [f"{name}: '{' '.join(g)}'" for g in sorted(ngrams(block) & grams)]
    return found


def test_no_prompt_example_copies_8_words_of_a_corpus_passage():
    prompts = {p.name: p.read_text(encoding="utf-8") for p in sorted(PROMPT_DIR.glob("*.txt"))}
    assert sum(len(example_blocks(t)) for t in prompts.values()) == 17   # the scan really finds all 17 example blocks
    found = overlaps(prompts, corpus_ngrams())
    assert not found, "prompt example copies corpus text: " + "; ".join(found)


def test_the_scan_reports_a_copied_phrase():
    passage = "The trader shall inform the consumer of the right of withdrawal before the contract is concluded."
    prompt = 'Intro\n\nEXAMPLE (made up)\nRule: "A seller shall inform the consumer of the right of withdrawal early."\n'
    assert overlaps({"p.txt": prompt}, ngrams(passage)) == [
        "p.txt: 'inform the consumer of the right of withdrawal'", "p.txt: 'shall inform the consumer of the right of'"]
    assert overlaps({"p.txt": "No example here: shall inform the consumer of the right of withdrawal"},
                    ngrams(passage)) == []
