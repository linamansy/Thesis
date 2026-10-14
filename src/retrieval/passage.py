"""Passage: one retrievable piece of legal text (usually one numbered paragraph of an article)."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Passage:
    id: str          # e.g. "CRD-Art9-1" = Consumer Rights Directive, Article 9, paragraph 1
    directive: str   # directive number, e.g. "2011/83/EU"
    article: int     # article number
    paragraph: int   # paragraph number (for the definitions article: the definition number)
    title: str       # article title, e.g. "Right of withdrawal"
    text: str        # the passage text, starting with the directive name and article title
    n_chars: int     # length of text in characters

    def to_dict(self) -> dict:
        return asdict(self)


def load_passages(path: Path) -> list[Passage]:
    """Read data/knowledge/passages.jsonl (one passage per line) in file order."""
    with open(path, encoding="utf-8") as f:
        return [Passage(**json.loads(line)) for line in f if line.strip()]
