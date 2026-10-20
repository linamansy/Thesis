# Analysis plan addendum: Study 2 (GDPR) — DRAFT, 19 Oct 2026

Commit this **before** any Study 2 generation on test cases. Items marked **[DECIDE]** must be filled by Lina first. Everything not mentioned here stays as in `docs/ANALYSIS_PLAN.md`.

## A. Deviations from ANALYSIS_PLAN §7 (log each in §9 with date and reason)

1. **Cases:** Study 1 pilot cases are a development set and are **not** part of the Study 2 test set (they were used for debugging and failure analysis). Test set = new PMo cases that meet the §7 rule (see `docs/STUDY2_DATASET_PROTOCOL.md`).
2. **Generator model:** §7 said "same generator". Study 2 uses **[DECIDE: model id]**, chosen on development cases only with the pre-set criteria in the dataset protocol §6. Generator and C3 agents use this same model (§8). BPMNGen code, system prompt, temperature 0.3 and num_ctx **[DECIDE: same 16384 or model default — must be equal for C1/C2/C3]** unchanged.
3. **Scoring:** extended metrics added as **secondary** (section D). Primary metrics are unchanged.

Consequence to state in the thesis: Study 2 differs from Study 1 in **two** things (legal domain and model). Study 2 is analysed on its own; differences between Study 1 and Study 2 are not attributed to either factor. [Optional, recommended if budget allows: also run qwen3:8b on the Study 2 test cases, so domain and model effects can be separated.]

## B. Unit of analysis

n test cases (**[DECIDE: final n]**, currently 18) × C1/C2/C3 × 3 repetitions. Repetitions averaged per case and condition. Never pooled with Study 1.

## C. Primary analysis (identical to Study 1)

- Metrics: task-matching F1 (threshold 0.75) and behavioural-profile similarity vs. the PMo reference.
- Friedman across C1/C2/C3; Wilcoxon signed-rank for C3 vs C1 and C3 vs C2 (two-sided); Holm over the same 4 primary tests; alpha 0.05.
- Effect sizes: median paired difference with bootstrap 95% CI; matched-pairs rank-biserial r.
- Data handling (invalid = 0, only rescue = di_stripped, no retries) as in plan §5.

## D. Extended scoring (secondary, reported but never replacing primary)

**[DECIDE which of these you mean by "extended scoring"; delete the others.]** Each must be fully defined and tested on development cases before the test run.

1. **Legal requirement coverage:** for rules that silver labels Applicable, share of silver `required_steps` that appear in the generated model (same matcher, threshold 0.75). Only if plan §6 does not apply.
2. **Over-application:** unjustified knowledge additions per model (C2 vs C3, Wilcoxon) — now with a meaningful number of GDPR passages.
3. **Wording-robust matching** (Study 1 finding: matcher under-credits reworded tasks): **[DECIDE method, e.g. embedding model + threshold]**. Report as a sensitivity analysis next to the primary F1; may also be re-run on Study 1 data, labelled as post-hoc.
4. RQ3 applicability agreement (agents vs. silver): accuracy, Cohen's kappa, confusion matrix, as in plan §4.

## E. RQ2 (exploratory, as in plan §3)

Spearman between reference-model complexity (flow nodes, CFC) and per-case effects. Exploratory; no correction claims.

## F. Freeze checklist (all committed, with hashes, before the first test generation)

- [ ] `data/study2/selection.csv` final (own screening done; agreement reported)
- [ ] GDPR raw file + `sources.json` entry with SHA-256
- [ ] GDPR passages + frozen retrieval with SHA-256 (same chunker and retrieval settings as Study 1)
- [ ] `docs/STUDY2_MODEL_SELECTION.md` (dev-only, C1-only selection result)
- [ ] Model id/version, provider, temperature, context setting in run_info.json
- [ ] Extended metrics implemented and tested on synthetic + dev data only
- [ ] Silver reference for test cases generated (same silver model/prompt) — before evaluation, after generation is fine
- [ ] preflight.py passes with the Study 2 checksums
