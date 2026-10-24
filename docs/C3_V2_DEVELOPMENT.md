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

> **TO BE FILLED IN.** The success criteria were not yet provided when this file was created. They must be written
> here and committed before round 1 starts. They may not be changed after round 1 has started.

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

(No rounds yet.)

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
