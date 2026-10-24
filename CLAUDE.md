# Thesis project: Explicit domain-knowledge mediation for LLM-based BPMN generation

## Goal
Compare three conditions for generating BPMN from text:
- C1: process description only -> generator
- C2: description + raw retrieved rule passages (RAG) -> same generator
- C3: description + the same retrieved passages after mediation agents -> same generator

The generator must be IDENTICAL in all three conditions: BPMNGen (Ulm University) with qwen3:8b on Ollama, its own fixed system prompt, temperature 0.3, num_ctx 16384, thinking off (BPMNGen's "/no_think" plus Ollama's think:false, added by the harness; see Pipeline). Only the knowledge block differs. It is always appended after the description under the same neutral label (config.yaml generator.knowledge_label, PROVISIONAL until agreed with supervisors/Ulm):
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
- BPMNGen file hashes (decided 19 Oct 2026, after the runs; audit finding 1): when a run starts, src/bpmngen_files.py hashes (SHA-256, read only) the BPMNGen files in config.yaml generator.bpmngen_hashed_files plus every other BPMNGen file the harness loads (run_bpmngen.ts --list-files, no Ollama call), and stores them in run_info.json as bpmngen_file_hashes. A run stops if they differ from an earlier part of the same run or from another run of the study (statistics.runs). The finished runs ollama_rep1-3 have no stored hashes; docs/BPMNGEN_VERSION_CHECK.md verifies after the fact that all 16 loaded files equal the original BPMNGen download.
- BPMNGen's cleanup can ADD sequence flows. These auto-repairs are counted per case and must be reported per condition. The first-task repair cannot run in this code path: generateContent passes input.prompt to the cleanup, but the object from mapPromptInput has no prompt field (opensource.ts lines 83, 313-318, 460). Confirmed: first_task_inserted is false in 117/117 generations.
- Thinking (decided 18 Oct 2026): BPMNGen asks for no thinking only with "/no_think" in the prompt; Ollama 0.40.6 let qwen3 think anyway, in a separate "thinking" field BPMNGen never reads (hidden, unsaved; one case looped to 122,236 tokens). The harness therefore adds Ollama's think:false to BPMNGen's request (config.yaml model.think, stored in run_info.json). This is the ONLY change to BPMNGen's request; no BPMNGen file is changed.
- The thinking field is always saved (bpmngen/raw_thinking.txt and the log). raw_has_think_block is true if there is thinking text in that field OR a <think>/</think> tag in the answer (qwen3 can still write a draft followed by "</think>"); then validation.json gets thinking_detected = True and a warning. It is flagged, never repaired.
- Failed generations (model results: scored as 0, never retried, validation.json written):
  - cut off: the harness aborts the stream when the output passes num_ctx tokens (done_reason "cut_off_by_harness"), or Ollama reports a length stop / the window was full -> context_limit_hit = True
  - timeout (generator.timeout_seconds, 900 s): the whole process tree (npx and its node child) is killed -> timed_out = True
- Stray </think> (decided 18 Oct 2026, before the real runs): even with think:false, qwen3 sometimes breaks off mid-XML, writes "</think>" and continues (2 of 6 smoke generations). This is treated as a genuine model failure: no repair, no retry, no change to how BPMNGen is called. The file stays invalid (score 0), thinking_detected is flagged, and it is counted per condition.
- Failure types (src/evaluate.py failure_type, counted per condition in the summaries as n_fail_<type>; each case counts once, under the first that applies): timed_out, context_limit_hit, thinking_detected, missing_namespace_rescued (di_stripped), invalid_xml_other.
- Only real Ollama unavailability (connection refused, HTTP errors) stops the run without a result (LLMUnavailableError), so the case can be resumed.
- Discarded run: the first, partial repetition 1 (C1, 9 cases, made with hidden thinking) was moved to results/_discarded/ollama_rep1_thinking_on/ (kept, never evaluated); repetition 1 restarts from scratch.
Legacy generator (generator.type: json_builder, used by the mock tests): own prompt -> JSON -> src/bpmn_builder.py. Not used for thesis runs.

## Rules for the code
- Python, simple and readable; I need to explain every part in my thesis
- Explain every file you create in simple terms
- Save every input and output of every LLM call to results/
- Model name and exact Ollama model digest logged (run_info.json); temperatures: generator 0.3 (BPMNGen), mediation agents 0
- Tests always use mock answers and a fake harness (THESIS_FORCE_MOCK); never invent fake "real" results
- Tests never write into the real results/: tests/conftest.py sets THESIS_RESULTS_DIR to a temporary folder (every "results/..." path in config.yaml is moved there), and tests/test_zz_results_untouched.py plus the session end prove results/ is byte-identical before and after the suite (fix B2, 19 Oct 2026)
- API keys only in .env, never in code
- Never put everything in one file

