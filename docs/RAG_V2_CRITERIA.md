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
