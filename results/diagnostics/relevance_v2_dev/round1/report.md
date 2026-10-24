# RelevanceAgent v2, development round 1

Silver is AI-made and provisional: these numbers are agreement with a stronger model, not correctness.

## consumer_law

| silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|
| applicable | 0 | 0 | 0 | 0 |
| indeterminate | 27 | 6 | 15 | 18 |
| not_applicable | 1 | 0 | 1 | 0 |
| irrelevant | 5 | 26 | 2 | 29 |

- v2: silver-relevant found 28/34 (recall 0.8235); silver-irrelevant called relevant 5/31 (specificity 0.8387)
- v1: silver-relevant found 16/34 (recall 0.4706); silver-irrelevant called relevant 2/31 (specificity 0.9355)
- quotes failed the code check: 0/98 (law_quote 0, description_quote 0); valid JSON 65/65

## gdpr

| silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|
| applicable | 2 | 1 | 0 | 3 |
| indeterminate | 9 | 8 | 0 | 17 |
| not_applicable | 2 | 4 | 0 | 6 |
| irrelevant | 3 | 6 | 0 | 9 |

- v2: silver-relevant found 13/26 (recall 0.5); silver-irrelevant called relevant 3/9 (specificity 0.6667)
- v1: silver-relevant found 0/26 (recall 0.0); silver-irrelevant called relevant 0/9 (specificity 1.0)
- quotes failed the code check: 1/52 (law_quote 0, description_quote 1); valid JSON 35/35

## Success criteria (section 2.3)

Overall quotes: 149/150 found (evidence 0.9933); valid JSON 100/100 (stability 1.0)

| criterion | met |
|---|---|
| 1_recall_consumer_law | yes |
| 2_specificity_consumer_law | yes |
| 1_recall_gdpr | no |
| 2_specificity_gdpr | yes |
| 3_generality | no |
| 4_evidence | yes |
| 5_stability | yes |
