# Thesis project: Explicit domain-knowledge mediation for LLM-based BPMN generation

## Goal
Compare three conditions for generating BPMN from text:
- C1: process description only -> generator
- C2: description + raw retrieved rule passages (RAG) -> same generator
- C3: description + the same retrieved passages after mediation agents -> same generator

The generator must be IDENTICAL in all three conditions: BPMNGen (Ulm University) with qwen3:8b on Ollama, its own fixed system prompt, temperature 0.3, num_ctx 16384, thinking off. Only the knowledge block differs. It is always appended after the description under the same neutral label (config.yaml generator.knowledge_label, PROVISIONAL until agreed with supervisors/Ulm):
- C1: "No domain knowledge provided." (same label and layout, empty block)
- C2: the 5 frozen passages, verbatim, with their IDs
- C3: requirements produced by the mediation agents + a list of rules marked Indeterminate

Decisions (16 Oct 2026):
- The C3 mediation agents use the SAME model as the generator (qwen3:8b on Ollama), so C3 cannot win by using a stronger model.
- BPMNGen's temperature 0.3 is kept (not overridden); the 3 repetitions measure run-to-run variation. To confirm with the Ulm PhD students.
- C1 uses the same layout as C2/C3 with an empty block.

## Data
- PMo dataset in data/raw/pmo/ (descriptions/*.txt = process text, bpmn/*.bpmn = ground truth)
- Working cases (Order & Purchasing domain): 01, 03, 05, 06, 10, 11, 13, 17, 19, 21, 37, 45, 46
- Working copies of these cases live in data/cases/
- The reference BPMN must NEVER be given to any LLM. Only evaluate.py reads it.

## Pipeline
Thesis generator (generator.type: bpmngen): knowledge block -> bpmngen_harness/run_bpmngen.ts -> BPMNGen's OpenSourceLLM (one Ollama call, qwen3 writes BPMN XML directly) -> BPMNGen's deterministic XML cleanup -> generated.bpmn -> our validator.
- BPMNGen is private Ulm code. It lives OUTSIDE this repository (generator.bpmngen_server_dir). Never copy it in, never change its files, never push it anywhere.
- The harness imports BPMNGen's classes and repeats createBPMN() without database, login or title. See docs/BPMNGEN_ANALYSIS.md and bpmngen_harness/README.md.
- BPMNGen's cleanup can ADD sequence flows or a first task. These auto-repairs are counted per case and must be reported per condition.
- An answer that is cut off (done_reason not "stop" or context window full) is a failed generation with context_limit_hit = True.
Legacy generator (generator.type: json_builder, used by the mock tests): own prompt -> JSON -> src/bpmn_builder.py. Not used for thesis runs.

## Rules for the code
- Python, simple and readable; I need to explain every part in my thesis
- Explain every file you create in simple terms
- Save every input and output of every LLM call to results/
- Model name and exact Ollama model digest logged (run_info.json); temperatures: generator 0.3 (BPMNGen), mediation agents 0
- Tests always use mock answers and a fake harness (THESIS_FORCE_MOCK); never invent fake "real" results
- API keys only in .env, never in code
- Never put everything in one file

## Configuration
- All parameters (model names, temperature, k values, file paths) live in config.yaml and are loaded in code. Never hard-code them.

## LLM provider and experiment runs
- Everything runs on qwen3:8b in Ollama (on the PC with the RTX 4060): the BPMNGen generator AND the C3 mediation agents (OllamaLLM, src/llm/ollama_llm.py: /api/chat, num_ctx 16384, think false, format json, temperature 0).
- The exact Ollama model digest of the generator and the agents is stored in run_info.json; a later part of a run with a different digest is refused (a tag like qwen3:8b can change after `ollama pull`).
- Ollama not reachable / HTTP error / harness timeout: retried where sensible, then the run STOPS without recording a result (LLMUnavailableError), so the case can be resumed.
- GeminiLLM and AnthropicLLM are kept in the code but not used for the thesis.
- 3 repetitions. Finish all three conditions (C1, C2, C3) of a repetition before starting the next repetition.
- Each repetition is one run folder: results/runs/<run_id>/<condition>/<case_id>/ (run id default: ollama_rep1, ollama_rep2, ollama_rep3). C3 mediation goes into results/runs/<run_id>/C3/mediation/.
- Resuming: if a run stops (e.g. the daily free-tier limit), rerunning the same command (same condition and repetition) skips finished cases and continues with the unfinished ones, logging to a new log file part. Finished cases are never overwritten or rerun. Any API error (a temporary one after all retries, any other one such as 404 model not found at once) stops the run without writing validation.json; it is never recorded as a model result.
- MockLLM is used for tests.

## Code structure (required by supervisor)
- Object-oriented design. Every agent is its own class in its own file under src/agents/.
- BaseAgent (src/agents/base_agent.py) holds shared logic: calling the LLM, validating JSON output with Pydantic, one retry on invalid output, and logging. Each agent inherits from BaseAgent and only defines its prompt and output schema.
- LLM access goes through an abstract LLMClient class (src/llm/base_llm.py) with MockLLM, OllamaLLM (thesis), GeminiLLM and AnthropicLLM subclasses, so agents never depend on a specific provider.
- Orchestrator (src/orchestrator.py) runs the mediation agents in order for C3.
- BPMNGenGenerator (src/bpmngen_generator.py) is the single shared generator for C1, C2 and C3 (runs the harness as a separate process).
- BPMNGenerator (src/generator.py) + BPMNBuilder (src/bpmn_builder.py): legacy JSON generator, used by the mock tests only.
- Evaluator (src/evaluate.py) compares generated BPMN with reference BPMN.
- run_experiment.py is the entry point and takes --condition C1, C2 or C3 and --repetition 1, 2 or 3.

## Logging
- RunLogger class (src/logger.py) writes one JSON record per LLM call to results/logs/<condition>_<run_id>.jsonl (JSON Lines); a resumed run writes to <condition>_<run_id>_part2.jsonl, _part3, ... An existing log file is never written into again.
- Each record contains: timestamp, run_id, condition, case_id, component (class name), model, temperature, prompt, raw_output, parsed_output, valid_json, retries, duration_seconds.
- Every component that calls an LLM must log through RunLogger. BPMNGenGenerator logs one record per case with the exact messages sent to Ollama, the raw output and the harness meta data; the full files are in <case>/bpmngen/.

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
- The C3 block only DESCRIBES what mediation found (headings + one descriptive line each). It contains no instructions to the generator (no "do not add steps"), because C2 gets none either; only the knowledge may differ.
- All agent outputs are saved to results/runs/<run_id>/C3/mediation/, one file per case.

## Evaluation
- Syntactic validity: does the generated BPMN parse and validate.
- Semantic quality: activity precision and recall against the reference BPMN, using label similarity matching.
- Behavioral quality: ordering, exclusive and parallel relations between matched activities. All pools are read; message flows count as order (BPMNGen draws one pool per actor, PMo references have one process); sub-processes are opened up.
- Unsupported additions (PROVISIONAL diagnostic): number of extra generated tasks, and how many look like they came from the knowledge block (evaluation.trace_threshold, not calibrated yet).
- Generator diagnostics per condition: cases that hit the context limit, token counts, BPMNGen auto-repairs.
- Complexity of each case is measured from the reference BPMN (tasks, gateways, loops, nesting).
- Results: results/evaluation.csv, one row per case per condition per repetition (with a repetition column), plus a summary per condition with the mean and standard deviation across repetitions.
- Sanity check: comparing a reference BPMN with itself must give perfect scores.

## Current scope
- Focus now: building C1, C2 and C3 and evaluating BPMN quality automatically against the reference models.
- Applicability evaluation (RQ3) is postponed. Every agent output is still saved so it can be evaluated later.
- Known limitation: a correct legally required step added in C2/C3 is not in the PMo reference BPMN, so it counts as an extra task and lowers precision. Such tasks are listed in evaluation.json (extra_task_diagnostics) and must be read by hand before conclusions are drawn. With the PMo references, the realistic expectation for C3 is "avoids the extra tasks raw RAG adds" (C3 ≈ C1 > C2 on precision), not "beats C1".
- Known limitation: 13 cases × 3 repetitions is pilot-sized. Report paired per-case comparisons; RQ2 (complexity) is exploratory only.

## Workflow
- Work one step at a time. Do only what the current prompt asks.
- After each step, run what you built and show me the result.
- Add tests in tests/ for every component.