"""SiblingExpander: adds the other paragraphs of the same article to a list of retrieved candidates (RAG v2).

A rule is often split over several paragraphs of one article (e.g. CRD Article 9: 9(1), 9(1a), 9(2)(a), ...). If the
first-stage retrieval finds one of them, the others ("siblings") may hold the part that fits the process. So, for
every candidate, all passages of the corpus with the same law (directive) and the same article are added, once each,
in corpus order. The article is read from the passage's own fields, never parsed from the id, so letter numbers work
(Article "6a" is not Article 6; paragraph "1a" is a sibling of paragraph 1).

The added passages have no first-stage score; they are SearchResults with score 0.0 and ranks after the candidates.
Which ones entered this way is recorded by the caller (src/rag_v2.py).
"""

from collections import defaultdict

from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult


def article_key(passage: Passage) -> tuple[str, str]:
    """(law, article), e.g. ("2011/83/EU", "6a")."""
    return passage.directive, str(passage.article)


class SiblingExpander:
    """Finds the sibling paragraphs of candidates in a fixed corpus."""

    def __init__(self, passages: list[Passage]):
        self.by_article = defaultdict(list)
        for passage in passages:
            self.by_article[article_key(passage)].append(passage)

    def siblings(self, candidates: list[SearchResult]) -> list[SearchResult]:
        """The passages of the candidates' articles that are not candidates themselves (each once, in order)."""
        seen = {c.passage.id for c in candidates}
        added = []
        for candidate in candidates:
            for passage in self.by_article[article_key(candidate.passage)]:
                if passage.id not in seen:
                    seen.add(passage.id)
                    added.append(SearchResult(passage=passage, score=0.0, rank=len(candidates) + len(added) + 1))
        return added
