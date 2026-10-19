# Fix log

Fixes from the audit (`docs/AUDIT_2026-10-19.md`), one at a time. Each entry: what changed, files, tests, risk.

**Invariant check used for every fix:** a script recomputes every Study 1 output (evaluation.csv, both summaries,
the 9 sensitivity CSVs, the 7 statistics tables, rq3_agreement.csv, rq3_confusion.json) for ollama_rep1-3 into a
scratch folder and compares them byte-for-byte with the stored files in results/. It never writes into results/
(per-case details off, every output path redirected).
Baseline before fix 1: all 21 outputs identical, so the current code reproduces the stored Study 1 numbers exactly.

---

## Before fix 1: BPMNGen file hashes (audit finding 1, MAJOR), 19 Oct 2026
- **What changed:** each run now stores SHA-256 hashes of every BPMNGen file the harness loads in run_info.json
  (`bpmngen_file_hashes`). A run stops if they differ from an earlier part of the same run or from another run of
  the study. The harness gained a `--list-files` mode (no Ollama call); generation mode is unchanged.
  One-time check: all 16 loaded files equal the original BPMNGen download (`docs/BPMNGEN_VERSION_CHECK.md`).
- **Files:** `src/bpmngen_files.py` (new), `bpmngen_harness/run_bpmngen.ts`, `run_experiment.py`, `config.yaml`,
  `CLAUDE.md`, `bpmngen_harness/README.md`, `docs/BPMNGEN_VERSION_CHECK.md` (new), `docs/AUDIT_2026-10-19.md` (new).
- **Tests:** `tests/test_bpmngen_files.py` (14 new). Suite: 382 passed.
- **Risk:** the finished runs ollama_rep1-3 have no hashes from run time (post-hoc check only). Old unfinished
  smoke runs can no longer be resumed (their run_info lacks the new key). BPMNGen's node_modules are not hashed.

## Fix 1 (B2): tests never write into results/; analysis uses only statistics.runs, 19 Oct 2026
- **What changed:**
  - `THESIS_RESULTS_DIR`: when set, every config.yaml path starting with `results/` is moved into that folder.
    `tests/conftest.py` sets it to a new temporary folder (deleted at the end), so in-process tests and the
    run_experiment.py processes they start write there. Before, two CLI tests wrote into the real results/runs
    and results/logs and relied on cleanup.
  - A fingerprint (SHA-256 of every file) of the real results/ is taken before any test runs.
    `tests/test_zz_results_untouched.py` checks it, and the session end checks it again and fails the run if
    anything was added, removed or changed.
  - `src/evaluate.py` evaluates only the run ids in `statistics.runs` and refuses others (`--runs` limited to
    them). Before, it evaluated every folder in results/runs/ and only excluded the `smoke` prefix, so a leftover
    test run could have entered the summaries. `src/rq3_agreement.py` uses the same list (before: everything
    except `smoke*`). `src/statistics.py` already did this.
- **Files:** `src/config.py`, `src/evaluate.py`, `src/rq3_agreement.py`, `tests/conftest.py`,
  `tests/results_guard.py` (new), `tests/test_zz_results_untouched.py` (new), `tests/test_evaluate.py`,
  `tests/test_silver_reference.py`, `CLAUDE.md`.
- **Tests:** 3 new (results untouched, config redirect, fingerprint logic). Replaced 2 smoke-run tests with
  "only study runs are evaluated" and "other run ids are refused". The validity-rule test now uses a study run id.
  Suite: 385 passed. External check: all 1572 files in results/ byte-identical before and after the suite.
- **Invariant:** all 21 Study 1 outputs byte-identical (evaluation.csv already held only ollama_rep1-3).
- **Fairness:** no change to the generator, prompts, knowledge block, retrieval or mediation.
- **Risk:** smoke runs can no longer be evaluated with src.evaluate (intended). The `smoke_test` column stays in
  evaluation.csv for compatibility and is now always False. The redirect applies only when THESIS_RESULTS_DIR is
  set; normal runs are unaffected.

## Fix 2 (B3+B4): stale documentation, 19 Oct 2026
- **What changed:**
  - "No real qwen3 output yet" replaced with what exists now (smoke runs and Study 1, 117 generations, 18 Oct 2026)
    in `bpmngen_harness/README.md` and `docs/BPMNGEN_ANALYSIS.md` (the latter keeps its 16 Oct date, so it is
    clear the analysis was written before real output).
  - Old Gemini mentions: `config.yaml` (provider comment no longer says "gemini-3.5-flash"; env_file comment now
    names GROQ_API_KEY), `requirements.txt` (no longer says Gemini is "used for the thesis"), the run-id example
    in the docstrings of `run_experiment.py` and `src/run_folder.py` ("gemini_rep1" -> "ollama_rep1").
    Historical mentions that are still true were kept (e.g. the annotator-change notes, GeminiLLM itself).
  - `CLAUDE.md`: "cleanup can ADD sequence flows or a first task" replaced with the wording you supplied: the
    first-task repair cannot run in this code path (opensource.ts lines 83, 313-318, 460), and
    first_task_inserted is false in 117/117 generations.
