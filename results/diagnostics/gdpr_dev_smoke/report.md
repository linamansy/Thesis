# GDPR development smoke run (smoke_gdpr_dev)

Generator: BPMNGen harness + qwen3:8b (digest 500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41), Ollama 0.40.8. Retrieval: `data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json` (rerank). Cases: 01 06 11 13 17 19 45 (development only).
Smoke run: not part of any Study 1 or Study 2 result. Silver-based columns are provisional (AI-made).

## Per condition

| condition | n_cases | n_valid | n_di_stripped | n_bpmnlint_valid | n_fail_missing_namespace_rescued | n_fail_invalid_xml_other | n_fail_thinking_detected | mean_precision | mean_recall | mean_f1 | mean_behavioral_similarity | mean_n_generated_tasks | mean_n_extra_tasks | mean_n_extra_knowledge_traceable | mean_requirement_coverage | mean_precision_adjusted | mean_n_unjustified_knowledge_additions | mean_prompt_tokens | mean_output_tokens | auto_flows_added | n_fail_context_limit_hit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | 7 | 0 | 3 | 4 | 3 | 2 | 2 | 0.2381 | 0.1226 | 0.1609 | 0.1667 | 2.1429 | 0.8571 | 0.0 | 0.0 | 0.2381 | 0.0 | 1838.5714 | 3716.0 | 12 |  |
| C2 | 7 | 0 | 1 | 3 | 1 | 5 | 1 | 0.0571 | 0.0357 | 0.044 | 0.1429 | 0.7143 | 0.4286 | 0.0 | 0.0 | 0.0571 | 0.0 | 2488.0 | 4518.8571 | 0 |  |
| C3 | 7 | 0 | 3 | 4 | 3 | 2 | 1 | 0.1857 | 0.1334 | 0.1491 | 0.3333 | 3.8571 | 2.2857 | 0.0 | 0.0 | 0.1857 | 0.0 | 1881.5714 | 4682.7143 | 0 | 1.0 |

## Per case

| condition | case_id | valid | di_stripped | failure_type | n_generated_tasks | precision | recall | f1 | behavioral_similarity | n_extra_knowledge_traceable | requirement_coverage | prompt_tokens | output_tokens |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | 01 | False | True | missing_namespace_rescued | 3 | 0.3333 | 0.125 | 0.1818 |  | 0 |  | 1801 | 2203 |
| C1 | 06 | False | True | missing_namespace_rescued | 6 | 0.6667 | 0.4 | 0.5 | 0.8333 | 0 |  | 1804 | 4602 |
| C1 | 11 | False | True | missing_namespace_rescued | 6 | 0.6667 | 0.3333 | 0.4444 | 0.1667 | 0 | 0.0 | 1803 | 3771 |
| C1 | 13 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1809 | 1444 |
| C1 | 17 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1939 | 4472 |
| C1 | 19 | False | False | thinking_detected | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 1827 | 8214 |
| C1 | 45 | False | False | thinking_detected | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1887 | 1306 |
| C2 | 01 | False | True | missing_namespace_rescued | 5 | 0.4 | 0.25 | 0.3077 | 1.0 | 0 |  | 2227 | 2950 |
| C2 | 06 | False | False | thinking_detected | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 2469 | 6367 |
| C2 | 11 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 2364 | 1111 |
| C2 | 13 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 2783 | 1183 |
| C2 | 17 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 2906 | 11493 |
| C2 | 19 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 2248 | 1725 |
| C2 | 45 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 2419 | 6803 |
| C3 | 01 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1844 | 2726 |
| C3 | 06 | False | False | thinking_detected | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1847 | 1213 |
| C3 | 11 | False | True | missing_namespace_rescued | 5 | 0.6 | 0.25 | 0.3529 | 1.0 | 0 | 0.0 | 1846 | 2681 |
| C3 | 13 | False | True | missing_namespace_rescued | 10 | 0.2 | 0.2222 | 0.2105 | 1.0 | 0 |  | 1852 | 4253 |
| C3 | 17 | False | False | context_limit_hit | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |  | 1982 | 14723 |
| C3 | 19 | False | False | invalid_xml_other | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0 | 0.0 | 1870 | 2478 |
| C3 | 45 | False | True | missing_namespace_rescued | 12 | 0.5 | 0.4615 | 0.48 | 0.3333 | 0 |  | 1930 | 4705 |

## inputString length (limit 30000 characters) and prompt tokens (limit 13107 = 80% of num_ctx)

| condition | case_id | input_string_chars | max_chars | chars_ok | prompt_tokens | max_prompt_tokens | tokens_ok |
|---|---|---|---|---|---|---|---|
| C1 | 01 | 673 | 30000 | True | 1801 | 13107 | True |
| C1 | 06 | 673 | 30000 | True | 1804 | 13107 | True |
| C1 | 11 | 700 | 30000 | True | 1803 | 13107 | True |
| C1 | 13 | 732 | 30000 | True | 1809 | 13107 | True |
| C1 | 17 | 1422 | 30000 | True | 1939 | 13107 | True |
| C1 | 19 | 748 | 30000 | True | 1827 | 13107 | True |
| C1 | 45 | 1099 | 30000 | True | 1887 | 13107 | True |
| C2 | 01 | 2601 | 30000 | True | 2227 | 13107 | True |
| C2 | 06 | 3931 | 30000 | True | 2469 | 13107 | True |
| C2 | 11 | 3314 | 30000 | True | 2364 | 13107 | True |
| C2 | 13 | 5496 | 30000 | True | 2783 | 13107 | True |
| C2 | 17 | 6220 | 30000 | True | 2906 | 13107 | True |
| C2 | 19 | 2591 | 30000 | True | 2248 | 13107 | True |
| C2 | 45 | 3500 | 30000 | True | 2419 | 13107 | True |
| C3 | 01 | 851 | 30000 | True | 1844 | 13107 | True |
| C3 | 06 | 851 | 30000 | True | 1847 | 13107 | True |
| C3 | 11 | 878 | 30000 | True | 1846 | 13107 | True |
| C3 | 13 | 910 | 30000 | True | 1852 | 13107 | True |
| C3 | 17 | 1600 | 30000 | True | 1982 | 13107 | True |
| C3 | 19 | 926 | 30000 | True | 1870 | 13107 | True |
| C3 | 45 | 1277 | 30000 | True | 1930 | 13107 | True |

## C3 mediation (agents v1)

```json
{
  "run_id": "smoke_gdpr_dev",
  "cases": [
    "01",
    "06",
    "11",
    "13",
    "17",
    "19",
    "45"
  ],
  "n_passages": 35,
  "passages_per_label": {
    "Applicable": 0,
    "Indeterminate": 0,
    "Not applicable": 0,
    "Irrelevant": 35,
    "Mediation failed": 0
  },
  "applicability_resolver": {
    "conditions_checked": 0,
    "downgraded": 0,
    "downgraded_quote_not_found": 0,
    "downgraded_no_quote": 0
  },
  "relevance_evidence_checker": {
    "process_quotes_checked": 35,
    "process_quotes_not_found": 5
  }
}
```
