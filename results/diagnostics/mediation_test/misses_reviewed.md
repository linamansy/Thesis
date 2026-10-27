# Mediation test: every miss, failing box checked by reading the audit trail

Criteria: docs/MEDIATION_TEST_CRITERIA.md (e01ef1c). Audit trails: `<group>/answers.json`, summaries in
`<group>/metrics.json` (misses[].trail). **No bug found**: in every case the code applied R1–R6 to the statuses it
received (labels follow R4; R1 derived by R3; quote checks reject changed or invented words). Nothing was changed.

## Development (T1 misses 7/8)

| variant | target | label | failing box | evidence |
|---|---|---|---|---|
| 01.2 | LPD-Art3-1 | Indeterminate | check-IF | S1 (commercial transaction) and D2 (another undertaking pays the organisation) not_stated, although added text says "Most customers are other companies ... the company sends them a bill"; C1/C2 not_stated after the second look |
| 06.1 | CRD-Art13-1 | Indeterminate | check-IF (second look) | R1, S1, T1 confirmed ("The shop sells kitchen items to private persons across the EU."); C1 "the consumer withdraws from the contract" and C2 not_stated, although added text says customers "change their mind ... and send it back" |
| 11.1 | GDPR-Art17-1 | Indeterminate | split (+ quote check) | split lists the six alternative grounds of Art. 17(1) as six IF items that must all hold (R1 = every situational condition), so the rule cannot be confirmed; C6 confirmed with an added-text quote. S1 downgraded: model quoted "the process begins when ..." (text: "This process begins ...") |
| 13.1 | SGD-Art14-1 | Indeterminate | check-IF + quote check | S1 and T1 not_stated although "private persons whose kitchen appliance stopped working a few months after purchase"; C1 quote copied from the item text, not the description -> downgraded |
| 17.1 | CRD-Art14-1 | Indeterminate | check-IF (second look) | R1 confirmed (consumer via S1 "The customers are private persons ..."); C1 withdrawal communicated, C2, C3 not_stated; T1 quote copied from the item text -> downgraded |
| 19.1 | ECD-Art11-1 | Not applicable | split -> role rule | split named roles ["public body"] ("Member States shall ensure ... the service provider ...") -> R1 contradicted by R3; S1 also not_stated |
| 45.1 | ECD-Art10-1 | Indeterminate | check-IF (scope) | everything confirmed except S1 "the service is an information society service"; R5: S1 is not looked at again in the second look |

T5 miss 01.1 (GDPR-Art13-1): the requirement passed every code check of RequirementCheckerV2 (22 words, trigger
"at the time when personal data are obtained" kept as "When the customer's details are collected", step_quote found
in the description). It fails only the criteria wording "step_quote verbatim in the **passage**": R6 and the code ask
for a step_quote from the **description**, so it can never be in the law passage. Reported literally (0/1) and with the
code check (1/1); the criteria are not changed.

## Held-out (report only, measured once; T1 misses 10/10)

| variant | target | label | failing box | evidence |
|---|---|---|---|---|
| 03.1 | LPD-Art3-1 | Not applicable | split -> role rule | split named "creditor"; D2 contradicted with a checked quote (the organisation pays its suppliers, it is the debtor) -> creditor contradicted (R3) |
| 05.1 | LPD-Art3-3 | Not applicable | split -> role rule | same as 03.1 (creditor; D2 contradicted) |
| 21.1 | GDPR-Art14-1 | Irrelevant | relevance | model: "the process description does not mention" data not obtained from the data subject |
| 37.1 | CRD-Art9-1 | Irrelevant | relevance (quote check) | model said relevant (withdrawal after changing one's mind) but its law_quote was not found in the passage |
| 46.1 | LPD-Art6-1 | Irrelevant | relevance | model: recovery costs "not mentioned or implied" |
| 03.2 | LPD-Art3-4 | Not applicable | split -> role rule | split named ["public body"] -> R1 contradicted |
| 05.2 | LPD-Art3-5 | Not applicable | split -> role rule (+ check-IF) | split named ["public body"]; C1 also contradicted ("its bills will be settled four months after they arrive") |
| 10.1 | GDPR-Art28-3-a | Not applicable | split -> role rule | split named ["processor"]; P1 not confirmed -> processor contradicted (A1: the organisation is the controller) |
| 21.2 | CRD-Art18-1 | Indeterminate | check-IF (scope) | S1 "the buyer is a consumer" not_stated |
| 46.2 | SGD-Art14-2 | Indeterminate | check-IF | S1 and T1 not_stated |

Wrong Applicable (T3, variant only, R and O): 10.1 GDPR-Art32-1. Split roles [controller, processor], one IF item
"processing of personal data"; R1 confirmed by A1 (controller), S1 and C1 confirmed with the quote "The requested
software is an online service run by an outside provider. It keeps the names, e-mail addresses and working hours of the
department's staff on that provider's servers." Requirement: "The outside provider must encrypt the staff's names,
e-mail addresses and working hours stored on its servers." (puts the duty on the provider, not the organisation).
Boxes: split (a generic IF item) + requirement (actor). The code followed R1–R6.
