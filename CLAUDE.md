# Thesis project: Explicit domain-knowledge mediation for LLM-based BPMN generation

## Goal
Compare three conditions for generating BPMN from text:
- C1: process description only -> generator
- C2: description + raw retrieved rule passages (RAG) -> same generator
- C3: description + the same retrieved passages after mediation agents -> same generator

The generator (model, prompt template, JSON schema, temperature) must be IDENTICAL in all three conditions. Only the knowledge block in the prompt differs:
- C1: empty knowledge block
- C2: the 5 frozen passages, verbatim, with their IDs
- C3: requirements produced by the mediation agents + a list of rules marked Indeterminate

## Data
- PMo dataset in data/raw/pmo/ (descriptions/*.txt = process text, bpmn/*.bpmn = ground truth)
- Working cases (Order & Purchasing domain): 01, 03, 05, 06, 10, 11, 13, 17, 19, 21, 37, 45, 46
- Working copies of these cases live in data/cases/
- The reference BPMN must NEVER be given to any LLM. Only evaluate.py reads it.

## Pipeline
LLM outputs a JSON process structure -> deterministic Python builder converts it to BPMN XML -> validation.
No LLM writes BPMN XML directly.

## Rules for the code
- Python, simple and readable; I need to explain every part in my thesis
- Explain every file you create in simple terms
- Save every input and output of every LLM call to results/
- Temperature 0, model name and version logged
- Use a mock LLM until I add an API key; never invent fake "real" results
- API keys only in .env, never in code
- Never put everything in one file

## Configuration
- All parameters (model names, temperature, k values, file paths) live in config.yaml and are loaded in code. Never hard-code them.

## LLM provider and experiment runs
- Provider for the thesis: Google Gemini, free tier (GeminiLLM, src/llm/gemini_llm.py, official google-genai library). Key GEMINI_API_KEY in .env.
- Temperature 0. One FIXED model version (never a "-latest" alias) set in config.yaml and used for every agent and condition; the exact model version returned by the API is logged for every call.
- API errors: rate limit (429 / RESOURCE_EXHAUSTED), overload and timeouts are retried with increasing waits, up to 8 times. An optional pause between calls keeps requests under the free-tier per-minute limit.
- 3 repetitions. Finish all three conditions (C1, C2, C3) of a repetition before starting the next repetition.
- Each repetition is one run folder: results/runs/<run_id>/<condition>/<case_id>/ (run id default: gemini_rep1, gemini_rep2, gemini_rep3). C3 mediation goes into results/runs/<run_id>/C3/mediation/.
- Resuming: if a run stops (e.g. the daily free-tier limit), rerunning the same command (same condition and repetition) skips finished cases and continues with the unfinished ones, logging to a new log file part. Finished cases are never overwritten or rerun. An API that is unreachable after all retries stops the run; it is never recorded as a model result.
- AnthropicLLM (src/llm/anthropic_llm.py) is kept for possible later use; MockLLM is used for tests.

## Code structure (required by supervisor)
- Object-oriented design. Every agent is its own class in its own file under src/agents/.
- BaseAgent (src/agents/base_agent.py) holds shared logic: calling the LLM, validating JSON output with Pydantic, one retry on invalid output, and logging. Each agent inherits from BaseAgent and only defines its prompt and output schema.
- LLM access goes through an abstract LLMClient class (src/llm/base_llm.py) with MockLLM (src/llm/mock_llm.py), GeminiLLM (src/llm/gemini_llm.py) and AnthropicLLM (src/llm/anthropic_llm.py) subclasses, so agents never depend on a specific provider.
- Orchestrator (src/orchestrator.py) runs the mediation agents in order for C3.
- BPMNGenerator (src/generator.py) is the single shared generator for C1, C2 and C3.
- BPMNBuilder (src/bpmn_builder.py) converts JSON to BPMN XML without any LLM.
- Evaluator (src/evaluate.py) compares generated BPMN with reference BPMN.
- run_experiment.py is the entry point and takes --condition C1, C2 or C3 and --repetition 1, 2 or 3.

## Logging
- RunLogger class (src/logger.py) writes one JSON record per LLM call to results/logs/<condition>_<run_id>.jsonl (JSON Lines); a resumed run writes to <condition>_<run_id>_part2.jsonl, _part3, ... An existing log file is never written into again.
- Each record contains: timestamp, run_id, condition, case_id, component (class name), model, temperature, prompt, raw_output, parsed_output, valid_json, retries, duration_seconds.
- Every component that calls an LLM must log through RunLogger.

## RAG (used by C2 and C3)
- Knowledge sources: EU Consumer Rights Directive 2011/83/EU and Late Payment Directive 2011/7/EU. Raw texts in data/knowledge/raw/. Versions and download dates in data/knowledge/sources.json.
- Chunking (DirectiveChunker): keep only articles (drop recitals and annexes, keep definitions). One passage = one numbered paragraph; keep lettered points (a), (b), (c) together. Prefix each passage with directive name and article title. Passage IDs like CRD-Art9-1 and LPD-Art3-1. Output: data/knowledge/passages.jsonl with fields id, directive, article, paragraph, title, text, n_chars.
- Dense retrieval (DenseRetriever): small English embedding model with its required query/passage prefixes, normalised vectors, FAISS IndexFlatIP.
- Sparse retrieval (BM25Retriever): BM25 with k1=1.5 and b=0.75; text lowercased, punctuation removed, English stopwords removed, Porter stemming.
- Queries per case (QueryBuilder): the full description + each sentence of it separately. No LLM anywhere in retrieval.
- Fusion (HybridRetriever): Reciprocal Rank Fusion with k=60 over the top-20 from each retriever, summed across all queries of a case, deduplicated, fixed top-5 per case, no relevance threshold.
- Retrieval runs ONCE (src/freeze_retrieval.py) and is saved to data/retrieval/frozen_retrieval.json together with the config used. C2 and C3 only read this file; they never run retrieval themselves.
- All retrieval classes live in src/retrieval/, one class per file.

## Mediation (C3)
- The Orchestrator processes each frozen passage of a case separately.
- RelevanceAgent: is the passage about this process? Returns relevant (true/false), a reason, and quotes from both texts. Irrelevant passages stop here.
- ApplicabilityAgent: splits the rule into conditions and gives each one the status satisfied, contradicted or not_stated, with an exact quote from the description as evidence (or null).
- Code, not an LLM, then:
  - checks that every evidence quote really appears in the description; a quote that is not found counts as not_stated
  - combines the statuses: any contradicted -> Not applicable; all satisfied -> Applicable; otherwise -> Indeterminate
- RequirementAgent: runs ONLY for Applicable rules. Turns the rule into a concrete requirement (actor, action, condition, ordering) without adding anything that is not in the rule.
- Provenance is saved by code: passage ID and text, evidence quotes, label, requirement.
- Indeterminate rules never become definite requirements; they are passed to the generator as a separate list.
- All agent outputs are saved to results/runs/<run_id>/C3/mediation/, one file per case.

## Evaluation
- Syntactic validity: does the generated BPMN parse and validate.
- Semantic quality: activity precision and recall against the reference BPMN, using label similarity matching.
- Behavioral quality: ordering, exclusive and parallel relations between matched activities.
- Complexity of each case is measured from the reference BPMN (tasks, gateways, loops, nesting).
- Results: results/evaluation.csv, one row per case per condition per repetition (with a repetition column), plus a summary per condition with the mean and standard deviation across repetitions.
- Sanity check: comparing a reference BPMN with itself must give perfect scores.

## Current scope
- Focus now: building C1, C2 and C3 and evaluating BPMN quality automatically against the reference models.
- Applicability evaluation (RQ3) is postponed. Every agent output is still saved so it can be evaluated later.
- Known limitation: a correct legally required step added in C3 is not in the PMo reference BPMN, so it may count as an unsupported activity. Keep such activities identifiable via provenance.

## Workflow
- Work one step at a time. Do only what the current prompt asks.
- After each step, run what you built and show me the result.
- Add tests in tests/ for every component.