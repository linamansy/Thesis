# RAG v2 criteria (Study 2 corpus)

This file fixes how RAG v2 (`src/rag_v2.py`, `config.yaml` `rag_v2`) is measured and how the one open setting,
`rag_v2.sibling_expansion`, is decided. Written on 27 Oct 2026, **before** any retrieval run on the Study 2 corpus
(`data/knowledge_study2_corpus/`: GDPR, CRD, LPD, SGD, ECD). Draft by Claude, approved by Lina.

No code, prompt, config, frozen retrieval or silver file was changed when this file was written.

---

## 1. Expected laws per real case

Written now, from the case domain only (what kind of business process the case is), not from any retrieval output.
A law is "expected" if a passage from it could plausibly apply to a process of this kind.

| Case | Label (`study2_cases.labels`) | Expected laws |
|------|-------------------------------|---------------|
| 01 | development | CRD, ECD, GDPR |
| 06 | development | CRD, SGD, ECD, GDPR |
| 11 | development | CRD, GDPR |
| 13 | development | SGD, GDPR |
| 17 | development | CRD, SGD, ECD, GDPR |
| 19 | development | CRD, SGD, ECD, GDPR |
| 45 | development | CRD, SGD, ECD, GDPR |
| 03 | non-development | LPD, GDPR |
| 05 | non-development | LPD, GDPR |
| 21 | non-development | LPD, GDPR |
| 46 | non-development | LPD, GDPR |
| 10 | non-development | GDPR |
| 37 | non-development | GDPR |

Law = passage id prefix (`GDPR-`, `CRD-`, `LPD-`, `SGD-`, `ECD-`).

## 2. Measures

- **M1, variant hit@5**: for each of the 8 variants in `data/retrieval_study2_corpus/retrieval_test_set.json`
  (01.1, 01.2, 06.1, 11.1, 13.1, 17.1, 19.1, 45.1), is its target passage in the top 5? M1 = number of hits out of 8.
- **M2, expected-law share**: for each of the 7 development cases (01, 06, 11, 13, 17, 19, 45), the share of its
  top-5 passages whose law is an expected law of that case (section 1), from 0 to 1. Reported per case and as the
  mean over the 7 cases.

Both are computed by `src/evaluate_retrieval_v2.py` for sibling expansion OFF and ON.

## 3. Decision rule for sibling expansion

Decided on the 8 variants and the 7 development cases only.

Keep `rag_v2.sibling_expansion` **ON** if both hold:

1. M1(ON) > M1(OFF), and
2. mean M2(ON) ≥ mean M2(OFF) − 0.10.

Otherwise **OFF**. A tie in M1 gives OFF (the simpler setup).

## 4. Adequacy target

Reported, not used to tune: **M1 ≥ 5/8** for the chosen setting.

If it is not met:

- it is reported as a limitation;
- any further RAG change (for example query rewriting) needs its own criteria, written in this file before it is
  tried;
- at most 1 extra round of changes. After that round the result is reported as it is.

## 5. Non-development cases

The 6 non-development cases (03, 05, 10, 21, 37, 46) are measured (M2) only **after** the decision of section 3 and
the freeze of the retrieval. Their results are never used for any decision.

## 6. Silver on the new corpus

After the freeze, silver labels are built for the 13 real cases on the new corpus as a second view: the top-20
candidate pool of each case, annotated by gpt-oss-120b (Study 1 silver setup). The labels are provisional, never
gold. The silver model is never the generator or agent model (qwen3:8b).

---

## 7. Extra round (the only one allowed by section 4)

Written on 27 Oct 2026, after the measurement of section 3 and **before** any run of this round. No retrieval and no
model was run to write it. Draft by Claude, approved by Lina.

### 7.1 Reason

