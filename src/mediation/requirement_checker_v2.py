"""RequirementCheckerV2: code checks of a C3 v2 requirement (docs/C3_V2_DEVELOPMENT.md section 7, criteria 4-6).

A requirement passes only if
  - it has at most max_words words and at most max_sentences sentences,
  - it contains none of the banned words (legal role names and "shall"; case-insensitive, plurals included),
  - at most max_copied_share of its word sequences of length ngram also appear in the legal passage.
All limits are in config.yaml c3_v2.requirement_checks. problems() returns the reasons a requirement fails (an empty
list = it passes); the reasons are sent back to the model in the one retry of RequirementAgentV2.
"""

import re

from src.config import load_config

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def words(text: str) -> list[str]:
    """Lowercase words without punctuation."""
    return WORD.findall(text.lower())


def ngrams(tokens: list[str], n: int) -> list[tuple]:
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


class RequirementCheckerV2:

    def __init__(self, config: dict | None = None):
        settings = (config or load_config())["c3_v2"]["requirement_checks"]
        self.max_words = settings["max_words"]
        self.max_sentences = settings["max_sentences"]
        self.banned_words = settings["banned_words"]
        self.n = settings["ngram"]
        self.max_copied_share = settings["max_copied_share"]
        alternatives = "|".join(re.escape(w) for w in self.banned_words)
        self.banned_pattern = re.compile(rf"\b({alternatives})s?\b", re.IGNORECASE)

    def measure(self, requirement: str, passage_text: str) -> dict:
        """The numbers the checks use."""
        tokens = words(requirement)
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", requirement.strip()) if words(s)]
        grams = ngrams(tokens, self.n)
        passage_grams = set(ngrams(words(passage_text), self.n))
        copied = sum(g in passage_grams for g in grams)
        return {"n_words": len(tokens), "n_sentences": len(sentences),
                "banned_found": sorted({m.group(1).lower() for m in self.banned_pattern.finditer(requirement)}),
                "n_ngrams": len(grams), "n_copied_ngrams": copied,
                "copied_share": round(copied / len(grams), 4) if grams else 0.0}

    def problems(self, requirement: str, passage_text: str) -> list[str]:
        m = self.measure(requirement, passage_text)
        found = []
        if m["n_words"] > self.max_words:
            found.append(f"the requirement has {m['n_words']} words; at most {self.max_words} are allowed")
        if m["n_sentences"] > self.max_sentences:
            found.append(f"the requirement has {m['n_sentences']} sentences; at most {self.max_sentences} are allowed")
        if m["banned_found"]:
            found.append(f"the requirement uses the word(s) {', '.join(m['banned_found'])}, which are not allowed")
        if m["copied_share"] > self.max_copied_share:
            found.append(f"{m['n_copied_ngrams']} of its {m['n_ngrams']} sequences of {self.n} words are copied from "
                         f"the legal passage; use your own plain words")
        return found