- **Files:** `bpmngen_harness/README.md`, `docs/BPMNGEN_ANALYSIS.md`, `config.yaml`, `requirements.txt`,
  `run_experiment.py`, `src/run_folder.py`, `CLAUDE.md`.
- **Tests:** no code behaviour changed. config.yaml loads to exactly the same values as before, and the
  requirement pins are unchanged. Suite: 385 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** comments and docs only.
- **Risk / not verified:** the code-path reason for the first-task repair (opensource.ts line numbers) is your
  finding. I did not check it, because opening BPMNGen code is not allowed. The 117/117 count was checked
  (evaluation.csv). Still stale, outside this fix: `docs/BPMNGEN_ANALYSIS.md:43` still says repairCollapsedFirstAction
  "inserts a first task" and `:36` refers to old CLAUDE.md text; README folder name `Thesis-BPMN`;
  `src/agents/silver_annotator.py:12` ("no shared code path"); `config.yaml` similarity_threshold comment
  "(to be calibrated)"; `docs/REPORT_CHANGES.md:47`.

## Fix 2b: remaining stale items, 19 Oct 2026
- **What changed:**
  - `docs/BPMNGEN_ANALYSIS.md`: the 16 Oct text is kept. Two dated notes were added:
    - after `repairCollapsedFirstAction` (old :43): your first-task correction, as you wrote it.
    - after old :36: a note that fits that line (it is about temperature and XML, not the first task, your choice):
      CLAUDE.md has since been updated; Chapter 3 still needs the same update.
  - `bpmngen_harness/README.md`: folder name `Thesis-BPMN` -> `Thesis` (4 places).
  - `config.yaml` similarity_threshold comment "(to be calibrated)" -> "Fixed before evaluation, not calibrated;
    sensitivity sweep reported". `docs/REPORT_CHANGES.md:47` trace threshold "not calibrated yet" -> "threshold 0.5
    fixed before evaluation, not calibrated; sensitivity sweep reported". No value changed.
  - `src/agents/silver_annotator.py:12` ("no shared code path"): NOT changed, as asked; explained in the reply.
- **Files:** `docs/BPMNGEN_ANALYSIS.md`, `bpmngen_harness/README.md`, `config.yaml`, `docs/REPORT_CHANGES.md`.
- **Tests:** config.yaml loads to identical values. Suite: 385 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** docs and comments only.
- **Risk / not verified:** the :43 note says "verified against the hash-matched BPMNGen download". That verification
  is yours; I could not check the BPMNGen code path. My checks are the hash match (docs/BPMNGEN_VERSION_CHECK.md)
  and the 117/117 count.

## Fix 2c: silver annotator independence sentence, 19 Oct 2026
- **What changed:** `src/agents/silver_annotator.py` docstring, second "Independence from C3" bullet: "no shared
  code path with the mediation agents" (never literally true: SilverAnnotator has inherited BaseAgent since
  1840ea4) replaced with the rewrite you approved: different model and prompt; labels decided by the annotator
  itself (no C3 agents, resolver or orchestrator); never sees generated models or C3 output; shares only the
  generic agent machinery (LLM call, JSON check, one retry, logging) and the quote checker, which only records
  results.
