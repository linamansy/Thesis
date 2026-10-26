# RelevanceAgent v2, development round 2

Silver is AI-made and provisional: these numbers are agreement with a stronger model, not correctness.

## consumer_law

| silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|
| applicable | 0 | 0 | 0 | 0 |
| indeterminate | 23 | 10 | 15 | 18 |
| not_applicable | 1 | 0 | 1 | 0 |
| irrelevant | 8 | 23 | 2 | 29 |

- v2: silver-relevant found 24/34 (recall 0.7059); silver-irrelevant called relevant 8/31 (specificity 0.7419)
- v1: silver-relevant found 16/34 (recall 0.4706); silver-irrelevant called relevant 2/31 (specificity 0.9355)
- quotes failed the code check: 3/98 (law_quote 3, description_quote 0); valid JSON 65/65

## gdpr

| silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|
| applicable | 2 | 1 | 0 | 3 |
| indeterminate | 8 | 9 | 0 | 17 |
| not_applicable | 2 | 4 | 0 | 6 |
| irrelevant | 4 | 5 | 0 | 9 |

- v2: silver-relevant found 12/26 (recall 0.4615); silver-irrelevant called relevant 4/9 (specificity 0.5556)
- v1: silver-relevant found 0/26 (recall 0.0); silver-irrelevant called relevant 0/9 (specificity 1.0)
- quotes failed the code check: 2/51 (law_quote 2, description_quote 0); valid JSON 35/35

## Success criteria (section 2.3)

Overall quotes: 144/149 found (evidence 0.9664); valid JSON 100/100 (stability 1.0)

| criterion | met |
|---|---|
| 1_recall_consumer_law | yes |
| 2_specificity_consumer_law | yes |
| 1_recall_gdpr | no |
| 2_specificity_gdpr | yes |
| 3_generality | no |
| 4_evidence | yes |
| 5_stability | yes |
