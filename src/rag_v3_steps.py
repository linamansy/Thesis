"""RAG step routing (SR), Study 2 diagnostic. NOT the exploratory RAG v3 (E/F/G) in src/rag_v3.py.

RAG v2 searches with the whole description and its sentences. SR first lets the model list the process steps, then
lets it choose, per step, the law ARTICLES that could matter, and only then searches the paragraphs of those articles.
Nothing in RAG v2, the mediation, config.yaml or the corpus is changed; the existing retrievers and the reranker are
reused as they are.

  S1 steps      StepsAgent lists the steps of the description: {step_id, actor, activity, data_or_object, quote}.
                Code (QuoteChecker) checks that each quote is in the description; a step whose quote fails is dropped
                and logged.
  S2 routing    For every step RoutingAgent gets the list of ALL articles of the corpus, one line each:
                "id: <law full name> – <title> – <first sentence of the article's first paragraph, cut at 40 words>"
                (fix F1, 29 Oct 2026; before: "id: title"), built by code from the corpus file, nothing
                hand-written, and returns at most 3 article ids with a one-line reason.
                Code checks that every id exists in the corpus; unknown ids are dropped and logged.
  S3 ranking    Per step, the existing hybrid search (dense + BM25, RRF) is restricted to the paragraphs of the routed
                articles, the best reranker.candidates are re-scored by the existing cross-encoder, with the step text
                (activity + data_or_object) as the only query. Restriction = search the whole corpus, keep only the
                routed paragraphs, then fuse (retrieval.rrf_k).
  S4 merge      The steps' reranked lists are merged with RRF (retrieval.rrf_k, 60) and the best reranker.top_k (5)
                are kept.

Options of StepRouter (29 Oct 2026; the defaults give exactly the behaviour above, so earlier runs stay reproducible):
  two_view          S2 runs twice per step: once with title-only lines ("id: title", the pre-F1 list) and once with the
                    F1 lines; the step's routes are the union of both (title view first, a repeated id once). S3 then
                    searches the paragraphs of all routed articles.
  fusion="combmax"  S4: a paragraph's score is its highest reranker score over the step lists; ties by its RRF score,
                    then passage id; the best COMBMAX_TOP (10) are kept (moved from scripts/compare_sr_fusion.py).
  parent_expansion  S4: the articles of the fused list, ordered by their best paragraph, are replaced by ALL their
                    paragraphs (corpus order within an article), cut at EXPANSION_CAP (20) passages (moved from
                    scripts/parent_expansion_sr.py).

The agents use the same model and settings as the C3 agents (config.yaml model and llm). No frozen file is written.
"""

import copy
import re

from pydantic import BaseModel, Field

from src.agents.base_agent import BaseAgent
from src.config import project_path
from src.mediation.quote_checker import QuoteChecker
from src.retrieval.hybrid_retriever import reciprocal_rank_fusion
from src.retrieval.passage import Passage
from src.retrieval.search_result import SearchResult

MAX_ROUTES = 3
OPENING_WORDS = 40   # S2 article line: the article's first sentence is cut at this many words
COMBMAX_TOP = 10     # fusion="combmax": the passages kept after CombMAX
EXPANSION_CAP = 20   # parent_expansion: the most passages after expansion
FUSIONS = ("rrf", "combmax")
STEPS_PROMPT = "prompts/rag_v3_steps.txt"
ROUTING_PROMPT = "prompts/rag_v3_routing.txt"


# ---------- corpus helpers ----------

def article_id_of(passage_id: str) -> str:
    """'GDPR-Art13-1' -> 'GDPR-Art13'; 'GDPR-Art5-1-a' -> 'GDPR-Art5'."""
    law, rest = passage_id.split("-Art", 1)
    return f"{law}-Art{rest.split('-')[0]}"


def article_index(passages: list[Passage]) -> dict[str, str]:
    """{article id: article title} in corpus order, built from the passages only."""
    index = {}
    for p in passages:
        index.setdefault(article_id_of(p.id), p.title)
    return index


def articles_text(index: dict[str, str]) -> str:
    return "\n".join(f"{article_id}: {title}" for article_id, title in index.items())


def first_sentence(passage: Passage, max_words: int = OPENING_WORDS) -> str:
    """The first sentence of a passage's body (after its header line, without a paragraph number such as "1."), cut
    at max_words words."""
    body = passage.text.split("\n", 1)[1] if "\n" in passage.text else passage.text
    body = re.sub(r"^\(?\d+[a-z]?[.)]\s+", "", " ".join(body.split()))
    sentence = re.split(r"(?<=[.!?])\s", body, maxsplit=1)[0]
    words = sentence.split()
    return " ".join(words[:max_words]) + (" ..." if len(words) > max_words else "")


