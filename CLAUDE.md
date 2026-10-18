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
- Everything runs on qwen3:8b in Ollama (on the PC with the RTX 4060, http://localhost:11434, no API key): the BPMNGen generator AND the C3 mediation agents.
- Mediation agents (OllamaLLM, src/llm/ollama_llm.py), all settings in config.yaml and sent with every request: temperature 0, seed 42, num_ctx 16384, thinking off (think: false), max_tokens 8192 (num_predict).
- The exact model file is fixed by its digest: qwen3:8b = 500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41 (llm.ollama_model_digest; pulled 18 Oct 2026, read with installed_ollama_digest). The agents check it before their first call; the generator's model is checked against the same digest when a run starts (run_experiment.ollama_settings) and stored in run_info.json. If anything differs, the run stops.
- Logged for every call: model name, model digest and finish_reason (STOP, or MAX_TOKENS when an answer was cut off).
- Errors: Ollama not reachable, timeouts and server errors are retried with increasing waits (2, 4, 8, 16, 32 s), up to 5 times; other errors (e.g. 404 model not downloaded) are not retried. Every such error stops the run without recording a result (LLMUnavailableError), so the case can be resumed.
- Prompt length: for the BPMNGen generator, prompt and answer tokens are measured on every call (meta.json) and a cut-off answer is flagged (context_limit_hit). src/count_prompt_tokens.py counts the prompt of the LEGACY json_builder generator only.
- GeminiLLM (src/llm/gemini_llm.py, model gemini-3.5-flash, key GEMINI_API_KEY in .env, at least 10 s between calls) and AnthropicLLM are kept for possible later use (e.g. a second-model robustness check); MockLLM is used for tests.
- 3 repetitions. Finish all three conditions (C1, C2, C3) of a repetition before starting the next repetition.
- Each repetition is one run folder: results/runs/<run_id>/<condition>/<case_id>/ (run id default: ollama_rep1, ollama_rep2, ollama_rep3). C3 mediation goes into results/runs/<run_id>/C3/mediation/.
- Resuming: if a run stops (e.g. the daily free-tier limit), rerunning the same command (same condition and repetition) skips finished cases and continues with the unfinished ones, logging to a new log file part. Finished cases are never overwritten or rerun. Any API error (a temporary one after all retries, any other one such as 404 model not found at once) stops the run without writing validation.json; it is never recorded as a model result.

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
- Each record contains: timestamp, run_id, condition, case_id, component (class name), model, model_digest, finish_reason, temperature, prompt, raw_output, parsed_output, valid_json, retries, duration_seconds.
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

## Silver legal reference (evaluation only)
- Problem it solves: the PMo reference models contain no legal steps, so a correct legal step would count as an error.
- src/build_silver_reference.py runs ONCE before the experiment runs and freezes data/silver/silver_reference.json: for every case and each of its 5 frozen passages, SilverAnnotator (src/agents/silver_annotator.py, prompts/silver_annotation_prompt.txt) labels the passage applicable / not_applicable / indeterminate / irrelevant and lists the process steps an applicable rule requires.
- Independence from C3: a different and stronger model (Gemini, config.yaml silver section, not qwen3), a different prompt, one call per passage, and it never sees generated models or C3 outputs. The file stores the annotator model version, prompt checksum and frozen-retrieval checksum.
- The labels are AI-made: SILVER, provisional, never gold. Decision 16 Oct 2026: no human audit; this is a stated limitation.
- Used by: the evaluator (precision_adjusted, requirement_coverage, justified extra tasks, unjustified knowledge additions) and src/rq3_agreement.py (agreement of C3's labels with silver: accuracy, Cohen's kappa, confusion matrix; reported as agreement with a stronger model, not as correctness).

## Evaluation
- Syntactic validity: does the generated BPMN parse and validate.
- Validity rule (decided 18 Oct 2026, before the real runs, same for C1, C2, C3):
  - "valid" (main metric) = our strict validator (src/validator.py), unchanged.
  - "bpmnlint_valid" = BPMNGen's own bpmnlint verdict, reported next to it (it is more lenient: it accepted a file with an undeclared bpmndi namespace).
  - Rescue for the structural metrics only (src/di_rescue.py): if a file is not valid and removing its <bpmndi:BPMNDiagram> section makes it pass the whole validator, the metrics are computed on that copy and "di_stripped" = True; "valid" stays False. The diagram section only holds drawing positions. Nothing else is ever repaired (e.g. a "b3pmn:" typo is not rescued and scores 0). The generated file is never changed; the copy lives in a temporary folder.
  - Smoke test 18 Oct 2026 (case 01): both XML errors were already in qwen3's raw answer, not caused by BPMNGen's cleanup.
- Semantic quality: activity precision and recall against the reference BPMN, using label similarity matching.
- Behavioral quality: ordering, exclusive and parallel relations between matched activities. All pools are read; message flows count as order (BPMNGen draws one pool per actor, PMo references have one process); sub-processes are opened up.
- Legal steps (silver reference): precision_adjusted (extra tasks that realise a required legal step are NOT errors; plain precision is kept too), requirement_coverage, n_extra_justified, n_unjustified_knowledge_additions.
- Unsupported additions (PROVISIONAL diagnostic): number of extra generated tasks, and how many look like they came from the knowledge block (evaluation.trace_threshold, not calibrated yet).
- Generator diagnostics per condition: cases that hit the context limit, token counts, BPMNGen auto-repairs.
- Complexity of each case is measured from the reference BPMN (tasks, gateways, loops, nesting).
- Results: results/evaluation.csv, one row per case per condition per repetition (with a repetition column), plus a summary per condition with the mean and standard deviation across repetitions.
- Sanity check: comparing a reference BPMN with itself must give perfect scores.

## Current scope
- Focus now: building C1, C2 and C3 and evaluating BPMN quality automatically against the reference models.
- Applicability evaluation (RQ3): automated against the silver reference (src/rq3_agreement.py); agreement, not correctness, because silver is not human-checked.
- Known limitation (partly solved): a correct legal step is not in the PMo reference BPMN. precision_adjusted and requirement_coverage use the silver reference so such steps are no longer errors, but silver is AI-made and unverified; report plain precision as well.
- Known limitation: 13 cases × 3 repetitions is pilot-sized. Report paired per-case comparisons; RQ2 (complexity) is exploratory only.

## Workflow
- Work one step at a time. Do only what the current prompt asks.
- After each step, run what you built and show me the result.
- Add tests in tests/ for every component.