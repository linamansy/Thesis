# Mediation test, development set

docs/MEDIATION_TEST_CRITERIA.md (commit e01ef1c). C3 v2 agents only, qwen/qwen3.8-27b on Groq, no BPMN generation.

## T1-T5

| measure | result | target |
|---|---|---|
| T1 target hit (O) | 2/8 | >= 6/8 |
| T2 control (O) | 7/8 | >= 7/8 |
| T3 wrong Applicables, base cases (R + O) | 0 | 0 |
| T3 wrong Applicables per setting/role | {'R_variant': 0, 'R_base': 0, 'O_variant': 0, 'O_base': 0} | - |
| T4 drop rate (R) | None (0 of 0 not passed on) | none |
| T5 requirement code checks (O, T1 hits) | 0/2 pass (step_quote in description: 2/2) | all pass |

## Per variant

| variant | target | O: variant label (+ quote from added text) | O: base label | R: Applicables (variant / base) | drop rate R (variant / base) |
|---|---|---|---|---|---|
| 01.1 | GDPR-Art13-1 | Applicable (S1: "the sales staff write down the customer's name, phone number and email address"; C1: "the sales staff write down the customer's name, phone number and email address") | Applicable | - / - | None / None |
| 01.2 | LPD-Art3-1 | Not applicable (no quote from added text) | Irrelevant | - / - | None / None |
| 06.1 | CRD-Art13-1 | Indeterminate (no quote from added text) | Irrelevant | - / - | None / None |
| 11.1 | GDPR-Art17-1 | Indeterminate (no quote from added text) | Irrelevant | - / - | None / None |
| 13.1 | SGD-Art14-1 | Applicable (S1: "Most complaints come from private persons whose kitchen appliance stopped working a few months after purchase.") | Irrelevant | - / - | None / None |
| 17.1 | CRD-Art14-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | None / None |
| 19.1 | ECD-Art11-1 | Irrelevant (no quote from added text) | Irrelevant | - / - | None / None |
| 45.1 | ECD-Art10-1 | Irrelevant (no quote from added text) | Irrelevant | - / - | None / None |

## Wrong Applicables (T3)

none

## Misses (automatic box naming from the audit trail; checked by reading)

- T5 01.1 GDPR-Art13-1: requirement
- T2 01 GDPR-Art13-1: check-IF / scope/role rule (Applicable without the added sentences)
- T1 01.2 LPD-Art3-1: split + scope/role rule (R1 contradicted: split named public body)
- T1 06.1 CRD-Art13-1: check-IF (C1 not_stated, second look)
- T1 11.1 GDPR-Art17-1: check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look); check-IF (C3 not_stated, second look); check-IF (C4 not_stated, second look); check-IF (C5 not_stated, second look); check-IF (C6 not_stated, second look)
- T5 13.1 SGD-Art14-1: requirement
- T1 17.1 CRD-Art14-1: check-IF (C1 not_stated, second look); check-IF (C2 not_stated, second look); check-IF (C4 not_stated, second look); check-IF (C5 not_stated, second look)
- T1 19.1 ECD-Art11-1: relevance
- T1 45.1 ECD-Art10-1: relevance

## T5 requirements (target hits)

- 01.1 GDPR-Art13-1: "When the sales staff write down the customer's name, phone number and email address, the customer is told the company's identity and contact details, the purposes and legal basis for processing, and other required details." (35 words; triggers kept True; step_quote "the sales staff write down the customer's name, phone number and email address and store them in the system" in passage False, in description True)
- 13.1 SGD-Art14-1: "When customers ask for the appliance to be fixed or swapped, the repair or replacement is done free of charge, within a reasonable time, and without significant inconvenience." (28 words; triggers kept True; step_quote "These customers usually ask for the appliance to be fixed or swapped for a new one." in passage False, in description True)
