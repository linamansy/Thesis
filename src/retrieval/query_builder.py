"""QueryBuilder: turns one case description into the list of retrieval queries.

The PMo descriptions have one sentence per line. Queries for a case:
  1. the full description (all lines joined with spaces) as one query
  2. every line (sentence) as its own query

Cleaning:
  - whitespace is tidied (Windows line endings, trailing and double spaces)
  - empty lines are skipped
  - a leading "Title:" label is removed, but the title text itself stays a query
    ("Title: Contract" -> "Contract")
  - a sentence that occurs twice becomes one query, so it does not count double in the fusion
No LLM is used.
"""

import re

TITLE_LABEL = re.compile(r"^title\s*:\s*", re.IGNORECASE)


class QueryBuilder:
    """Builds the queries of one case."""

    def sentences(self, description: str) -> list[str]:
        """The cleaned, non-empty lines of the description, in order, without duplicates."""
        sentences = []
        for line in description.splitlines():
            line = TITLE_LABEL.sub("", " ".join(line.split()))
            if line and line not in sentences:
                sentences.append(line)
        return sentences

    def build(self, description: str) -> list[str]:
        """[full description, sentence 1, sentence 2, ...]"""
        sentences = self.sentences(description)
        if not sentences:
            return []
        full = " ".join(sentences)
        return [full] + [s for s in sentences if s != full]  # a one-line description gives one query
