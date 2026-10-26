# C3 v2 development

This file records why a second version of the C3 mediation agents (v2) is developed and the rules for developing it.
The rules in section 2 are fixed on 21 Oct 2026, **before** any v2 change is made. C3 v1 (Study 1, git tag
`c3-v1-study1`, `config.yaml` `c3_version: v1`) stays unchanged and its results are not rerun or replaced.

No code, prompt or config was changed when this file was written.

---

## 1. Two problems of the Study 1 agents (v1)

Evidence is quoted from `results/runs/ollama_rep1/C3/mediation/11.json` (case 11, a subscription service).
The mediation agents run at temperature 0 with seed 42, so repetitions 2 and 3 give the same labels for case 11
(checked: identical in `ollama_rep2` and `ollama_rep3`); they confirm the problem is stable, not that it is
independent evidence.

Case 11 description (`data/cases/11`):

> This process begins when a customer signs up for a subscription service, entering personal and payment information.
> The system generates an account, assigns access, and triggers automated billing cycles.
> Throughout the subscription, the customer receives regular updates, product enhancements, or renewal notifications.
> If the customer decides to cancel, they submit a cancellation request, which the support team processes.
> Depending on the terms, any refunds or charges are applied.
> The process concludes when the subscription is deactivated by the support team and the final account balance is settled.

Overall picture in repetition 1: of the 65 passages (13 cases × 5), the agents labelled 47 Irrelevant, 18
Indeterminate and **0 Applicable**. So the RequirementAgent never ran and no C3 block contained a requirement.
The two problems below explain much of this.

### Problem 1: RelevanceAgent rejects a relevant passage (CRD-Art14-4)

CRD-Art14-4 ("Obligations of the consumer in the event of withdrawal") is about what a consumer must not pay for
when they withdraw from a service contract. Case 11 is a consumer subscription service with a cancellation step,
so the passage is on topic. The RelevanceAgent judged it irrelevant:

```json
"passage_id": "CRD-Art14-4",
"label": "Irrelevant",
"relevance": {
  "relevant": false,
  "reason": "The legal passage discusses consumer rights related to withdrawal from services and digital content, while the process description focuses on subscription management, billing, and cancellation. The topics do not align.",
  "evidence_process": "If the customer decides to cancel, they submit a cancellation request, which the support team processes.",
  "evidence_passage": "The consumer shall bear no cost for: (a) the performance of services or the supply of water, gas or electricity, ..."
}
```

- The agent's own evidence quote (the cancellation request) is the step the passage is about, yet its reason
  says the topics "do not align". It treats "withdrawal" and "cancellation" as different topics.
- Because the passage is marked Irrelevant, it stops here: it is not passed to the ApplicabilityAgent and does not
  appear in the C3 block, not even as an Indeterminate rule.