## Configuration
- All parameters (model names, temperature, k values, file paths) live in config.yaml and are loaded in code. Never hard-code them.
- Layout (fix B7+C1, 19 Oct 2026): ONE `model` block (provider, name, digest, Ollama URL and server settings, num_ctx, think, BPMNGen class) read by BOTH the generator and the C3 agents; `llm` = settings only the agents send (temperature 0, seed, max_tokens, retries); `generator` = BPMNGen settings, with `expected` = BPMNGen's own fixed request values (temperature 0.3, system-prompt SHA-256). Every BPMNGen request is checked against model + expected; a difference stops the run (GeneratorSetupError, never a model result).
- Prompt texts that used to be in code are files in prompts/: c1_no_knowledge.txt, c3_block_template.json, json_retry_note.json. tests/test_study1_prompts.py proves the config reproduces all 117 stored Study 1 generator prompts and all 249 logged agent prompts byte for byte.

## LLM provider and experiment runs
- Everything runs on qwen3:8b in Ollama (on the PC with the RTX 4060, http://localhost:11434, no API key): the BPMNGen generator AND the C3 mediation agents.
- Ollama server settings (decided 18 Oct 2026, before the real runs): Windows user environment variables OLLAMA_FLASH_ATTENTION=1 and OLLAMA_KV_CACHE_TYPE=q8_0 (config.yaml model.ollama_server_env; restart Ollama after a change). With them qwen3:8b at num_ctx 16384 runs 100% on the GPU (6.3 GB); without them 20% ran on the CPU. Speed test (smoke_speed, case 01, C1): about 42 tokens/s (7372 tokens in 176 s) vs about 11 tokens/s before (4294 tokens in 401 s). num_ctx stays 16384 for the generator (BPMNGen's own fixed value, not changed) and the agents, so Ollama never reloads the model between them.
- run_info.json stores, for every run: the generator's model digest, the Ollama version (0.40.6 on 18 Oct 2026; Ollama updates itself, so a later part with another version is refused) and the Ollama server settings. A run does not start if the server settings differ from config.yaml. Since 19 Oct 2026 (fix B8) it also stores bpmngen_library_versions: Node and npm versions, every direct BPMNGen dependency, and every installed version of generator.bpmngen_key_libraries (bpmnlint, bpmn-moddle), read only with npm ls (src/bpmngen_libraries.py); a later part with other versions is refused.
- Mediation agents (OllamaLLM, src/llm/ollama_llm.py), all settings in config.yaml and sent with every request: temperature 0, seed 42, num_ctx 16384, thinking off (think: false), max_tokens 8192 (num_predict).
- The exact model file is fixed by its digest: qwen3:8b = 500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41 (model.ollama_model_digest; pulled 18 Oct 2026, read with installed_ollama_digest). The agents check it before their first call; the generator's model is checked against the same digest when a run starts (run_experiment.ollama_settings) and stored in run_info.json. If anything differs, the run stops.
- Logged for every call: model name, model digest and finish_reason (STOP, or MAX_TOKENS when an answer was cut off).
- Errors: Ollama not reachable, timeouts and server errors are retried with increasing waits (2, 4, 8, 16, 32 s), up to 5 times; other errors (e.g. 404 model not downloaded) are not retried. Every such error stops the run without recording a result (LLMUnavailableError), so the case can be resumed.
- Prompt length: for the BPMNGen generator, prompt and answer tokens are measured on every call (meta.json) and a cut-off answer is flagged (context_limit_hit). src/count_prompt_tokens.py counts the prompt of the LEGACY json_builder generator only.
- GroqLLM (src/llm/groq_llm.py) is used only by the silver annotator (see Silver legal reference). GeminiLLM (src/llm/gemini_llm.py, key GEMINI_API_KEY in .env, at least 10 s between calls) and AnthropicLLM are kept for possible later use (e.g. a second-model robustness check); MockLLM is used for tests.
- 3 repetitions. Finish all three conditions (C1, C2, C3) of a repetition before starting the next repetition.
- Each repetition is one run folder: results/runs/<run_id>/<condition>/<case_id>/ (run id default: ollama_rep1, ollama_rep2, ollama_rep3; decided 18 Oct 2026: the real runs use these default ids, because then the code refuses to start repetition n before every condition of n-1 is complete). C3 mediation goes into results/runs/<run_id>/C3/mediation/.
- Resuming: if a run stops (e.g. the daily free-tier limit), rerunning the same command (same condition and repetition) skips finished cases and continues with the unfinished ones, logging to a new log file part. Finished cases are never overwritten or rerun. Any API error (a temporary one after all retries, any other one such as 404 model not found at once) stops the run without writing validation.json; it is never recorded as a model result.

## Code structure (required by supervisor)
- Object-oriented design. Every agent is its own class in its own file under src/agents/.
- BaseAgent (src/agents/base_agent.py) holds shared logic: calling the LLM, validating JSON output with Pydantic, one retry on invalid output, and logging. Each agent inherits from BaseAgent and only defines its prompt and output schema.
- LLM access goes through an abstract LLMClient class (src/llm/base_llm.py) with MockLLM, OllamaLLM (thesis), GroqLLM (silver annotator only), GeminiLLM and AnthropicLLM subclasses, so agents never depend on a specific provider.
- Orchestrator (src/orchestrator.py) runs the mediation agents in order for C3.
- BPMNGenGenerator (src/bpmngen_generator.py) is the single shared generator for C1, C2 and C3 (runs the harness as a separate process).
- BPMNGenerator (src/generator.py) + BPMNBuilder (src/bpmn_builder.py): legacy JSON generator, used by the mock tests only.
- Evaluator (src/evaluate.py) compares generated BPMN with reference BPMN.
- run_experiment.py is the entry point and takes --condition C1, C2 or C3 and --repetition 1, 2 or 3.

- Preflight (fix E1, 19 Oct 2026): `python -m src.preflight` must pass before any generation (one PASS/FAIL line per check: plan committed, frozen-retrieval checksums = plan section 9, C3 = frozen version, model digest, BPMNGen hashes = docs/bpmngen_hashes_2026-10-19.json, sample development cases: C1/C2/C3 requests from BPMNGen's own dry run differ only in the knowledge block and stay < 80% of num_ctx). The C3 agents run only on development cases (cases.development_ids: all 13 Study 1 cases); test cases (cases.test_ids) get C1/C2 checks only. Output in results/preflight/<timestamp>/.

## Logging
- RunLogger class (src/logger.py) writes one JSON record per LLM call to results/logs/<condition>_<run_id>.jsonl (JSON Lines); a resumed run writes to <condition>_<run_id>_part2.jsonl, _part3, ... An existing log file is never written into again.
- Each record contains: timestamp, run_id, condition, case_id, component (class name), model, model_digest, finish_reason, reasoning (reasoning models only), temperature, prompt, raw_output, parsed_output, valid_json, retries, duration_seconds.
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
- The silver reference must be complete and committed before the evaluation (python -m src.evaluate) — it does not need to exist before the generation runs, because it only uses the descriptions and law passages, never generated models.
- src/build_silver_reference.py builds and freezes data/silver/silver_reference.json once (cases already in the file are never re-annotated): for every case and each of its 5 frozen passages, SilverAnnotator (src/agents/silver_annotator.py, prompts/silver_annotation_prompt.txt) labels the passage applicable / not_applicable / indeterminate / irrelevant and lists the process steps an applicable rule requires.
- Independence from C3: a different and stronger model (config.yaml silver section, not qwen3), a different prompt, one call per passage, and it never sees generated models or C3 outputs. The file stores the annotator provider and model, the annotation dates, the prompt checksum and the frozen-retrieval checksum.
- Annotator model: openai/gpt-oss-120b on Groq's free API (GroqLLM, src/llm/groq_llm.py, OpenAI-compatible; key GROQ_API_KEY in .env, never committed), temperature 0, max_tokens 5000, used ONLY for the silver builder. A guard stops the build without saving the case if any answer reports another model name, or if the saved file was made by another model. Every case records annotated_at and Groq's system_fingerprint(s); the model's reasoning text is saved in the log.
- Groq free limits (19 Oct 2026): 1000 requests/day, 8000 tokens/minute. Groq counts prompt + max_tokens against the per-minute limit, hence max_tokens 5000 (largest silver prompt ~2000 tokens). A 429 rate limit is waited out as Groq asks and is NOT a failure; a requested wait above 15 min (daily limit) stops the build, which resumes from the finished cases.
- Change of annotator (decided 19 Oct 2026, before any evaluation): gemini-3.6-flash -> openai/gpt-oss-120b via Groq, because the Gemini free tier allows only 20 requests/day and paid billing was not possible. The 3 Gemini cases (01, 03, 05) are kept in data/silver/_discarded/gemini_partial/ (with a README) and never used; all 13 cases were rebuilt with gpt-oss-120b, so the file has one annotator.
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
- Unsupported additions: number of extra generated tasks, and how many look like they came from the knowledge block (knowledge-traceable). evaluation.trace_threshold is FIXED at 0.5, decided 18 Oct 2026 before the real runs; a sensitivity check at 0.4 / 0.5 / 0.6 (evaluation.trace_sensitivity_thresholds) runs with python -m src.evaluate --sweep and is reported next to the main result.
- Generator diagnostics per condition: cases that hit the context limit, token counts, BPMNGen auto-repairs.
- Complexity of each case is measured from the reference BPMN (tasks, gateways, loops, nesting).
- Results: results/evaluation.csv, one row per case per condition per repetition (with a repetition column), plus a summary per condition with the mean and standard deviation across repetitions.
- Sanity check: comparing a reference BPMN with itself must give perfect scores.
- Stage gates (fix E2, 19 Oct 2026; src/stage_gates.py, `python -m src.stage_gates` shows them): python -m src.evaluate refuses to start unless the silver reference has labels and expected requirements for every case, matches the frozen retrieval and is committed without changes, and every run in statistics.runs is complete; python -m src.statistics refuses unless evaluation.csv holds exactly those runs with every condition x case.
- Only the study's runs are analysed: src/evaluate.py, src/statistics.py and src/rq3_agreement.py use exactly the run ids in config.yaml statistics.runs (ollama_rep1-3); smoke runs and any other folder in results/runs/ are ignored, and other ids are refused (fix B2, 19 Oct 2026).
- Statistics (src/statistics.py, config.yaml statistics section) follow docs/ANALYSIS_PLAN.md exactly: repetitions averaged per case and condition; Friedman; Wilcoxon C3 vs C1 and C3 vs C2 on F1 and behavioural similarity with Holm over these 4; median paired difference with bootstrap 95% CI (seed 42) and rank-biserial; over-application (n_unjustified_knowledge_additions, C3 vs C2); Spearman with reference complexity (ref_flow_nodes, ref_cfc) for RQ2; the same tests on valid/rescued generations only; failure types per condition. Tables in results/statistics/. Tested on synthetic data only.

## Current scope
- Focus now: building C1, C2 and C3 and evaluating BPMN quality automatically against the reference models.
- Applicability evaluation (RQ3): automated against the silver reference (src/rq3_agreement.py); agreement, not correctness, because silver is not human-checked.
- Known limitation (partly solved): a correct legal step is not in the PMo reference BPMN. precision_adjusted and requirement_coverage use the silver reference so such steps are no longer errors, but silver is AI-made and unverified; report plain precision as well.
- Known limitation: 13 cases × 3 repetitions is pilot-sized. Report paired per-case comparisons; RQ2 (complexity) is exploratory only.

## Workflow
- Work one step at a time. Do only what the current prompt asks.
- After each step, run what you built and show me the result.
- Add tests in tests/ for every component.

## Study 2 (GDPR, branch study2-bpmngen-server)
- GDPR corpus restricted to Chapters I-V (Art 1-50; config.yaml study2_gdpr.included_chapters, data/knowledge_gdpr/passages_ch1-5.jsonl, own dense index data/retrieval_gdpr/dense_index_ch1-5). Reason: Chapters VI–XI address supervisory authorities, remedies, specific national situations and final provisions, not an organisation's process; decided 24 Oct 2026 on development cases, applies to C2 and C3 equally. The full data/knowledge_gdpr/passages.jsonl (all 99 articles) is kept.
- Reranker (src/retrieval/cross_encoder_reranker.py, config.yaml reranker, off by default): scores each hybrid candidate against the description's sentence queries only and uses the mean score (changed 24 Oct 2026 from max over all queries, where the full description always gave the maximum). The first comparison (all 99 articles, max) is kept in data/retrieval_gdpr/frozen_retrieval_dev_{hybrid,rerank}.json, superseded and never used.
- Choice between the hybrid and rerank versions: rule fixed in docs/C3_V2_DEVELOPMENT.md section 4 before any GDPR silver labelling (more silver-applicable passages in the top 5 wins; then fewer irrelevant; then hybrid).
