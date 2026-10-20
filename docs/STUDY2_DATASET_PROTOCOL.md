# Study 2 dataset protocol (GDPR) — DRAFT, 19 Oct 2026

Status: **draft for Lina to check and commit**. The screening in `data/study2/selection_screening_DRAFT.csv` was done by an AI assistant and is **provisional**. It becomes the final `data/study2/selection.csv` only after Lina screens all 55 cases herself (and, ideally, a second person does too).

## 1. Purpose

Study 1 found 0 silver-applicable rules (CRD/LPD knowledge, 13 Order & Purchasing cases), so the legal side of RQ1 and RQ3 could not be measured. Study 2 uses a legal source that applies to many more processes (GDPR) and cases chosen by a fixed rule, so that applicable rules actually occur.

## 2. Source data

- Cases: PMo dataset (Brissard, Cuppens, Zouaq; Zenodo 10.5281/zenodo.15857589, CC BY 4.0), 55 description + reference BPMN pairs, `data/raw/pmo/`. Reference = `bpmn/<id>.bpmn` (README: "should be used as the ground truth").
- Knowledge: Regulation (EU) 2016/679 (GDPR), CELEX 32016R0679, official English text, original OJ version (OJ L 119, 4.5.2016), downloaded the same way as the CRD/LPD (CELLAR, XHTML, `Accept-Language: eng`), stored in a **separate** collection with its own `sources.json` entry and SHA-256. Not yet downloaded (the cloud workspace cannot reach publications.europa.eu; download it on your PC).
  - Decide and write down: original 2016 text vs. the corrigendum-consolidated version. For consistency with Study 1 ("original version, not consolidated"), use the original.

## 3. Selection rule (from ANALYSIS_PLAN.md §7, committed) and how it is applied

Rule as committed: *include if the description explicitly involves recording, sending or evaluating data about an identifiable person; exclude anonymous transactions and purely private activities (GDPR Art. 2(2)(c)); borderline cases excluded with written reasons.*

Operational codebook (added now, before final screening — log it as a clarification, not a change):

| Code | Meaning | GDPR anchor (verify wording in the downloaded text) |
|---|---|---|
| A | The text names or clearly refers to a **natural person** (customer, employee, applicant, guest, user/"you", insurant, patient). Companies/suppliers do not count. | Art. 4(1) "personal data" |
| B | The text has an **explicit** step where an organisation or IT system records/enters/logs/stores, sends/notifies/forwards, or evaluates/rates/scores **information about that person**. Data only about a product, machine or order item does not count. | Art. 4(2) "processing" |
| E1 | Anonymous transaction (nothing about the person is kept). | — |
| E2 | Purely personal or household activity (only a private person and friends/family). | Art. 2(2)(c) |
| Borderline | A or B only implied, or roles unclear → **exclude**, reason written. | §7 of the plan |

Include = A and B and not E1/E2.

Screening is based on the **description text only** (never on model outputs or on the reference BPMN), so it cannot be tuned towards a result.

## 4. Provisional screening result (AI draft)

| Group | Cases | n |
|---|---|---|
| Pilot cases (Study 1) that meet the rule | 01, 06, 11, 13, 17, 19, 45 | 7 |
| Pilot cases that do not meet the rule | 03, 05, 10, 21, 37, 46 | 6 |
| New cases that meet the rule | 02, 04, 07, 12, 18, 20, 22, 23, 25, 26, 27, 28, 29, 31, 43, 47, 48, 51 | 18 |
| Borderline → excluded | 08, 39, 50, 52, 53, 54 | 6 |
| Clearly excluded | 09, 14, 15, 16, 24, 30, 32, 33, 34, 35, 36, 38, 40, 41, 42, 44, 49, 55 | 18 |

Weakest includes, worth a second look: **04** (leads could be companies), **29** and **48** (written from the data subject's own view; 29 is long and already contains legal requirements), **27** (5,371 characters and already contains Austrian legal rules → watch context_limit_hit).

## 5. Development / test split

- **Development set = the 13 Study 1 pilot cases** (01, 03, 05, 06, 10, 11, 13, 17, 19, 21, 37, 45, 46). Reason: you have already looked at their outputs, debugged on them and analysed their failures, so they are no longer clean test data.
  - The 7 GDPR-qualifying ones (01, 06, 11, 13, 17, 19, 45) are used for Study 2 pipeline checks (GDPR retrieval, agent prompts fit the context, preflight).
  - All 13 can be used for model selection (§6).
- **Test set = new cases that meet the rule** (currently 18; final number after your screening).
- This changes ANALYSIS_PLAN §7, which planned to include qualifying pilot cases in Study 2 → **log as a deviation with date and reason** (reason above).

Hold-out rules for the test set (write these into the addendum and keep them):
1. No generation, retrieval inspection or silver labelling on test cases until the model, prompts, agents, retrieval settings and scoring are frozen and committed.
2. After the first test generation, nothing is changed. If something must change, it is a logged deviation and the whole test run is repeated.
3. Agents stay exactly as in Study 1 (the RelevanceAgent error mode is reported, not fixed — fixing it on cases you have seen would be tuning).

## 6. Choosing the stronger model (development cases only)

Fixed **before** looking at any candidate output:

Hard requirements (a model failing one is out):
1. Not qwen (generator of Study 1) and not gpt-oss (silver annotator) → a third model family.
2. Same model for BPMNGen generation **and** the C3 agents (ANALYSIS_PLAN §8), so C3 cannot win through a stronger mediator.
3. Usable through BPMNGen **without changing BPMNGen files** (check whether its OpenAI-compatible class can point to the provider; harness changes only).
4. Pinned model id/version recorded in run_info.json; temperature as in Study 1 (0.3 generator, 0 agents).
5. Context window ≥ 32k (your longest C2/C3 prompts must fit).
6. Free or affordable for ~(test cases × 3 conditions × 3 reps) + agent calls, with rate limits that let you finish.

Selection run (development cases only):
- Run **C1 only** (no knowledge) on all 13 development cases, 1 repetition per candidate.
- Choose by: (a) valid-or-rescued BPMN rate, (b) no reasoning/thinking leakage, (c) tie-breaker: mean C1 task F1.
- **Never use C2/C3 results to pick the model** — that would select a model that favours one condition.
- Write the result to `docs/STUDY2_MODEL_SELECTION.md` and commit before any test run.

Candidates to check (availability checked 19 Oct 2026; re-check before use):
- `llama-3.3-70b-versatile` on Groq (Meta; listed as a production model, 131k context; you already have a Groq account). Strongest fit for the hard requirements.
- Mistral (Small/Medium) via the free "Experiment" plan: needs phone verification (NVIDIA failed for this reason), and requires opting in to data training — fine for PMo, but say so in the thesis.
- Not allowed: anything qwen (incl. `qwen/qwen3.8-27b` on Groq), anything gpt-oss. Preview models should be avoided (can be removed at short notice).

## 7. Silver reference for Study 2

Same silver model and prompt as Study 1 (gpt-oss-120b via Groq, temperature 0), new GDPR frozen retrieval, always called **provisional**. Plan §6 (too few applicable rules) still applies.

## 8. Files

- `data/study2/selection_screening_DRAFT.csv` — AI draft with reason and verbatim evidence quote per case; columns `lina_decision`, `lina_reason`, `second_rater_decision` are empty for you.
- `data/study2/selection.csv` — final, after your screening (agreement between AI draft, you and a second rater reported as % agreement and Cohen's kappa).
- `data/knowledge_gdpr/` — raw GDPR file, `sources.json`, passages, frozen retrieval with SHA-256 checksums (in the addendum).
