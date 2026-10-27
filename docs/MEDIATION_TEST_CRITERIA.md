# Mediation test criteria (Study 2 corpus)

Written 27 Oct 2026, committed **before any mediation run on the Study 2 corpus**. Nothing in this file was
measured; it only fixes what will be measured and how it is reported. No model or retrieval was run for this file.

## 1. Setup

- **Agents only, no generation.** Only the C3 mediation agents run; BPMNGen is not called.
- **C3 version:** C3 v2 = tag `c3v2-logic-final-fix1` + the R2/R3 extensions to the new laws (commit `19cfe82`).
  The decision logic is unchanged (rules R1–R6, [C3_V2_DEVELOPMENT.md](C3_V2_DEVELOPMENT.md) section 9).
- **Model:** qwen3:8b on Ollama 0.40.11 (digest checked as for every run), agent settings from `config.yaml`.
- **Cases:**
  - Development variants: 01.1, 01.2, 06.1, 11.1, 13.1, 17.1, 19.1, 45.1, plus their base cases
    01, 06, 11, 13, 17, 19, 45.
  - Held-out variants, old: 03.1, 05.1, 21.1, 37.1, 46.1; v3: 03.2, 05.2, 10.1, 21.2, 46.2; plus their base cases.
    Measured **once**, reported separately, **never** used to change anything.
- **Two retrieval settings:**
  - **R** = frozen RAG top-5 (`data/retrieval_study2_corpus/frozen_retrieval_v2.json`).
  - **O** = oracle top-5 = the frozen top-5 with rank 5 replaced by the variant's target passage if the target is
    not already in it. O is a pre-declared diagnostic, not a result of the retrieval.
  - The base case gets the **same** top-5 as its variant in each setting (so T2/T3 compare like with like).

## 2. Measures

| ID | Setting | Measure |
|----|---------|---------|
| T1 | O | Target hit: the target passage is labelled Applicable in the variant, with a verified quote from the **added** sentence(s) of the variant. |
| T2 | O | Control: the target passage is **not** Applicable in the base case. |
| T3 | R and O | Wrong Applicables: Applicable passages that are not the target; each listed with its quote. |
| T4 | R | Drop rate: share of retrieved passages **not** passed to the C3 block. |
| T5 | O, target hits only | Requirement quality: code checks (≤ 40 words, every THEN trigger kept, `step_quote` verbatim in the passage) + the requirement text listed. |

## 3. Targets

Reported, not tuned: the logic is final, so no change is made to reach them.

- T1 ≥ 6/8 on the development variants.
- T2 ≥ 7/8.
- T3 = 0 in the base cases.
- T5: all code checks pass.

T4 and the held-out results have no target; they are reported only.

## 4. Misses and fixes

- Every miss (T1, T2, T3, T5) is reported with its audit trail, naming the box that failed: relevance, split,
  scope/role rule, check-IF, quote check, resolver, or requirement.
- Only a **proven bug** (the code does not follow rules R1–R6) may be fixed. It is recorded as a bug fix in
  [C3_V2_DEVELOPMENT.md](C3_V2_DEVELOPMENT.md), not as a round.
- **No** prompt changes and **no** rule changes because of these results.

## 5. Run

The task that runs these measurements must contain the keyword **REAL RUN**. This document makes no run.

## 6. Note, 27 Oct 2026 (after the development and held-out runs; nothing above changed)

- **(a) T5 wording correction:** step_quote is checked against the DESCRIPTION, as rule R6 says; by R6, T5 = 1/1.
- **(b) Diagnostic:** same test, setting O, 8 development variants + base cases, with one stronger open-source model
  on Groq; logic unchanged; result decides only whether the model is the bottleneck.
- **Model (picked by rule, 27 Oct 2026, from console.groq.com/docs/models):** the largest production text model on
  Groq that is not gpt-oss (silver), supports JSON output and has >= 16k context. Production text models:
  llama-3.1-8b-instant, llama-3.3-70b-versatile, openai/gpt-oss-20b, openai/gpt-oss-120b -> **`llama-3.3-70b-versatile`**
  (131,072 tokens context; JSON object mode). In `config.yaml c3_agents_llm.groq.model`; the agents' default stays
  Ollama (`c3_agents_llm.provider: ollama`). Script: `scripts/run_mediation_strong.py`.
- **27 Oct: llama-3.3-70b-versatile not available (404); model chosen from the live list by the same rule.**
  Live list (Groq `GET /models` with this account): the only text models that are not gpt-oss are `allam-2-7b`
  (4,096 tokens context, below 16k) and `qwen/qwen3.8-27b` (131,072 tokens context, 16,384 max completion tokens)
  -> **`qwen/qwen3.8-27b`**. One short JSON test call answered valid JSON with no reasoning text.