def article_lines(passages: list[Passage]) -> dict[str, str]:
    """{article id: "<law full name> – <title> – <first sentence of its first paragraph>"} in corpus order, built from
    the corpus only: the law name is the passage header before " - Article", the first paragraph is the article's
    first passage in the corpus."""
    lines = {}
    for p in passages:
        article_id = article_id_of(p.id)
        if article_id not in lines:
            law = p.text.split(" - Article", 1)[0].strip()
            lines[article_id] = f"{law} – {p.title} – {first_sentence(p)}"
    return lines


# ---------- S1 steps ----------

class Step(BaseModel):
    step_id: str = Field(description="S1, S2, ... in the order of the description")
    actor: str = Field(description="Who does the step")
    activity: str = Field(description="What is done, in a few words")
    data_or_object: str = Field(description="The data, document or object the step handles; empty string if none")
    quote: str = Field(description="Exact words copied from the process description that state the step")


class StepsOutput(BaseModel):
    steps: list[Step]


class StepsAgent(BaseAgent):
    output_schema = StepsOutput
    json_format = True

    def __init__(self, llm, logger, max_retries: int | None = None):
        super().__init__(llm, logger, max_retries, template_path=project_path(STEPS_PROMPT))

    def build_prompt(self, description: str) -> str:
        return self.template.format(schema=self.schema_text(), description=description.strip())


def check_steps(steps: list[dict], description: str) -> tuple[list[dict], list[dict]]:
    """(kept, dropped): a step is kept only if its quote is found in the description (QuoteChecker). Dropped steps
    get a 'dropped_because' reason."""
    checker, kept, dropped = QuoteChecker(), [], []
    for step in steps:
        found = checker.found(step["quote"], description)
        record = dict(step, quote_found=bool(found))
        if found:
            kept.append(record)
        else:
            dropped.append(dict(record, dropped_because="quote not found in the description" if found is False
                                else "no quote given"))
    return kept, dropped


def step_query(step: dict) -> str:
    """The S3 query: activity + data_or_object."""
    return " ".join(part.strip() for part in (step["activity"], step["data_or_object"]) if part and part.strip())


# ---------- S2 routing ----------

class Route(BaseModel):
    article_id: str = Field(description="An article id from the list, written exactly as in the list")
    reason: str = Field(description="One short sentence on how the article relates to the step")


class RoutingOutput(BaseModel):
    routes: list[Route] = Field(max_length=MAX_ROUTES, description=f"At most {MAX_ROUTES} articles")


class RoutingAgent(BaseAgent):
    output_schema = RoutingOutput
    json_format = True

    def __init__(self, llm, logger, max_retries: int | None = None):
        super().__init__(llm, logger, max_retries, template_path=project_path(ROUTING_PROMPT))

    def build_prompt(self, step: dict, articles: str) -> str:
        return self.template.format(schema=self.schema_text(), actor=step["actor"], activity=step["activity"],
                                    data_or_object=step["data_or_object"] or "(none)", articles=articles)