- For comparison only (silver is AI-made, not gold): the silver annotator labels CRD-Art14-4 for case 11
  `indeterminate`, i.e. on topic but with unconfirmed facts ("The passage deals with consumer withdrawal rights for
  services and digital content, which matches the subscription service context, ...").

The same pattern is visible for CRD-Art8-7 in case 11 (confirmation of a distance contract, judged irrelevant
because the description "focuses on subscription management, billing cycles, and cancellation procedures").

### Problem 2: ApplicabilityAgent lists obligations as conditions (CRD-Art6-1-e, CRD-Art6-1-l)

A rule has two parts: **conditions** (when does it apply? e.g. "a distance contract with a consumer") and
**obligations** (what must then be done? e.g. "the trader shall provide the total price"). Only conditions should be
checked against the description. The v1 ApplicabilityAgent mixes them.

**CRD-Art6-1-e** (label Indeterminate), conditions as produced by the agent:

```json
{"condition": "the trader shall provide the consumer with the total price of the goods or services inclusive of taxes", "status": "not_stated", "evidence": null},
{"condition": "the nature of the goods or services is such that the price cannot reasonably be calculated in advance", "status": "not_stated", "evidence": null},
{"condition": "the total price shall include the total costs per billing period", "status": "not_stated", "evidence": null},
{"condition": "where such contracts are charged at a fixed rate, the total price shall also mean the total monthly costs", "status": "not_stated", "evidence": null},
{"condition": "the manner in which the price is to be calculated shall be provided", "status": "not_stated", "evidence": null},
{"condition": "the cost of using the means of distance communication for the conclusion of the contract where that cost is calculated other than at the basic rate", "status": "not_stated", "evidence": null}
```

- "the trader shall provide ...", "the total price shall include ...", "... shall be provided" are obligations
  (what the trader must do), not conditions.
- The real conditions of the passage are missing: the customer is a consumer, and the contract is a distance or
  off-premises contract ("Before the consumer is bound by a distance or off-premises contract ...").
- The one condition the description does state, a contract containing a subscription ("signs up for a subscription
  service"), is not listed. (The silver annotator lists it as `stated_true`.)

**CRD-Art6-1-l** (label Indeterminate): the agent gives 10 conditions. Only the first is a real condition
("the contract is a distance or off-premises contract"). The other 9 are items of information the trader must give,
e.g.:

```json
{"condition": "the trader provides the consumer with information in a clear and comprehensible manner", "status": "not_stated", "evidence": null},
{"condition": "a reminder of the existence of a legal guarantee of conformity for goods", "status": "not_stated", "evidence": null},
{"condition": "the duration of the contract or the conditions for terminating the contract if the contract is of indeterminate duration or is to be extended automatically", "status": "not_stated", "evidence": null}
```

**Why this matters.** A process description that needs a legal rule usually does *not* already contain the step the
rule demands; that is why the rule is useful. If the obligation is checked as a condition, it is almost always
`not_stated`, so under the combination rule (all satisfied → Applicable) the rule can never become Applicable, and the
RequirementAgent never runs. The C3 block also shows the obligations as "Unconfirmed" conditions, which describes the
rule incorrectly to the generator.

---

## 2. Rules for developing v2

Fixed on 21 Oct 2026, before any v2 change.

### 2.1 Development cases only
- v2 is developed and tried **only** on `cases.development_ids` in `config.yaml`
  (currently the 13 Study 1 cases: 01, 03, 05, 06, 10, 11, 13, 17, 19, 21, 37, 45, 46).
- No v2 prompt, schema or code may be run on, or tuned by looking at, any case in `cases.test_ids`.
- The reference BPMN is never given to any agent (unchanged rule).

### 2.2 At most 3 rounds of changes
- A round = one set of changes to the C3 agents (prompts, schemas, agent code, combination rule), followed by one run
  of the agents on the development cases and a check against the success criteria (2.3).
- At most 3 rounds. After round 3, v2 is frozen as it is, whether or not all criteria are met; unmet criteria are
  reported as a limitation.
- v2 may stop earlier if all criteria are met.
- The generator, retrieval, frozen passages, model (qwen3:8b, same digest) and agent settings (temperature 0, seed 42,
  num_ctx 16384, think off) do not change. Only the C3 mediation may change.

### 2.3 Success criteria (fixed now)

Written 24 Oct 2026 (criteria by Lina), committed **before round 1 starts** and before any v2 prompt, schema or code
exists or has been run. They may not be changed after round 1 has started.

Scope: these criteria are for the **relevance step** of v2 (RelevanceAgent v2). "Silver-relevant" = silver label
applicable, indeterminate or not_applicable; "silver-irrelevant" = silver label irrelevant.

1. **Recall:** v2 marks relevant at least **70%** of the silver-relevant passages.
2. **Specificity:** v2 marks irrelevant at least **50%** of the silver-irrelevant passages.
3. **Generality:** 1 and 2 must each pass separately on the consumer-law development cases AND on the GDPR
   development cases. Passing on only one law counts as a fail.
4. **Evidence:** at least **90%** of the law_quote and description_quote values pass the code check (quote found in the
   passage / in the description).
5. **Stability:** at least **95%** of the answers are valid JSON after the 1 retry.
6. **Stop rule:** at most 3 development rounds for relevance. If the criteria are still not met after round 3, the best
   round is kept and the shortfall is reported. The criteria are never changed after results are seen.
7. **Note:** silver is AI-made and provisional; these criteria measure agreement with a stronger model, not
   correctness.

Passages the criteria are computed on (development cases only, 5 frozen passages per case, from the existing silver
files; no test case):

| law | cases | frozen retrieval | silver file | applicable | indeterminate | not_applicable | irrelevant | total |
|---|---|---|---|---|---|---|---|---|
| consumer law (CRD + LPD) | 13 Study 1 cases | `data/retrieval/frozen_retrieval.json` | `data/silver/silver_reference.json` | 0 | 33 | 1 | 31 | 65 |
| GDPR (Chapters I-V) | 7 GDPR development cases | `data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json` | `data/silver_gdpr/silver_reference_dev.json` (rerank top 5 only) | 3 | 17 | 6 | 9 | 35 |

Thresholds in passages: consumer law recall >= 24 of 34 silver-relevant (70% of 34 = 23.8), specificity >= 16 of 31
silver-irrelevant (50% of 31 = 15.5); GDPR recall >= 19 of 26 (18.2), specificity >= 5 of 9 (4.5). Criteria 4 and 5
are computed over all answers of both laws together and also reported per law.

### 2.4 Logging of each round
Each round gets one entry in section 3 below, written on the day of the round, with:
- date and round number
- what was changed and why (linked to problem 1, problem 2 or a criterion), with the files changed
- git commit of the round
- the run folder of the round's agent outputs
- the result for each success criterion (met / not met, with the numbers)
- decision: next round, or freeze v2

---

## 3. Round log

### Round 1 (24 Oct 2026): RelevanceAgent v2

**What changed and why.** A new, general relevance step for any kind of law (Problem 1 of section 1; on GDPR, v1
called all 35 development passages Irrelevant, `results/runs/smoke_gdpr_dev/C3/mediation/`). v1 asked whether the
passage's *topic* matches the process, with a list of consumer-law topics. v2 asks whether a *step of the process
does what the rule applies to*: the model names the rule's trigger (law_trigger + law_quote copied from the passage)
and the process step that does it (process_step + description_quote copied from the description), with no topic
list, no law-specific words and one neutral made-up example. Code (no LLM) checks both quotes with the QuoteChecker;
the final label is relevant only if the model said true AND both quotes are found.
Files (new; the v1 files are unchanged and C3 v1 still matches its frozen hashes): `prompts/relevance_prompt_v2.txt`,
`src/agents/relevance_agent_v2.py`, `src/mediation/relevance_v2_checker.py`, `src/relevance_v2_dev.py`,
`tests/test_relevance_agent_v2.py`, `config.yaml` (`paths.relevance_prompt_v2`, `paths.relevance_v2_dev_dir`,
`c3_v2_dev`). Only the relevance step was run (no ApplicabilityAgent, no generator).

**Commit:** `4ff3ee8` (code, before the run). **Run folder:** `results/diagnostics/relevance_v2_dev/round1/`
(qwen3:8b digest `500a1f06…`, Ollama 0.40.8, temperature 0, seed 42, think off; development cases only:
13 consumer-law cases with `data/retrieval/frozen_retrieval.json`, 7 GDPR cases with the rerank file).

**Results** (silver is AI-made and provisional; agreement with a stronger model, not correctness):

| law | silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|---|
| consumer law | applicable | 0 | 0 | 0 | 0 |
| consumer law | indeterminate | 27 | 6 | 15 | 18 |
| consumer law | not_applicable | 1 | 0 | 1 | 0 |
| consumer law | irrelevant | 5 | 26 | 2 | 29 |
| GDPR | applicable | 2 | 1 | 0 | 3 |
| GDPR | indeterminate | 9 | 8 | 0 | 17 |
| GDPR | not_applicable | 2 | 4 | 0 | 6 |
| GDPR | irrelevant | 3 | 6 | 0 | 9 |

| criterion | consumer law | GDPR | met |
|---|---|---|---|
| 1 recall >= 70% | 28/34 = 82.4% (v1 16/34 = 47.1%) | **13/26 = 50.0%** (v1 0/26) | consumer yes, **GDPR no** |
| 2 specificity >= 50% | 26/31 = 83.9% (v1 29/31 = 93.5%) | 6/9 = 66.7% (v1 9/9) | yes, yes |
| 3 generality (1 and 2 on both laws) | | | **no** (GDPR recall) |
| 4 evidence >= 90% | 98/98 quotes found | 51/52 found | yes (149/150 = 99.3%) |
| 5 stability >= 95% | 65/65 valid JSON | 35/35 | yes (100/100, no retry needed) |

Silver-irrelevant passages called relevant by v2: consumer law 5 of 31, GDPR 3 of 9. Quotes failing the code check:
1 of 150 (a description_quote, GDPR case 11, GDPR-Art15-3).

Of the 13 GDPR silver-relevant passages v2 missed, 12 are the model's own "not relevant" and 1 is a failed quote.
The model's reasons name a narrow trigger (e.g. "a data subject makes a request", "rectifying inaccurate personal
data") that the description does not state, while silver labels the same passages on topic because the process
handles personal data. GDPR-Art16-1 (case 19, silver applicable) is one of the misses; GDPR-Art2-1 and GDPR-Art32-2
(case 11, silver applicable) are found.

**Decision:** pending. Round 1 does not meet all criteria (criterion 3 fails on GDPR recall). Per Lina's instruction,
the prompt is not changed after seeing these results; the next step (round 2 or freeze) is Lina's decision.

### Round 2 (24 Oct 2026): RelevanceAgent v2, broad relevance

**What changed and why.** Round 1 failed criterion 3 on GDPR recall (13/26): the model took the rule's specific
trigger event (e.g. "a data subject makes a request") and rejected passages whose event the description does not
state. Round 2 makes relevance a broad "is this rule about something this process does?" judgement: the prompt asks
for law_focus (what the rule is about, with an exact law_quote) and the step where that kind of activity happens
(process_step + description_quote), and says explicitly NOT to check IF conditions, trigger events, deadlines or
exceptions (left to the applicability stage) and not to mark a passage irrelevant only because a specific event or
condition is not described. New neutral example: "If a customer complains about a card payment, the shop must refund
within 14 days" / "The customer pays by card" -> relevant at the payment step. No topic list, no law-specific words.
Files: `prompts/relevance_prompt_v2.txt`; `src/agents/relevance_agent_v2.py` schema field law_trigger -> law_focus with
broad descriptions (the schema is pasted into the prompt; Lina chose to change it too); the test's mock answer. The
code quote check, the runner and the criteria are unchanged.

**Commit:** `b4de8cb` (before the run). **Run folder:** `results/diagnostics/relevance_v2_dev/round2/` (same model,
settings and development cases as round 1).

**Results** (silver is AI-made and provisional):

| law | silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |
|---|---|---|---|---|---|
| consumer law | applicable | 0 | 0 | 0 | 0 |
| consumer law | indeterminate | 23 | 10 | 15 | 18 |
| consumer law | not_applicable | 1 | 0 | 1 | 0 |
| consumer law | irrelevant | 8 | 23 | 2 | 29 |
| GDPR | applicable | 2 | 1 | 0 | 3 |
| GDPR | indeterminate | 8 | 9 | 0 | 17 |
| GDPR | not_applicable | 2 | 4 | 0 | 6 |
| GDPR | irrelevant | 4 | 5 | 0 | 9 |

| criterion | round 1 | round 2 | round 2 met |
|---|---|---|---|
| 1 recall, consumer law | 28/34 = 82.4% | 24/34 = 70.6% | yes (just) |
| 1 recall, GDPR | 13/26 = 50.0% | **12/26 = 46.2%** | **no** |
| 2 specificity, consumer law | 26/31 = 83.9% | 23/31 = 74.2% | yes |
| 2 specificity, GDPR | 6/9 = 66.7% | 5/9 = 55.6% | yes |
| 3 generality | no | **no** | **no** |
| 4 evidence | 149/150 = 99.3% | 144/149 = 96.6% (5 law_quotes failed) | yes |
| 5 stability | 100/100 | 100/100 | yes |

Round 1 vs round 2 per passage: consumer law, silver-relevant 24 relevant in both, 4 lost, 0 gained, 6 irrelevant in
both; silver-irrelevant 4 newly called relevant, 1 no longer. GDPR, silver-relevant 10 relevant in both, 3 lost, 2
gained, 11 irrelevant in both; silver-irrelevant 1 newly called relevant. All 14 GDPR misses of round 2 are the
model's own "not relevant" (no quote failure); its law_focus is still the rule's specific obligation or right (e.g.
"rectification of inaccurate personal data", "records of processing activities", "right of access by the data
subject"), and the reasons say the process "does not mention" that activity. GDPR-Art16-1 (case 19, silver
applicable) is still missed; GDPR-Art2-1 and GDPR-Art32-2 (case 11) are still found.

**Best round so far:** round 1 (higher recall on both laws, higher specificity on both, more quotes found). Neither
round meets criterion 3.

**Decision:** pending (Lina). The prompt is not changed after seeing these results. One round is left (rule 2.2 /
criterion 6: at most 3 rounds; after round 3 the best round is kept and the shortfall reported).

**Design decision recorded with round 2 (design only, nothing built yet).** C3 v2 has four boxes:
1. **RelevanceAgent** (this agent).
2. **ApplicabilityAgent**, with inside it: a **law-only IF/THEN split call** (the passage alone, no description: which
   parts are conditions (IF) and which are obligations (THEN); addresses Problem 2) -> a **check-IF call with quotes**
   (each IF condition against the description: satisfied / contradicted / not_stated, with an exact quote) -> the
   **code quote check** -> a **second-look call**. The split is its own law-only call and is never combined with the
   description check in one prompt.
3. **Resolver** (code): combines the statuses into Applicable / Not applicable / Indeterminate, as in v1.
4. **RequirementAgent**: turns an Applicable rule's THEN part into a requirement.

**Implemented (26 Oct 2026, boxes 2-4, mock tests only; nothing run on Ollama).** `src/agents/applicability_agent_v2.py`
(split call on the law text only -> `{"if", "then", "exceptions"}`, an IF item with must / shall / is required to ->
"Split invalid" (`config.yaml` `c3_v2.obligation_words`); check-IF call on the description + IF list and exceptions;
code quote check; first look; second look for Indeterminate with the description + all 5 case passages + the open IF
conditions, `look` = first / second; an empty IF list -> Indeterminate without a check call),
`src/mediation/resolver_v2.py` (Applicable only if all IF confirmed and no exception confirmed by a verified quote; an
exception the description does not mention does not block), `src/agents/requirement_agent_v2.py` (THEN -> 1-2 sentences
tied to RelevanceAgentV2's process step), `src/orchestrator_v2.py` (audit trail per case with every step; knowledge block
= confirmed requirements only, `prompts/c3_block_template_v2.json`, or C1's "No domain knowledge provided." when none).
Prompts: `prompts/applicability_{split,check,second_look}_prompt_v2.txt`, `prompts/requirement_prompt_v2.txt`. Tests:
`tests/test_c3_v2_boxes.py`. v1 files unchanged (C3 v1 hashes still match); not yet wired into `run_experiment.py`.

### Section 7 fixes, round 1 (26 Oct 2026): split role rule, plain RequirementAgentV2

**What changed.** The fixes and criteria of section 7: role rule + example in the split prompt, plain-language
RequirementAgentV2 prompt, code checks on each requirement with one retry, agent-only evaluation runner.

**Commits:** `581e2e2` (code, before the run), `22f9f8c` (REAL RUN). **Run folder:** `results/diagnostics/c3_v2_round1/`
(qwen3:8b digest `500a1f06…`, Ollama 0.40.11, agent calls only, no BPMN generation; 7 GDPR development cases +
variant 01.1 with the frozen and the oracle top 5; 45 passages, 151 calls).

**Results against the section 7 criteria:**

| # | Criterion | Result | Met |
|---|---|---|---|
| 1 | Usable split ≥ 90% | 45/45 = 100% | yes |
| 2 | No "must" / "shall" / "is required to" in IF | 0 of 46 IF items | yes |
| 3 | No situational condition: IF = the role | **9/14** | **no** |
| 4 | Requirement ≤ 40 words, 1–2 sentences, plain, names the step | 14/14 within limits (max 24 words, 1 sentence) | yes |
| 5 | No "shall" / "controller" / "data subject" / "processor" | 14/14 after the retry (3 needed it) | yes |
| 6 | ≤ 50% copied 5-word sequences | 14/14 (max 26.7%) | yes |
| 7 | States what is required, never instructs the generator to draw | 14/14 by reading | yes |
| 8 | Valid JSON ≥ 95%, at most 1 retry | 151/151, 0 retries | yes |

Round 1 does not meet all criteria (criterion 3 fails).

**New problems seen in round 1 (not covered by the section 7 criteria):**

- **Role IF items confirmed by word match.** The check-IF call confirmed role conditions from quotes that only share
  a word with the role, e.g. "the organisation acts as a processor" ← "Payment processing begins." (case 17,
  GDPR-Art30-2). 14 passages became Applicable; only 1 of the 7 Applicable on the 7 development cases is
  silver-applicable (GDPR-Art32-2, case 11; the other 6 are silver indeterminate; silver is provisional).
- **Some requirements change the rule's meaning.** GDPR-Art15-3 (case 11) lost "on request": "the customer is given a
  copy of their personal data" before billing. GDPR-Art30-2 (case 17, variant/oracle 01.1) became a record "done for
  its customers" / "for the customer", while the rule is about processing carried out on behalf of a controller.

**Decision:** round 2 with the criteria of section 8, fixed before any code change.

---

## 4. Study 2: choosing the GDPR retrieval version (development cases)

Fixed on 24 Oct 2026, **before any silver labelling** of GDPR passages (no silver label for any GDPR passage
exists when this is written). It decides which of the two frozen retrieval versions Study 2 uses for C2 and C3.

Both versions use the GDPR restricted to Chapters I-V (Art 1-50, `config.yaml` `study2_gdpr.included_chapters`;
Chapters VI-XI address supervisory authorities, remedies, specific national situations and final provisions, not an
organisation's process) and only the 7 GDPR development cases (01, 06, 11, 13, 17, 19, 45):

- **hybrid**: `data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_hybrid.json`, hybrid top 5, exactly like Study 1
- **rerank**: `data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json`, hybrid top 20 re-scored by the
  cross-encoder (sentence queries only, mean score), top 5 kept

Silver labels: the silver annotator (Study 1 setup, `openai/gpt-oss-120b` via Groq, temperature 0, unchanged prompt)
labels every case-passage pair that appears in either version once, into
`data/silver_gdpr/silver_reference_dev.json`. A pair that appears in both versions has one label, used for both.

**Rule** (counts summed over the 7 cases × 5 passages of each version's top 5):

1. The version with **more silver-applicable passages** in its top 5 wins.
2. If tied: the version with **fewer silver-irrelevant passages** in its top 5 wins.
3. If still tied: **hybrid** wins (simpler, and identical to the Study 1 method).

The rule is applied once, mechanically, to the counts; the result and the counts are recorded below. The silver
labels are AI-made (provisional, not gold), so the choice is reported as based on agreement with a stronger model.
The rule may not be changed after any GDPR silver label exists.

Result (applied 24 Oct 2026, `python -m src.build_silver_gdpr_dev`; silver file
`data/silver_gdpr/silver_reference_dev.json`, 63 case-passage pairs, `openai/gpt-oss-120b` via Groq, log
`results/logs/SILVER_gdpr_dev_silver_20261024T132952Z.jsonl`):

| version | applicable | indeterminate | not_applicable | irrelevant |
|---|---|---|---|---|
| hybrid | 1 | 18 | 3 | 13 |
| rerank | 3 | 17 | 6 | 9 |

**rerank wins at step 1** (3 silver-applicable passages vs 1). Applicable: hybrid case 45 GDPR-Art13-2-a; rerank
case 11 GDPR-Art2-1 and GDPR-Art32-2, case 19 GDPR-Art16-1. Observation (does not change the result): GDPR-Art2-1
(material scope) is labelled applicable with no required steps; without it rerank would still win (2 vs 1).

---

## 5. Study 2: adding more EU laws to the corpus (development cases)

Fixed on 24 Oct 2026, **before any of the new laws was downloaded** and before any silver label for them exists.
It decides whether Study 2 keeps the GDPR-only corpus (Chapters I-V, section 4) or replaces it with a combined
corpus. Whichever corpus wins, C2 and C3 get the same corpus and the same frozen passages; only the knowledge block
differs between C1, C2 and C3.

**Inclusion criterion.** EU laws in force whose obligations fall on the organisation running the process and that
regulate activity types in the case set (online ordering, personal data, employment, consumer credit, workplace
safety).

**Laws included by this criterion** (original version, official English text, same CELLAR method as
`data/knowledge/sources.json`):

| id prefix | law | CELEX | activity type |
|---|---|---|---|
| ECD | e-Commerce Directive 2000/31/EC | 32000L0031 | online ordering |
| TPWC | Directive (EU) 2019/1152 on transparent and predictable working conditions | 32019L1152 | employment |
| CCD | Directive (EU) 2023/2225 on credit agreements for consumers | 32023L2225 | consumer credit |
| OSH | Directive 89/391/EEC on safety and health of workers at work | 31989L0391 | workplace safety |

The GDPR Chapters I-V passages (`data/knowledge_gdpr/passages_ch1-5.jsonl`) stay in the combined corpus unchanged.

**Excluded, with reason:**
- PSD2, Directive (EU) 2015/2366: its duties fall on payment service providers, not on the organisation running
  the process.
- Digital Services Act, Regulation (EU) 2022/2065: its duties fall on intermediary services and online
  marketplaces, not on the organisation running the process.
- Working Time Directive 2003/88/EC: it gives workers entitlements through the Member States and rarely becomes a
  process step.

**Article rule.** Keep articles that set duties for the organisation (service provider, employer, creditor) plus
definitions. Drop scope-only articles and articles on transposition, penalties, reporting, review, amendments and
final provisions. Every kept and dropped article is logged with a one-line reason in `docs/PROGRESS_2026-10-24.md`.

**Method (unchanged from section 4).** Same chunker and settings as Study 1; own dense index for the combined
corpus; retrieval for the 7 development cases only (01, 06, 11, 13, 17, 19, 45) with the Study 2 setup (hybrid top
20 → cross-encoder reranker, sentence queries, mean score → top 5); silver labels with the unchanged Study 1 silver
setup (`openai/gpt-oss-120b` via Groq, temperature 0, `prompts/silver_annotation_prompt.txt`, same guards). A
case-passage pair already labelled in `data/silver_gdpr/silver_reference_dev.json` keeps that label (copied, source
marked); only new pairs are labelled.

**Decision rule.** The combined corpus (GDPR Ch. I-V + the 4 new laws) replaces GDPR-only **only if** the summed
silver-applicable count in the reranked top 5 over the 7 development cases is **higher than 3** (the GDPR-only
rerank count of section 4). If it is equal or lower, Study 2 keeps GDPR-only. The rule is applied once,
mechanically. It may not change after labelling starts. The silver labels are AI-made (provisional, not gold).

Result (applied 24 Oct 2026, `python -m src.build_silver_study2_laws_dev`; frozen retrieval
`data/retrieval_study2/frozen_retrieval_dev_combined_rerank.json`, silver file
`data/silver_study2/silver_reference_dev_combined.json`, 35 case-passage pairs, all newly labelled (no GDPR passage
reached any top 5, so no label could be reused), `openai/gpt-oss-120b` via Groq, 35/35 STOP, 0 invalid, log
`results/logs/SILVER_study2_laws_dev_silver_20261024T182923Z.jsonl`):

| corpus | applicable | indeterminate | not_applicable | irrelevant |
|---|---|---|---|---|
| GDPR-only (section 4, rerank) | 3 | 17 | 6 | 9 |
| combined (GDPR Ch. I-V + ECD, TPWC, CCD, OSH) | 0 | 21 | 1 | 13 |

**GDPR-only is kept**: the combined corpus has 0 silver-applicable passages, which is not higher than 3. Study 2 C2
and C3 keep `data/retrieval_gdpr/frozen_retrieval_dev_ch1-5_rerank.json` (`config.yaml` `study2_laws.corpus:
gdpr_only`). Observation (does not change the result): in the combined top 5, the new passages displaced every
GDPR passage (ECD Articles 10-11 in cases 01, 06, 17, 45; CCD in cases 11, 13, 19), including the 3 GDPR passages
that were silver-applicable.

## 6. Ollama version

26 Oct: Ollama auto-updated 0.40.8 → 0.40.11. Model digest unchanged (500a1f06…). smoke_gdpr_dev and RelevanceAgent v2 rounds 1–2 ran on 0.40.8; all Study 2 runs from the case-01 study onward use 0.40.11.

## 7. Round 1 fixes after case-01 study: success criteria (committed before code)

Written 26 Oct 2026, before any code change for this round. Based on the case-01 study
(`results/diagnostics/variant_01.1/report.md`, `comparison.md`).

**Problems found.**

- (a) The split put the duty into IF for passages with no condition (GDPR-Art35-9, GDPR-Art30-2).
- (b) RequirementAgent copied the legal obligation verbatim (GDPR-Art13-1 in `oracle_01.1/C3`).

**Measurement.** Real agent calls only (qwen3:8b, Ollama 0.40.11, model digest unchanged), no BPMN generation, on the
7 development cases + variant 01.1.

**Success criteria (all must hold).**

| # | Criterion | How it is checked |
|---|---|---|
| 1 | Usable split for ≥ 90% of passages | count over all passages |
| 2 | IF never contains "must", "shall" or "is required to" | code check |
| 3 | Passages with no situational condition: IF = the role the duty applies to (e.g. "the organisation acts as a processor") | per passage |
| 4 | Requirement ≤ 40 words, 1–2 sentences, plain language, names the process step | word/sentence count by code; rest per requirement |
| 5 | Requirement contains none of "shall", "controller", "data subject", "processor" | code check |
| 6 | ≤ 50% of the requirement's 5-word sequences are copied from the passage | code check |
| 7 | Requirement states what is required and NEVER instructs the generator to add or draw anything | per requirement |
| 8 | Valid JSON for ≥ 95% of calls, at most 1 retry | from the log |

**Rounds.** At most 3 rounds of changes (section 2.2); this is round 1.

## 8. Round 2: criteria (committed before code)

Written 26 Oct 2026, after the round 1 run (section 3, "Section 7 fixes, round 1") and before any code change for
round 2. Same measurement as section 7: real agent calls only (qwen3:8b, Ollama 0.40.11, model digest unchanged), no
BPMN generation, on the 7 development cases + variant 01.1.

**Kept from section 7 (all still must hold):** criteria 1–8 of section 7, unchanged.

**Added after round 1 because new failure modes were seen (all must hold):**

| # | Criterion | How it is checked |
|---|---|---|
| 9 | A role condition is confirmed only if the quote shows the role's defining facts (controller = decides why and how data is used, for its own purposes; processor = handles data on behalf of another organisation), never by word match | false-applicable rate ≤ 20% on the development cases, with silver as provisional reference, plus Claude's reading listed per passage |
| 10 | A duty on a public body (Commission, supervisory authority, Member State) → Not applicable for a business process | per passage |
| 11 | The requirement keeps every trigger and condition of the THEN (e.g. "on request", "where applicable") | ≥ 90% of requirements by reading, listed per passage |
| 12 | The role definitions are fixed text in the agent prompt, identical for all cases, and never passed to the generator | prompt files + knowledge block check |

**Rounds.** This is round 2 of at most 3 (section 2.2).
