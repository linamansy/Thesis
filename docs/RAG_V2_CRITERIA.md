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

---

## 8. RAG v3 (exploratory, added after pre-registered rounds failed)

Written on 27 Oct 2026, after the extra round of section 7 and **before** any run of RAG v3. No retrieval and no
model was run to write it. Draft by Claude, approved by Lina.

### 8.1 Honest note

- Sections 4 and 7.5 allowed **no further rounds** after the extra round. This section goes beyond the
  pre-registered plan.
- Pre-registered results, reported as they are: M1 = 2/8 (current freeze kept, section 7.4); held-out M1 = 0/5
  (section 7.8).
- A bug check found no bug: passages are retrieved correctly when the query uses legal wording; they are not when
  the query uses business wording (vocabulary gap, section 7.1).
- Lina decided on **one exploratory round**. Every RAG v3 result is labelled **exploratory** in the thesis and in
  every output file name or header. The pre-registered results of sections 3 and 7 stay the main reported results.
- This is the **last retrieval change**. Whatever RAG v3 gives is reported as it is.

### 8.2 Options

Same in all three: sibling expansion OFF; corpus `data/knowledge_study2_corpus/` with passages SHA-256
`d30eea57b4773c24772a88d0f68cb61c0f3d6e29466a7ccf5dbbce0e574fd43b` (289 passages), unchanged; BM25, RRF (k = 60),
pool 20, mean over the queries, top 5 as in the current freeze; queries = full description + each sentence (no query
rewriting). **C2 and C3 always receive the original passage text** from the corpus file; model changes and
enrichment text affect only the search.

| Option | Change against the current freeze |
|--------|-----------------------------------|
| **E** | Stronger local models (both fit together on the 8 GB RTX 4060 in fp16, about 1.1 GB each): dense embedding model **`BAAI/bge-m3`** (dense vectors only, normalised, FAISS IndexFlatIP, max length 8192, no query/passage prefix as the model card says) instead of `intfloat/e5-small-v2`; reranker **`BAAI/bge-reranker-v2-m3`** instead of `cross-encoder/ms-marco-MiniLM-L-6-v2`. Version = the Hugging Face commit hash of each model at download; both hashes are written into this section and `config.yaml` before the first E run and never changed. Chosen before any run by general quality (widely used multilingual/English retrieval and reranking models of the same family, long input length, runnable on 8 GB), not by these cases. Ollama is not running a model while retrieval runs. |
| **F** | Passage enrichment: for each of the 289 passages, qwen3:8b (Ollama 0.40.11, digest of `model.ollama_model_digest`, temperature 0, seed 42, think false, num_ctx 16384) writes 1–2 plain business-language sentences on when the passage applies in a business process, with the fixed prompt in 8.3. Input = the passage text only (never a case, variant or description). Generated **once**, saved with every prompt and raw answer (log as for all LLM calls), and the enrichment file is SHA-256 hashed in a manifest before any retrieval run with it. Index text = passage text + newline + enrichment; used for BM25, the dense index (own index folder) and the reranker. Models as in the current freeze. |
| **G** | E + F together (bge-m3 and bge-reranker-v2-m3 on the enriched index text). |

### 8.3 Enrichment prompt (option F and G, fixed)

`{passage_text}` is replaced by the passage's `text` field from the corpus file, verbatim. Nothing else is changed.
The answer is stripped of leading/trailing whitespace and used verbatim (no shortening, no repair); an empty answer
gives no enrichment for that passage (index text = passage text only). The finish_reason is logged; an answer cut
off (MAX_TOKENS) is kept as it is and counted in the report.

```text
/no_think
You help a search engine connect EU law with business processes.

Below is one passage of EU law. Write 1 or 2 short sentences in plain business language that say when this passage
applies in a business process: which kind of business, which step or situation (for example taking an order, sending
an invoice, paying a supplier, delivering goods, handling a return, collecting customer data), and who is involved.

Rules:
- Use everyday business words, not legal terms. Do not name directives, articles or numbers.
- Say only what the passage supports. Do not add obligations that are not in the passage.
- Write only the 1 or 2 sentences. No list, no heading, no other text.

Passage:
{passage_text}
```

### 8.4 Selection rule

Decided on the 8 development variants (M1) and the 7 development cases (M2) **only**:

1. highest M1 wins;
2. tie → higher mean M2;
3. tie → simpler option, in the order E < F < G.

The winner replaces the current frozen retrieval (`data/retrieval_study2_corpus/frozen_retrieval_v2.json`) **only if
its M1 > 2/8**; the new freeze is a new file, the old one is kept. Otherwise the current freeze is kept unchanged.
The adequacy target M1 ≥ 5/8 is reported only. The 6 non-development cases (M2) are measured only after the freeze
decision, report only (as 7.6).

### 8.5 New held-out set

Before any RAG v3 run, 5 **new** variants of non-development cases (**03.2, 05.2, 10.1, 21.2, 46.2**) are drafted
(same format as 7.8: description, `variant.json` with accepted target ids, provisional reference) and approved by
Lina, in a file separate from the test set and from the old held-out set. They are **never** used for selection and
are measured **once**, after the freeze decision of 8.4: new held-out M1 = hits @5 out of 5. The old held-out set
(03.1, 05.1, 21.1, 37.1, 46.1; 0/5 in section 7) is re-measured once with the same setting and reported next to it.

### 8.6 Model calls

Any model call of RAG v3 (enrichment, embedding, reranking) needs the keyword **REAL RUN** in the run task. Tests use
mock LLM answers and fake embedding/reranker models only.

### 8.7 Fairness

The same retrieved passages, with their original text, go to C2 and C3. Only the knowledge block differs between
C1, C2 and C3.
