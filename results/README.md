# results/: what every file is

Written 19 Oct 2026 (fix E3). **`MANIFEST.csv`** lists every file in this folder, one row each: path, status, run id,
repetition, condition, case, role (the names used below), size and SHA-256. It was built read-only by
`python -m src.results_manifest`; it does not list itself or this README. Recompute a file's SHA-256 and compare it
with the manifest to show the file is unchanged.

**Status** in the manifest:
- `study` = a run in `config.yaml statistics.runs` (Study 1: `ollama_rep1`, `ollama_rep2`, `ollama_rep3`). Only
  these are evaluated and analysed.
- `smoke` = a test run (id starts with `smoke`). Never evaluated.
- `discarded` = kept, but never used.
- `other` = everything else (top-level tables, diagnostics, logs without a run).

## runs/: one folder per run = one repetition (`results/runs/<run_id>/`)

| File | What it is |
|---|---|
| `run_info.json` | Settings of the run (model, digests, Ollama version and server settings, temperature, seed, num_ctx, think; from 19 Oct 2026 also `bpmngen_file_hashes` and `bpmngen_library_versions`), and per condition the parts run, their start/end times and log files, and the counts. A later part with other settings is refused. |
| `<C1\|C2\|C3>/<case>/knowledge_block.txt` | The exact knowledge block given to the generator for this case. C1: the fixed sentence. C2: the 5 frozen passages. C3: the mediated block. |
| `<cond>/<case>/generated.bpmn` | The BPMN model that is evaluated (copy of `bpmngen/generated.bpmn`). |
| `<cond>/<case>/validation.json` | Written LAST: its existence marks the case as finished. Our strict validator's verdict (`valid`, `errors`, counts), failure flags (`context_limit_hit`, `timed_out`, `thinking_detected`) and the BPMNGen meta data used by the evaluation. |
| `<cond>/<case>/evaluation.json` | Per-case details of the main evaluation (matched, missing and extra tasks with similarities, behavioural pairs, silver diagnostics, reference complexity). Written by `python -m src.evaluate`. |
| `<cond>/<case>/bpmngen/ollama_request.json` | The exact request sent to Ollama (system prompt, user message, options, `think`). |
| `<cond>/<case>/bpmngen/raw_model_output.txt` | The model's answer before BPMNGen's cleanup. |
| `<cond>/<case>/bpmngen/raw_thinking.txt` | Ollama's separate thinking field (empty when thinking was off). |
| `<cond>/<case>/bpmngen/bpmngen_cleaned_output.txt` | The answer after BPMNGen's cleanup. |
| `<cond>/<case>/bpmngen/generated.bpmn` | The BPMN BPMNGen produced from it. |
| `<cond>/<case>/bpmngen/validation.json` | BPMNGen's own bpmnlint verdict (reported as `bpmnlint_valid`). |
| `<cond>/<case>/bpmngen/meta.json` | Harness meta data: model, num_ctx, temperature, think, token counts, `done_reason`, `fits_context`, `auto_repairs`, thinking flags, time. From 19 Oct 2026 also `repair_counts`. |
| `C3/mediation/<case>.json` | C3 provenance per passage: relevance output and quote check, applicability output, the resolver's checked conditions and label, the requirement (Applicable only), and the case's knowledge block. |
| `C3/mediation/run_summary.json` | Counts over the mediation files of the run (labels per passage, downgraded conditions, quote checks). |

Run folders: `ollama_rep1`–`ollama_rep3` (Study 1, 18 Oct 2026). Smoke runs: `smoke_bpmngen`, `smoke_speed`,
`smoke_nothink_pre_tagfix`, `smoke_nothink` (18 Oct 2026, before Study 1), and `smoke_fix5_config`,
`smoke_fix7_repairs` (19 Oct 2026, one case each, checks of fixes 5 and 7).

## logs/: every LLM call
| File | What it is |
|---|---|
| `<cond>_<run_id>.jsonl`, `..._part<n>.jsonl` | One JSON record per LLM call (prompt, raw output, parsed output, model, digest, finish reason, temperature, time) of that condition and run; `_part<n>` = a resumed part. |
| `SILVER_silver_<timestamp>.jsonl` | Calls of the silver annotator. `..._20261018T124712Z` = the discarded Gemini build; `..._20261018T212241Z` = the gpt-oss-120b build used (data/silver/silver_reference.json). |
| `main_experiment_console.log` | Console output of `scripts/run_main_experiment.ps1` for Study 1. |

## Main evaluation (python -m src.evaluate) and statistics (python -m src.statistics)
| File | What it is |
|---|---|
| `evaluation.csv` | One row per run × condition × case (117 for Study 1): validity, failure type, precision, recall, F1, behavioural similarity, extra and knowledge-traceable tasks, silver legal diagnostics, generator diagnostics, reference complexity. Main similarity threshold 0.75. |
| `evaluation_run_summary.csv` | One row per run × condition: means over the cases, failure-type counts. |
| `evaluation_summary.csv` | One row per condition: mean and SD over the repetitions. |
| `sensitivity/evaluation_threshold_<t>.csv`, `sensitivity/summary.csv` | The evaluation at similarity thresholds 0.70 / 0.75 / 0.80 / 0.85, and their summary (`--sweep`). |
| `sensitivity/trace_threshold_<t>.csv`, `sensitivity/trace_summary.csv` | The knowledge-traceable diagnostic at trace thresholds 0.4 / 0.5 / 0.6, and their summary (`--sweep`). |
| `statistics/rq1_primary_tests.csv` | Friedman test, planned Wilcoxon tests (C3–C1, C3–C2) with Holm correction, effect sizes; C2–C1 descriptive. |
| `statistics/rq1_descriptive.csv` | Per condition and metric: mean, median, quartiles of the case means. |
| `statistics/rq1_overapplication.csv` | Over-application (unjustified knowledge additions), C3 vs C2. |
| `statistics/rq2_spearman.csv`, `statistics/rq2_case_effects.csv` | RQ2 (exploratory): Spearman correlation of per-case effects with reference complexity, and the per-case values. |
| `statistics/secondary_valid_or_rescued_tests.csv` | The planned tests on valid or rescued generations only. |
| `statistics/failure_types.csv` | Generations, valid count and each failure type per condition. |
| `rq3_agreement.csv`, `rq3_confusion.json` | RQ3: agreement of C3's applicability labels with the silver labels per run (accuracy, Cohen's kappa) and the confusion matrices. Agreement with a stronger model, not correctness. |

## diagnostics/: added analyses (not part of the planned statistics)
| File | What it is |
|---|---|
| `harness_checks.md`, `precision_recall.md` | Pilot diagnostics reports (commit a0780fb). |
| `extended_scoring_study1.csv` / `.md` | Extended-reference scoring (fix 8): PMo tasks + silver expected requirements. PROVISIONAL until the Study 2 analysis-plan addendum is committed. |
| `structure_measures_study1.csv` / `.md` | Actors, decisions, start/end events matched against the reference (fix 10). |
| `matcher_sample.csv` | 30 matched + 30 unmatched task pairs (seed 42) with an empty `manual_judgement` column (fix 11). |

## Other
| File | What it is |
|---|---|
| `run_main_experiment.ps1` | Byte-identical copy of `scripts/run_main_experiment.ps1`, the script that ran Study 1. |
| `_discarded/ollama_rep1_thinking_on/` | The first, partial repetition 1 (C1, made while qwen3 still thought in hidden; case 21 looped to 122,236 tokens). Kept, never evaluated; see its `README.txt`. |
