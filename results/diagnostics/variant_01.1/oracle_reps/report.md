# Oracle runs on 01.1, repetitions 1-3

Expected step: "Inform customer about how their contact details will be used" (01.1 reference Task_9, PROVISIONAL; label match at threshold 0.75).

| run | rep | XML valid | scorable (di_stripped rule) | expected step present | closest task label + similarity | C3 block identical to rep 1? |
|---|---|---|---|---|---|---|
| oracle_01.1/C2/01.1 | 1 | no | yes (di_stripped) | no | "Collect Information" (0.45) | - |
| oracle_01.1_rep2/C2/01.1 | 2 | no | yes (di_stripped) | no | "Collect Information" (0.45) | - |
| oracle_01.1_rep3/C2/01.1 | 3 | no | no | n/a (no scorable model) | n/a | - |
| after_round3_oracle/C3/01.1 | 1 | no | no | n/a (no scorable model) | n/a | yes |
| oracle_01.1_rep2/C3/01.1 | 2 | no | no | n/a (no scorable model) | n/a | yes |
| oracle_01.1_rep3/C3/01.1 | 3 | no | yes (di_stripped) | no | "Collect Customer Details" (0.73) | yes |
