# Analysis Plan (fixed after data generation, before any evaluation)

## 1. Unit of analysis
Study 1: 13 PMo cases x 3 conditions (C1/C2/C3) x 3 repetitions = 117 generations. For tests, the 3 repetitions are averaged per case and condition (13 paired values per condition). n = 13 is small: effect sizes with 95% CIs are reported alongside p-values; results are presented as evidence, not proof.

## 2. RQ1 – mediation and BPMN quality
Primary metrics: task-matching F1 (threshold 0.75) and behavioural-profile similarity, both against the PMo reference model.
Planned comparisons: C3 vs C1 and C3 vs C2 (two-sided); C2 vs C1 descriptive.
Tests: Friedman test across C1/C2/C3; Wilcoxon signed-rank for the two planned comparisons; Holm correction over the 4 primary tests; alpha = 0.05.
Effect sizes: median paired difference with bootstrap 95% CI; matched-pairs rank-biserial correlation.
Secondary (descriptive): precision, recall, validity, complexity, precision_adjusted, requirement_coverage, extra-task diagnostics.
Over-application: n_unjustified_knowledge_additions, C2 vs C3 (Wilcoxon), always reported.

## 3. RQ2 – complexity as moderator
Complexity measured on the PMo reference model only (number of flow nodes; Cardoso's CFC). Spearman correlation between case complexity and per-case effect (C3−C1, C3−C2) on the primary metrics. Exploratory.

## 4. RQ3 – mediation mechanism
Applicability: C3 agent labels vs silver labels (accuracy, Cohen's kappa, full confusion matrix, percent agreement); kappa paradox discussed if one label dominates.
Requirement fidelity: only for rules both agents and silver call applicable, against silver required_steps; otherwise "not estimable".
Silver annotator: openai/gpt-oss-120b via Groq (open-weight, different model family from the qwen3 generator and agents), temperature 0, one annotator for all cases. A partial Gemini build (3 cases) was discarded before use because of the Gemini free-tier limit. The silver reference is AI-made and always called provisional, never gold.

## 5. Data handling (decided before the runs)
- Invalid outputs that cannot be rescued score 0 (main analysis). Secondary analysis: valid or rescued outputs only.
- Only rescue: removing the bpmndi diagram section for structural metrics (di_stripped). No other repair, no retries.
- Stray </think> tags: genuine model failure, scored 0, counted as thinking_detected. Observed during the runs (before evaluation): 25 of 117 generations flagged; reported, not corrected.
- Cut-off answers (context_limit_hit) and timeouts are failed generations, scored, never retried.
- Failure-type table per condition: other invalid XML, missing namespace (rescued), thinking_detected, context_limit_hit, timed_out.
- Thresholds fixed: similarity 0.75 (sweep 0.70–0.85); trace_threshold 0.5 (sweep 0.4/0.5/0.6). Sweeps are robustness checks only.
- Excluded: smoke runs and the discarded thinking-on run (results/_discarded/).
- Limitation: BPMNGen fixes num_ctx at 16384, so longer prompts (C2/C3) leave less room for the answer; context_limit_hit is reported per condition.

## 6. Too few applicable rules
If fewer than about 3 cases have at least one silver-applicable rule, the legal metrics of RQ1 and the fidelity part of RQ3 are reported as limited, and the over-application analysis (section 2) is emphasised.

## 7. Study 2 (GDPR), if conducted
Cases: all 55 PMo cases filtered by the rule "include if the description explicitly involves recording, sending or evaluating data about an identifiable person; exclude anonymous transactions and purely private activities (GDPR Art. 2(2)(c))"; borderline cases excluded with written reasons (data/study2/selection.csv).
Knowledge: separate GDPR collection (CELEX 32016R0679), same chunker, its own frozen retrieval and silver (same silver model and prompt as Study 1). Same generator, agents, settings and this analysis plan. Reported separately from Study 1; never pooled into one test.

## 8. Additional data or models
If a dataset with descriptions, reference BPMN models and clear legal relevance becomes available, it is analysed as an additional study with this plan. A stronger generator may be added as a separate robustness study; generator and agents then use the same model, and the silver annotator must be from a different model family. Studies are never mixed.

## 9. Deviations
Any change after this commit is reported as a deviation with date and reason.

- 2026-10-19 – implementation fix: smoke runs excluded from rq3 output, main numbers unchanged. src/rq3_agreement.py had also listed the smoke runs (smoke_bpmngen, smoke_nothink) as separate rows, against section 5; they are now left out. The rows and confusion matrices of ollama_rep1–3 are identical before and after the fix.
- 2026-10-19 – addendum (fix E1, your decision; no change to the analysis): checksums of the frozen retrieval, which the preflight check (src/preflight.py) compares before any generation. `data/retrieval/frozen_retrieval.json` SHA-256 `0a59828ad966dc04dfe9fb66fb7c1e4ac599f68a56d3abcac57c25ffa43b5ab7`; `data/knowledge/passages.jsonl` SHA-256 `cb8b262906d48b2d6e31fc8f434fb804caa2b333150dd5fabeef0194d87c5aa6`. These are the files used for Study 1 (frozen 14 Oct 2026, commit ee5f8b4; the silver reference records the same frozen-retrieval checksum).