- M1 = 2/8 with the frozen setting (sibling expansion OFF); the target of section 4 is 5/8.
- For 5 of the 8 variants the target passage is not even in the top-20 candidates, so the reranker cannot reach it.
- LPD-type cases retrieve no LPD and no GDPR passages: the descriptions use business words ("invoice", "pay within
  30 days"), the law uses legal words ("commercial transaction", "late payment interest") — a vocabulary gap.
- The variant sentences stay unchanged: they are realistic business language, and the retrieval has to cope with it.

### 7.2 Pre-declared configurations

Same in all four: sibling expansion OFF; embedding model `intfloat/e5-small-v2`; reranker
`cross-encoder/ms-marco-MiniLM-L-6-v2` (same revision, mean over the queries, top 5); corpus
`data/knowledge_study2_corpus/` with passages SHA-256 `d30eea57b4773c24772a88d0f68cb61c0f3d6e29466a7ccf5dbbce0e574fd43b`.

| Config | Change against the current freeze |
|--------|-----------------------------------|
| **A** | Index text: each passage is prefixed with law name + article number + article title (e.g. `Late Payment Directive 2011/7/EU, Article 3: Transactions between undertakings.`) before it is embedded, BM25-indexed and reranked. Index text only; the corpus file and the passage text given to C2/C3 are unchanged. |
| **B** | Query rewriting: qwen3:8b (Ollama 0.40.11, temperature 0, seed 42, think false, num_ctx 16384) rewrites each description once into short legal-concept queries with the fixed prompt in 7.3. The rewritten queries are **added** to the original queries (full description + each sentence); the originals are kept. Every rewriting input and output is saved. |
| **C** | Hybrid first stage (BM25 + dense, reciprocal rank fusion, k = 60) with a candidate pool of **50** instead of 20 (top 50 from each retriever, top 50 after fusion go to the reranker). |
| **D** | A + B + C together. |

### 7.3 Query-rewriting prompt (config B and D, fixed)

`{description}` is replaced by the case description, verbatim. Nothing else is changed. The answer is parsed as
one query per non-empty line; lines are stripped of leading "-", "*" and numbering; empty answers give no extra
queries (the original queries are still used).

```text
/no_think
You help a search engine find relevant passages of EU law for a business process.

Below is a description of a business process. Rewrite it as short search queries in the vocabulary of EU law
(for example: consumer, trader, distance contract, right of withdrawal, pre-contractual information, commercial
transaction, late payment, interest for late payment, personal data, data subject, controller, conformity of goods,
information society service, order confirmation).

Rules:
- Write between 3 and 8 queries.
- Each query is at most 12 words.
- Use only concepts that the process description supports. Do not name directives, articles or numbers.
- Write one query per line. No numbering, no explanations, no other text.

Process description:
{description}
```

### 7.4 Selection rule

Decided on the 8 variants (M1) and the 7 development cases (M2) **only**:

1. highest M1 wins;
2. tie → higher mean M2;
3. tie → simpler config, in the order A < C < B < D.

The winner replaces the current frozen retrieval (`data/retrieval_study2_corpus/frozen_retrieval_v2.json`) **only if
its M1 > 2/8**. Otherwise the current freeze is kept unchanged.

### 7.5 Adequacy target

Unchanged: M1 ≥ 5/8, reported only, never used to tune. **No further rounds after this one**; the result is
reported as it is.

### 7.6 Non-development cases

The 6 non-development cases are measured (M2) only after the new freeze (or after keeping the current one). They are
never used for selection.

### 7.7 Fairness

The same retrieved passages go to C2 and C3, as before. Only the knowledge block differs between C1, C2 and C3.

### 7.8 Held-out check

Before any run of this round, 5 new variants of **non-development** cases (03.1, 05.1, 21.1, 37.1, 46.1) are
written (same format as section 2's variants: description, `variant.json` with one target passage, provisional
reference) and approved by Lina. They are **never** used for selection. They are measured **only once**, after the
new freeze (or after keeping the current one): M1 held-out = hits @5 out of 5, reported next to M1 on the 8.
