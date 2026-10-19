# Harness checks (Study 1)

Read-only check of `results/runs/ollama_rep{1,2,3}/<condition>/<case>/bpmngen/meta.json` and `raw_model_output.txt` (smoke runs excluded; `C3/mediation` is not a case). Nothing was changed.

| Condition | runs read | (1) first_task_inserted = true | (2) raw output contains "boundaryEvent" | (3) fits_context = false or done_reason != "stop" |
|---|---|---|---|---|
| C1 | 39 | 0 | 0 | 0 |
| C2 | 39 | 0 | 0 | 0 |
| C3 | 39 | 0 | 0 | 0 |

Missing meta.json or raw_model_output.txt: 0

## Flagged runs

- none