def check_routes(routes: list[dict], index: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(kept, dropped): an id must exist in the corpus; repeated ids are dropped too."""
    kept, dropped, seen = [], [], set()
    for route in routes:
        if route["article_id"] not in index:
            dropped.append(dict(route, dropped_because="article id not in the corpus"))
        elif route["article_id"] in seen:
            dropped.append(dict(route, dropped_because="repeated article id"))
        else:
            seen.add(route["article_id"])
            kept.append(dict(route, title=index[route["article_id"]]))
    return kept, dropped


# ---------- S3 / S4 ----------

def merge_rankings(rankings: dict[str, list[str]], rrf_k: int, top_k: int) -> list[dict]:
    """S4: RRF over the steps' ranked passage-id lists (best first). Ties: passage id."""
    fused = reciprocal_rank_fusion(list(rankings.values()), rrf_k)
    order = sorted(fused, key=lambda pid: (-fused[pid], pid))[:top_k]
    return [{"rank": rank, "passage_id": pid, "rrf_score": fused[pid],
             "rank_in_steps": {s: ranking.index(pid) + 1 for s, ranking in rankings.items() if pid in ranking}}
            for rank, pid in enumerate(order, start=1)]


def step_lists(s3: dict) -> dict[str, list[dict]]:
    """{step id: its ranked rows (passage_id, rerank_score), best first} from an S3 result."""
    return {step: v["ranking"] for step, v in s3["per_step"].items()}


def rrf_order(lists: dict[str, list[dict]], rrf_k: int) -> list[dict]:
    """The full RRF order of the step lists as [{passage_id, rrf_score}]."""
    full = merge_rankings({s: [r["passage_id"] for r in rows] for s, rows in lists.items()}, rrf_k, 10 ** 6)
    return [{"passage_id": row["passage_id"], "rrf_score": row["rrf_score"]} for row in full]


def combmax_order(lists: dict[str, list[dict]], rrf_k: int) -> list[dict]:
    """CombMAX: highest reranker score over the steps; ties by RRF score, then passage id."""
    best = {}
    for rows in lists.values():
        for r in rows:
            best[r["passage_id"]] = max(best.get(r["passage_id"], r["rerank_score"]), r["rerank_score"])
    rrf = {row["passage_id"]: row["rrf_score"] for row in rrf_order(lists, rrf_k)}
    order = sorted(best, key=lambda pid: (-best[pid], -rrf[pid], pid))
    return [{"passage_id": pid, "max_rerank_score": best[pid], "rrf_score": rrf[pid]} for pid in order]


def expand(top_ids: list[str], corpus_ids: list[str], cap: int = EXPANSION_CAP) -> dict:
    """Parent expansion: the articles in order of their best paragraph in top_ids, ALL their paragraphs (corpus order
    within an article), cut at cap."""
    articles = list(dict.fromkeys(article_id_of(pid) for pid in top_ids))
    full = [pid for article in articles for pid in corpus_ids if article_id_of(pid) == article]
    return {"articles": articles, "passages": full[:cap], "cut": full[cap:]}


def union_routes(views: dict[str, list[dict]]) -> list[dict]:
    """two_view: the kept routes of all views in view order; an id routed by several views is kept once (its first
    route), with the list of views that routed it."""
    union = {}
    for view, routes in views.items():
        for route in routes:
            union.setdefault(route["article_id"], dict(route, views=[]))["views"].append(view)
    return list(union.values())


class StepRouter:
    """S1-S4 for one description. dense, sparse, reranker: the existing retrievers (or fakes in tests).
    two_view, fusion, parent_expansion: see the module text; the defaults are the original SR."""

    def __init__(self, config: dict, steps_agent, routing_agent, passages: list[Passage], dense, sparse, reranker,
                 two_view: bool = False, fusion: str = "rrf", parent_expansion: bool = False):
        if fusion not in FUSIONS:
            raise ValueError(f"fusion must be one of {FUSIONS}, not {fusion!r}")
        self.two_view, self.fusion, self.parent_expansion = two_view, fusion, parent_expansion
        self.steps_agent, self.routing_agent = steps_agent, routing_agent
        self.passages = passages
        self.dense, self.sparse, self.reranker = dense, sparse, reranker
        self.index = article_index(passages)
        self.rrf_k = config["retrieval"]["rrf_k"]
        self.n_candidates = config["reranker"]["candidates"]
        self.top_k = config["reranker"]["top_k"]

    def steps(self, case_id: str, description: str) -> dict:
        out = self.steps_agent.run(case_id, description=description)
        raw = [s.model_dump() for s in out.steps] if out else None
        kept, dropped = check_steps(raw or [], description)
        return {"stage": "S1 steps", "failed": out is None, "raw_steps": raw, "steps": kept, "dropped": dropped}

    def route_once(self, case_id: str, step: dict, articles: str) -> dict:
        out = self.routing_agent.run(case_id, step=step, articles=articles)
        raw = [r.model_dump() for r in out.routes] if out else None
        kept, dropped = check_routes(raw or [], self.index)
        return {"failed": out is None, "raw_routes": raw, "routes": kept, "dropped": dropped}

    def route(self, case_id: str, steps: list[dict]) -> dict:
        lines = articles_text(article_lines(self.passages))
        if not self.two_view:
            per_step = {step["step_id"]: self.route_once(case_id, step, lines) for step in steps}
            return {"stage": "S2 article routing", "n_articles_offered": len(self.index), "per_step": per_step}
        texts = {"title": articles_text(self.index), "law_title_sentence": lines}
        per_step = {}
        for step in steps:
            views = {view: self.route_once(case_id, step, text) for view, text in texts.items()}
            per_step[step["step_id"]] = {
                "failed": any(v["failed"] for v in views.values()),
                "routes": union_routes({view: v["routes"] for view, v in views.items()}),
                "dropped": [dict(d, view=view) for view, v in views.items() for d in v["dropped"]],
                "views": views}
        return {"stage": "S2 article routing (two views, union of routes)", "n_articles_offered": len(self.index),
                "views": list(texts), "per_step": per_step}

    def rank_step(self, step: dict, article_ids: list[str]) -> dict:
        """S3 for one step: hybrid search restricted to the routed articles, then the reranker."""
        query, allowed = step_query(step), set(article_ids)
        pool = len(self.passages)   # search everything, keep only the routed paragraphs
        lists = []
        for results in (self.dense.search(query, pool), self.sparse.search(query, pool)):
            lists.append([r for r in results if article_id_of(r.passage.id) in allowed])
        fused = reciprocal_rank_fusion([[r.passage.id for r in lst] for lst in lists], self.rrf_k)
        by_id = {r.passage.id: r.passage for lst in lists for r in lst}
        order = sorted(fused, key=lambda pid: (-fused[pid], pid))[:self.n_candidates]
        hybrid = [SearchResult(passage=by_id[pid], score=fused[pid], rank=i) for i, pid in enumerate(order, 1)]
        reranked = self.reranker.rerank([query], hybrid, top_k=len(hybrid))
        hybrid_rank = {c.passage.id: c.rank for c in hybrid}
        fused_score = {c.passage.id: c.score for c in hybrid}
        return {"step_id": step["step_id"], "query": query, "routed_articles": article_ids,
                "n_paragraphs_in_routed_articles": sum(article_id_of(p.id) in allowed for p in self.passages),
                "ranking": [{"rank": r.rank, "passage_id": r.passage.id, "rerank_score": r.score,
                             "hybrid_rank": hybrid_rank[r.passage.id], "fused_score": fused_score[r.passage.id]}
                            for r in reranked]}

    def rank_and_merge(self, steps: list[dict], routes: dict) -> tuple[dict, dict]:
        """(S3 result, S4 result). A step without a valid route is skipped (logged)."""
        ranked, skipped = {}, []
        for step in steps:
            ids = [r["article_id"] for r in routes["per_step"][step["step_id"]]["routes"]]
            if ids:
                ranked[step["step_id"]] = self.rank_step(step, ids)
            else:
                skipped.append(step["step_id"])
        s3 = {"stage": "S3 paragraph ranking", "per_step": ranked, "steps_without_route": skipped}
        texts = {p.id: p.text for p in self.passages}
        if self.fusion != "rrf" or self.parent_expansion:
            return s3, self.merge_with_options(s3, texts)
        top = merge_rankings({s: [r["passage_id"] for r in v["ranking"]] for s, v in ranked.items()},
                             self.rrf_k, self.top_k)
        for row in top:
            row["text"] = texts[row["passage_id"]]
        s4 = {"stage": "S4 merge (RRF over the steps)", "rrf_k": self.rrf_k, "top_k": self.top_k, "passages": top}
        return s3, s4

    def merge_with_options(self, s3: dict, texts: dict[str, str]) -> dict:
        """S4 with fusion="combmax" and/or parent_expansion. "fused" = the fused list, "passages" = the final set."""
        if self.fusion == "combmax":
            top_k, order = COMBMAX_TOP, combmax_order(step_lists(s3), self.rrf_k)
        else:
            top_k, order = self.top_k, rrf_order(step_lists(s3), self.rrf_k)
        fused = [dict(row, rank=rank) for rank, row in enumerate(order[:top_k], start=1)]
        s4 = {"stage": f"S4 merge ({self.fusion} over the steps" + (", parent expansion)" if self.parent_expansion
                                                                    else ")"),
              "fusion": self.fusion, "rrf_k": self.rrf_k, "top_k": top_k, "fused": fused}
        if not self.parent_expansion:
            return s4 | {"passages": [dict(row, text=texts[row["passage_id"]]) for row in fused]}
        out = expand([row["passage_id"] for row in fused], [p.id for p in self.passages])
        fused_rank = {row["passage_id"]: row["rank"] for row in fused}
        return s4 | {"expansion_cap": EXPANSION_CAP, "articles": out["articles"], "cut": out["cut"],
                     "passages": [{"rank": rank, "passage_id": pid, "fused_rank": fused_rank.get(pid),
                                   "text": texts[pid]} for rank, pid in enumerate(out["passages"], start=1)]}

    def run(self, case_id: str, description: str) -> dict:
        s1 = self.steps(case_id, description)
        s2 = self.route(case_id, s1["steps"])
        s3, s4 = self.rank_and_merge(s1["steps"], s2)
        return {"S1": s1, "S2": s2, "S3": s3, "S4": s4}


def build_retrievers(config: dict) -> tuple[list[Passage], object, object, object]:
    """(passages, dense, sparse, reranker): the RAG v2 retrievers on the Study 2 corpus, loaded as RAG v2 loads them."""
    from src.rag_v2 import RagV2Retriever, corpus_view
    base = RagV2Retriever(corpus_view(copy.deepcopy(config)))
    return base.dense.passages, base.dense, base.sparse, base.reranker
