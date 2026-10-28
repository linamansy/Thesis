"""RequirementCheckerV2: code checks of a C3 v2 requirement (docs/C3_V2_DEVELOPMENT.md section 7, criteria 4-6).

A requirement passes only if
  - it has at most max_words words and at most max_sentences sentences,
  - it contains none of the banned words (legal role names and "shall"; case-insensitive, plurals included),
  - at most max_copied_share of its word sequences of length ngram also appear in the legal passage.
All limits are in config.yaml c3_v2.requirement_checks. problems() returns the reasons a requirement fails (an empty
list = it passes); the reasons are sent back to the model in the one retry of RequirementAgentV2.

Round 3 (R6), quote_problems(): the step_quote must appear in the process description, every trigger in the FULL
legal passage and every kept_as in the requirement (QuoteChecker: whole words, same order). Whether the list names
EVERY trigger is not checked by code; it is judged by reading (criterion 11).

Fix A (28 Oct 2026): a trigger used to be checked against the THEN part only. But the IF/THEN split moves triggers
("at the time when personal data are obtained") into the IF part by design, so valid triggers were rejected and the
rule lost its requirement (GDPR-Art13-2-a, case 01.1). A trigger is therefore checked against the whole passage
(IF and THEN together); a trigger that is nowhere in the passage is still rejected.

Duty check (28 Oct 2026): a requirement could pass every check above while stating no duty at all - GDPR-Art13-2-a
(case 01.1) passed with an empty triggers list and a requirement that only restated the process step ("sales staff
write down the customer's name ..."). duty_problems() therefore requires the answer's duty: from_then must be at
least MIN_DUTY_WORDS words copied from the THEN part (the obligation), kept_as must be copied from the requirement
itself. An empty triggers list is accepted only for a rule whose IF part has no situational condition (a role-only
rule); otherwise the reason "triggers missing" is returned.
"""

import re

from src.config import load_config
from src.mediation.quote_checker import QuoteChecker

WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
MIN_DUTY_WORDS = 3   # shortest duty quote accepted (fixed by the task of 28 Oct 2026, not a config parameter)


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
        self.quote_checker = QuoteChecker()

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

    def quote_problems(self, output, description: str, passage_text: str, then: str = "",
                       if_items: list[dict] | None = None) -> list[str]:
        """output: RequirementOutputV2 (requirement, step_quote, triggers, duty).

        passage_text is the FULL legal passage (see fix A above), not only its THEN part; then is the THEN part
        (the obligation) and is used for the duty check; if_items are the IF items of the split (each with its
        "kind"), used only for the empty-triggers rule. if_items None = the rule's IF part is unknown, so that
        rule is not checked."""
        found = []
        if not self.quote_checker.found(output.step_quote, description):
            found.append("the step_quote is not copied word for word from the process description")
        found += self.duty_problems(output, then)
        if not output.triggers and any(item.get("kind") == "situation" for item in (if_items or [])):
            found.append("triggers missing: the rule applies only under situational conditions, so the triggers list "
                         "must not be empty")
        for t in output.triggers:
            if not self.quote_checker.found(t.trigger, passage_text):
                found.append(f'the trigger "{t.trigger}" is not copied word for word from the legal passage')
            if not self.quote_checker.found(t.kept_as, output.requirement):
                found.append(f'the kept_as words "{t.kept_as}" are not copied word for word from the requirement')
        return found

    def duty_problems(self, output, then: str) -> list[str]:
        """The duty check (28 Oct 2026): the requirement must keep the duty of the obligation.

        duty.from_then must be at least MIN_DUTY_WORDS words copied from the THEN part, duty.kept_as must be copied
        from the requirement itself. Every reason names the check that failed."""
        duty = getattr(output, "duty", None)
        if duty is None or not words(duty.from_then or ""):
            return ["duty missing: give the words of the OBLIGATION that say what must be done (duty.from_then) and "
                    "the words of your requirement that keep them (duty.kept_as)"]
        found = []
        if len(words(duty.from_then)) < MIN_DUTY_WORDS:
            found.append(f'the duty from_then "{duty.from_then}" has fewer than {MIN_DUTY_WORDS} words; quote the '
                         f'words of the OBLIGATION that say what must be done')
        if not self.quote_checker.found(duty.from_then, then):
            found.append(f'the duty from_then "{duty.from_then}" is not copied word for word from the OBLIGATION')
        if not self.quote_checker.found(duty.kept_as, output.requirement):
            found.append(f'the duty kept_as words "{duty.kept_as}" are not copied word for word from the requirement, '
                         f'so the requirement does not state the duty')
        return found