- **Files:** `src/agents/silver_annotator.py` (module docstring only).
- **Tests:** the code without the module docstring is identical (AST comparison). Suite: 385 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** comment only. The silver prompt file and its stored SHA-256 are untouched.
- **Risk:** none. Two details of the old bullet are gone with the exact wording (the prompt file name, "one call
  per passage"). They are still stated in `src/build_silver_reference.py` and `config.yaml`.

## Fix 3 (B5+B6): generator log records carry the model digest; README command turns thinking off, 19 Oct 2026
- **What changed:**
  - Before, every BPMNGenGenerator log record had `model_digest: null` (the agents' records had it), against
    CLAUDE.md "Logged for every call: model name, model digest". Now `BPMNGenGenerator` takes `model_digest` and
    writes it into every record, including timeouts. The value is the generator digest that
    `run_experiment.ollama_settings()` already reads from Ollama at run start, checks against
    `llm.ollama_model_digest` and stores in run_info.json as `generator_digest`. It reaches the generator through
    `ExperimentRunner(..., generator_digest=...)`. This is the same pattern as the agents (digest checked once,
    logged with every call). No extra Ollama call.
  - `bpmngen_harness/README.md`: the manual smoke command now includes `--think false`, plus a sentence on why.
    Without it the harness sends BPMNGen's request unchanged and Ollama lets qwen3 think.
- **Files:** `src/bpmngen_generator.py`, `run_experiment.py`, `bpmngen_harness/README.md`,
  `tests/test_bpmngen_generator.py`.
- **Tests:** 3 new (digest in the normal and the timeout record; ExperimentRunner passes the digest; every
  manual `npx ts-node ... run_bpmngen.ts` command in the README has `--think false`). Suite: 388 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** the harness command and the Ollama request are unchanged (`command()` untouched); only the log
  record gains the digest.
- **Risk:** existing Study 1 logs keep `model_digest: null` for the generator (never rewritten). The digest is in
  their run_info.json. The generator's `finish_reason` is still Ollama's lowercase `"stop"`, while the agents log
  `"STOP"` (CLAUDE.md says STOP/MAX_TOKENS). Not changed here, because it was not in this fix; say if you want it
  aligned.

## Fix 4 (B8): BPMNGen library versions in run_info.json, 19 Oct 2026
- **What changed:** when a BPMNGen run starts, `src/bpmngen_libraries.py` (new) runs `node --version`,
  `npm --version`, `npm ls --depth=0 --json` and `npm ls <key libraries> --all --json` in the BPMNGen server
  folder. All of these are read only: npm ls lists what is installed and changes nothing, and no BPMNGen file is
  opened. The result goes into run_info.json as `bpmngen_library_versions`: node, npm, `top_level` (every direct
  dependency with its version), `key_libraries` (every installed version, at any depth, of
  `generator.bpmngen_key_libraries` = [bpmnlint, bpmn-moddle], your examples) and `problems` (what npm ls
  reports as wrong; recorded, not fatal). It is a run setting, so RunFolder refuses a later part of the same
  run with other versions.
- **This PC (19 Oct 2026):** Node v24.20.0, npm 11.19.0, 70 direct dependencies, bpmnlint 11.7.2, bpmn-moddle
  9.0.4 and 10.0.0 (10.0.0 nested under bpmn-auto-layout), no npm problems. BPMNGen's package-lock.json is still
  dated 15 Oct.
- **Files:** `src/bpmngen_libraries.py` (new), `run_experiment.py` (`bpmngen_library_settings`), `config.yaml`
  (`bpmngen_key_libraries`, `npm_command`), `CLAUDE.md`, `tests/test_bpmngen_libraries.py` (new).
- **Tests:** 7 new (versions read correctly and only with read-only commands in BPMNGen's folder; every depth;
  npm problems recorded; unusable npm output stops; stored in run_info; later part with other versions refused;
  nothing for the legacy generator). Suite: 395 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** the generator request, harness command and prompts are unchanged; only run_info gains a key.
- **Risk:** the finished runs ollama_rep1-3 have no recorded versions (the values above are from 19 Oct, after
  the runs). Versions are compared only within one run, not across the study's runs (as with the hashes, this
  could be added). npm ls adds a few seconds at run start. Old unfinished run folders cannot be resumed (new
  settings key).

## Fix 5 (B7+C1): hard-coded values into config.yaml; one model block, 19 Oct 2026
- **Your decisions:** shared model block plus checks; prompt texts as files in prompts/.
- **What changed:**
  - **One `model` block** (provider, name, digest, Ollama URL, server env, num_ctx, think, BPMNGen module/class,
    info timeout), read by BOTH BPMNGenGenerator and the agents (OllamaLLM; also Gemini/Anthropic). `llm` keeps
    only what the agents send (temperature 0, seed, max_tokens, timeouts, retries). Removed duplicates:
    `generator.model`, `generator.ollama_base_url`, `generator.think_param`, `llm.model/provider/num_ctx/think/...`.
  - **`generator.expected`** = BPMNGen's own fixed values (temperature 0.3; SHA-256 of its system prompt, identical
    in all 117 Study 1 requests). After every BPMNGen call, `check_request()` compares model, temperature,
    num_ctx, think and system-prompt hash with config. A difference raises `GeneratorSetupError`: the call is
    logged, the case stays unfinished, and the run stops (resumable). It is never recorded as a model result.
  - **Prompt texts into files:** `prompts/c1_no_knowledge.txt` (C1 block), `prompts/c3_block_template.json` (C3
    headings, explanation lines, line formats, "(none)", "none stated"), `prompts/json_retry_note.json` (retry
    note). They were created from the code constants, unchanged. Exact-whitespace texts are JSON strings.
    Loader: `src/prompt_texts.py`.
  - **Harness:** BPMNGen module/class, mode, format and all output file names are now arguments (from config);
    the defaults equal the old fixed values. A missing class gives a clear error.
  - **File names / thresholds / settings now in config:** bpmngen output folder and file names, mediation
    summary file, rq3 outputs, context_check dir, statistics table names and round_decimals (10),
    trace_min_sentence_chars (15), groq_max_rate_limit_waits (100), ollama_info_timeout_seconds (30). Silent
    defaults in evaluate.py removed (config values required).
