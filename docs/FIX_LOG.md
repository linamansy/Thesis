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
