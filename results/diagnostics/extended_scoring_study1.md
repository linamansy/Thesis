# Extended-reference scoring, Study 1 (PROVISIONAL until the Study 2 analysis-plan addendum is committed)

Reference = PMo tasks + required steps of rules the silver annotator labelled applicable (src/extended_scoring.py). A NEW, separate output: evaluation.csv, the summaries and the statistics are unchanged. Values are means over all cases and repetitions (n per condition below).

| Condition | n | precision (old) | extended precision | recall (old) | PMo recall | cases with expected requirements | requirement coverage | over-application (sum) | over-application (mean) |
|---|---|---|---|---|---|---|---|---|---|
| C1 | 39 | 0.2685 | 0.2685 | 0.1894 | 0.1894 | 0 | not defined | 1 | 0.0256 |
| C2 | 39 | 0.1801 | 0.1801 | 0.1304 | 0.1304 | 0 | not defined | 2 | 0.0513 |
| C3 | 39 | 0.1429 | 0.1429 | 0.0902 | 0.0902 | 0 | not defined | 0 | 0.0000 |

- Rows with at least one expected requirement: 0 of 117.
- Rows where extended precision = old precision: 117 of 117; PMo recall = old recall: 117 of 117.
- With no applicable rule the extended reference is the PMo model, so both must be equal there.
- Over-application: extra tasks law-traceable to a rule NOT labelled applicable (trace check, threshold from config). The silver labels are AI-made and provisional.