- **Files:** `config.yaml`, `prompts/c1_no_knowledge.txt`, `prompts/c3_block_template.json`,
  `prompts/json_retry_note.json` (new), `src/prompt_texts.py` (new), `src/bpmngen_generator.py`,
  `bpmngen_harness/run_bpmngen.ts`, `run_experiment.py`, `src/orchestrator.py`, `src/agents/base_agent.py`,
  `src/generator.py`, `src/run_folder.py`, `src/config.py`, `src/bpmngen_files.py`, `src/llm/{ollama,gemini,
  anthropic,groq}_llm.py`, `src/ollama_server.py`, `src/build_silver_reference.py`, `src/evaluate.py`,
  `src/statistics.py`, `src/rq3_agreement.py`, `src/count_prompt_tokens.py`, `CLAUDE.md`, tests.
- **Tests:** `tests/test_study1_prompts.py` (new, 119 tests). The current config reproduces all 117 stored
  Study 1 generator prompts byte for byte (knowledge block from config = stored knowledge_block.txt; BPMNGen user
  message = harness join of the stored inputs; check_request passes for every stored request) and all 249
  logged agent prompts (195 relevance, 54 applicability; no retries and no requirement calls happened in
  Study 1). Negative checks: changing one template character or the label makes it fail. Plus 7 new tests
  (each request field mismatch stops the run and is logged; harness args from config; generator and agents read
  the same model block). Existing tests moved to the new keys. Suite: 521 passed.
- **Live check:** one real generation (`smoke_fix5_config`, C1, case 01, new folder) passed check_request
  against the real BPMNGen. run_info has the same fields and values as Study 1 plus hashes and library
  versions. The log carries the digest. The model's XML was invalid (missing bpmndi namespace, as in Study 1).
  The harness in list mode with the configured class still sees the same 16 BPMNGen files.
- **Invariant:** all 21 Study 1 outputs byte-identical. results/: no existing file changed; only the new smoke
  run folder and its log were added.
- **Fairness:** the generator request is unchanged (shown for Study 1 data by the reproduction test, and live
  by check_request). C1/C2/C3 still differ only in the knowledge block.
- **Risk / left as is:** the three failure-type lists (evaluate/summarise/statistics) stay in code, because their
  order fixes the column order of existing outputs. `scripts/run_main_experiment.ps1` is kept unchanged as the
  record of what ran Study 1. The retry-note path is covered by unit tests only (no retries in Study 1).
  Old unfinished run folders are unaffected (run_info field names unchanged).

## Fix 6 (C2): freeze C3 v1, 19 Oct 2026
- **What changed:**
  - Annotated git tag `c3-v1-study1` on commit **aa1ca1e**, the last commit before repetition 1 started (your
    choice). It is the code that ran Study 1. The tag is local; push it with `git push origin c3-v1-study1` when
    you push.
  - `src/c3_version.py` (new): SHA-256 fingerprint of every C3 prompt part: the three agent prompt files, the
    three agent output schemas (pasted into each prompt), the JSON retry note and the C3 block template (without
    comments). Line endings are normalised, so a CRLF checkout gives the same hashes.
  - `tests/c3_v1_hashes.json` (new): the v1 hashes, with tag and commit. Before storing, every item was
    cross-checked against the content at aa1ca1e: the agent prompt files, the retry note and the block layout
    (rebuilt from aa1ca1e's code constants) are identical. The agent schema files are unchanged since aa1ca1e.
  - `config.yaml` `mediation:` `c3_version: v1`, `c3_hashes_file: tests/c3_v1_hashes.json` (for the fix 12
    preflight).
- **Tests:** `tests/test_c3_frozen.py` (7 new): C3 unchanged since v1; every part fingerprinted; a one-character
  change in the template or a prompt is detected; line endings alone do not count; a wrong version name is
  refused; the tag points at the stored commit; the tagged prompt files equal today's (skipped if the tag is
  missing in a clone). Suite: 528 passed.
- **Invariant:** all 21 Study 1 outputs byte-identical; results/ byte-identical.
- **Fairness:** no prompt or code behaviour changed; C3 is now guarded against accidental change.
- **Risk:** changing C3 for a later study means creating v2 (new hashes file + config), not editing v1.
  The agent code paths outside the prompts (resolver, quote checker) are not hashed; they are covered by their
  unit tests and by the tag.
