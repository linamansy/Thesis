# Mediation test, held-out set (measured once, report only)

docs/MEDIATION_TEST_CRITERIA.md (commit e01ef1c). C3 v2 agents only, qwen3:8b, no BPMN generation.

## T1-T5

| measure | result | target |
|---|---|---|
| T1 target hit (O) | 0/10 | none (report only) |
| T2 control (O) | 10/10 | none (report only) |
| T3 wrong Applicables, base cases (R + O) | 0 | none (report only) |
| T3 wrong Applicables per setting/role | {'R_variant': 1, 'R_base': 0, 'O_variant': 1, 'O_base': 0} | - |
| T4 drop rate (R) | 0.99 (99 of 100 not passed on) | none |
| T5 requirement code checks (O, T1 hits) | 0/0 pass (step_quote in description: 0/0) | none (report only) |

## Per variant

| variant | target | O: variant label (+ quote from added text) | O: base label | R: Applicables (variant / base) | drop rate R (variant / base) |
|---|---|---|---|---|---|
| 03.1 | LPD-Art3-1 | Not applicable (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 05.1 | LPD-Art3-3 | Not applicable (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |
| 21.1 | GDPR-Art14-1 | Irrelevant (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 37.1 | CRD-Art9-1 | Irrelevant (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 46.1 | LPD-Art6-1 | Irrelevant (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 03.2 | LPD-Art3-4 | Not applicable (no quote from added text) | Not applicable | - / - | 1.0 / 1.0 |
| 05.2 | LPD-Art3-5 | Not applicable (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |
| 10.1 | GDPR-Art28-3-a | Not applicable (no quote from added text) | Irrelevant | GDPR-Art32-1 / - | 0.8 / 1.0 |
| 21.2 | CRD-Art18-1 | Indeterminate (no quote from added text) | Indeterminate | - / - | 1.0 / 1.0 |
| 46.2 | SGD-Art14-2 | Indeterminate (no quote from added text) | Irrelevant | - / - | 1.0 / 1.0 |

## Wrong Applicables (T3)

- R / variant 10.1 (variant 10.1): GDPR-Art32-1 - S1 "The requested software is an online service run by an outside provider. It keeps the names, e-mail addresses and working hours of the department's staff on that provider's servers."; C1 "The requested software is an online service run by an outside provider. It keeps the names, e-mail addresses and working hours of the department's staff on that provider's servers."
- O / variant 10.1 (variant 10.1): GDPR-Art32-1 - S1 "The requested software is an online service run by an outside provider. It keeps the names, e-mail addresses and working hours of the department's staff on that provider's servers."; C1 "The requested software is an online service run by an outside provider. It keeps the names, e-mail addresses and working hours of the department's staff on that provider's servers."

## Misses (automatic box naming from the audit trail; checked by reading)

- T1 03.1 LPD-Art3-1: check-IF (S1 not_stated, first look; scope item); check-IF (C1 not_stated, first look); check-IF (C2 not_stated, first look); check-IF (D2 contradicted, first look; role_fact item)
- T1 05.1 LPD-Art3-3: check-IF (S1 not_stated, first look; scope item); check-IF (C1 not_stated, first look); check-IF (D2 contradicted, first look; role_fact item)
- T1 21.1 GDPR-Art14-1: relevance
- T1 37.1 CRD-Art9-1: relevance
- T1 46.1 LPD-Art6-1: relevance
- T1 03.2 LPD-Art3-4: split + scope/role rule (R1 contradicted: split named public body); check-IF (S1 not_stated, first look; scope item); check-IF (C2 not_stated, first look)
- T1 05.2 LPD-Art3-5: split + scope/role rule (R1 contradicted: split named public body); check-IF (S1 not_stated, first look; scope item); check-IF (C1 contradicted, first look)
- T1 10.1 GDPR-Art28-3-a: split + scope/role rule (R1 contradicted: split named processor); check-IF (C1 not_stated, first look); check-IF (P1 not_stated, first look; role_fact item)
- T1 21.2 CRD-Art18-1: check-IF (S1 not_stated, first look; scope item)
- T1 46.2 SGD-Art14-2: check-IF (S1 not_stated, first look; scope item); check-IF (T1 not_stated, first look; role_fact item)

## T5 requirements (target hits)

