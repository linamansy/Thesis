# Mediation test, development set

docs/MEDIATION_TEST_CRITERIA.md (commit e01ef1c). C3 v2 agents only, qwen3:8b, no BPMN generation.

## T1-T5

| measure | result | target |
|---|---|---|
| T1 target hit (O) | 1/8 | >= 6/8 |
| T2 control (O) | 8/8 | >= 7/8 |
| T3 wrong Applicables, base cases (R + O) | 0 | 0 |
| T3 wrong Applicables per setting/role | {'R_variant': 0, 'R_base': 0, 'O_variant': 0, 'O_base': 0} | - |
| T4 drop rate (R) | 1.0 (80 of 80 not passed on) | none |
| T5 requirement code checks (O, T1 hits) | 0/1 pass (step_quote in description: 1/1) | all pass |

## Per variant

| variant | target | O: variant label (+ quote from added text) | O: base label | R: Applicables (variant / base) | drop rate R (variant / base) |
|---|---|---|---|---|---|
| 01.1 | GDPR-Art13-1 | Applicable (S1: "the sales staff write down the customer's name, phone number and email address and store them in the system"; C1: "the sales staff write down the customer's name, phone number and email address and store them in the system") | Indeterminate | - / - | 1.0 / 1.0 |
| 01.2 | LPD-Art3-1 | Indeterminate (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 06.1 | CRD-Art13-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |
| 11.1 | GDPR-Art17-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |
| 13.1 | SGD-Art14-1 | Indeterminate (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 17.1 | CRD-Art14-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |
| 19.1 | ECD-Art11-1 | Not applicable (no quote from added text) | Not applicable | - / - | 1.0 / 1.0 |
| 45.1 | ECD-Art10-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |

## Wrong Applicables (T3)

none

## Misses (automatic box naming from the audit trail; checked by reading)

- T5 01.1 GDPR-Art13-1: requirement
- T1 01.2 LPD-Art3-1: check-IF (S1 not_stated, first look; scope item); check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look); check-IF (D2 not_stated, first look; role_fact item)
- T1 06.1 CRD-Art13-1: check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look)
- T1 11.1 GDPR-Art17-1: quote check (S1: model said confirmed, quote not found); check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look); check-IF (C3 not_stated, second look); check-IF (C4 not_stated, second look); check-IF (C5 not_stated, second look)
- T1 13.1 SGD-Art14-1: check-IF (S1 not_stated, first look; scope item); quote check (C1: model said confirmed, quote not found); check-IF (T1 not_stated, first look; role_fact item)
- T1 17.1 CRD-Art14-1: check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look); check-IF (C3 not_stated, second look); quote check (T1: model said confirmed, quote not found)
- T1 19.1 ECD-Art11-1: split + scope/role rule (R1 contradicted: split named public body); check-IF (S1 not_stated, first look; scope item)
- T1 45.1 ECD-Art10-1: check-IF (S1 not_stated, first look; scope item)

## T5 requirements (target hits)

- 01.1 GDPR-Art13-1: "When the customer's details are collected, the company tells the customer about its identity, contact info, and why it's collecting the data." (22 words; triggers kept True; step_quote "During the inquiry, the sales staff write down the customer's name, phone number and email address and store them in the system" in passage False, in description True)
