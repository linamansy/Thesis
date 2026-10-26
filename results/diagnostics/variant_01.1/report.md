# Variant 01.1 and oracle diagnostic

Expected step: "Inform customer about how their contact details will be used" (01.1 reference Task_9, PROVISIONAL; label match at threshold 0.75). Target passage: GDPR-Art13-1.

| run | passages given | XML valid | auto-repairs | Art13-1 in prompt? | expected step present? |
|---|---|---|---|---|---|
| variant_01.1/C1/01 | none | no | auto_flows_added=0, auto_links_added=1, first_task_inserted=False | no | no |
| variant_01.1/C2/01.1 | GDPR-Art35-9, GDPR-Art7-4, GDPR-Art30-2, GDPR-Art12-6, GDPR-Art13-3 | no | auto_flows_added=0, auto_links_added=0, first_task_inserted=False | no | n/a (no scorable model) |
| variant_01.1/C3/01.1 | GDPR-Art35-9, GDPR-Art7-4, GDPR-Art30-2, GDPR-Art12-6, GDPR-Art13-3 | no | auto_flows_added=0, auto_links_added=1, first_task_inserted=False | no | n/a (no scorable model) |
| oracle_01.1/C2/01.1 | GDPR-Art35-9, GDPR-Art7-4, GDPR-Art30-2, GDPR-Art12-6, GDPR-Art13-1 | no | auto_flows_added=0, auto_links_added=0, first_task_inserted=False | yes | no |
| oracle_01.1/C3/01.1 | GDPR-Art35-9, GDPR-Art7-4, GDPR-Art30-2, GDPR-Art12-6, GDPR-Art13-1 | no | auto_flows_added=0, auto_links_added=1, first_task_inserted=False | yes | no |

## variant_01.1/C3/01.1

| passage | label | look |
|---|---|---|
| GDPR-Art35-9 | Split invalid | first |
| GDPR-Art7-4 | Indeterminate | second |
| GDPR-Art30-2 | Split invalid | first |
| GDPR-Art12-6 | Indeterminate | second |
| GDPR-Art13-3 | Indeterminate | second |

C3 block:

```
No domain knowledge provided.
```

## oracle_01.1/C3/01.1

| passage | label | look |
|---|---|---|
| GDPR-Art35-9 | Split invalid | first |
| GDPR-Art7-4 | Indeterminate | second |
| GDPR-Art30-2 | Split invalid | first |
| GDPR-Art12-6 | Indeterminate | second |
| GDPR-Art13-1 | Applicable | first |

C3 block:

```
REQUIREMENTS
These rules were checked and apply to this process.
- [GDPR-Art13-1] At the time when personal data are obtained during the inquiry, the controller shall provide the data subject with all of the following information: (a) the identity and the contact details of the controller and, where applicable, of the controller's representative; (b) the contact details of the data protection officer, where applicable; (c) the purposes of the processing for which the personal data are intended as well as the legal basis for the processing; (d) where the processing is based on point (f) of Article 6(1), the legitimate interests pursued by the controller or by a third party; (e) the recipients or categories of recipients of the personal data, if any; (f) where applicable, the fact that the controller intends to transfer personal data to a third country or international organisation and the existence or absence of an adequacy decision by the Commission, or in the case of transfers referred to in Article 46 or 47, or the second subparagraph of Article 49(1), reference to the appropriate or suitable safeguards and the means by which to obtain a copy of them or where they have been made available.
```
