# Case-01 study: generated vs reference, element by element

Sources (saved files only): `results/runs/{variant_01.1,oracle_01.1}/<cond>/<case>/generated.bpmn` and `validation.json`,
`data/cases/01/reference.bpmn`, `data/cases/01.1/reference.bpmn` (PROVISIONAL, = 01 + Task_9), `data/cases/01.1/variant.json`,
and the `knowledge_block.txt` of each run.

Study 1 rule: every scorable file is invalid only because of an undeclared `bpmndi` prefix; the comparison uses the
di_stripped copy (`<bpmndi:BPMNDiagram>` removed), which passes `src/validator.py`. Only the process part of the
file is compared; the diagram section held drawing positions only.

Matching is by meaning (manual). "Missing [uncertain]" = the reference task has no task in the generated model, but
something related appears as an event or a message flow. "Addition valid?" is a PROPOSAL only; Lina decides.
Pools (participants "Customer", "Sales Staff") and message flows are not elements in this table.

Reference elements (01): start `start`; tasks Task_5 Receive customer inquiry, Task_2 Collect customer information,
Task_7 Address customer concerns or questions, Task_3 Guide customer in selecting product/service, Task_4 Provide quote,
Task_6 Place order, Task_1 Record order in system, Task_8 Send order confirmation to customer; parallel split
ParallelGateway_2 / join ParallelGateway_1 (collect info ‖ address concerns); exclusive split ExclusiveGateway_4
(interested → guide, else end); exclusive split ExclusiveGateway_2 (after quote: place order or not); exclusive merges
ExclusiveGateway_1, ExclusiveGateway_3; end `end`. 01.1 adds Task_9 "Inform customer about how their contact details
will be used" between Task_2 and ParallelGateway_1.

---

## 1. variant_01.1/C1/01 (reference: 01, no knowledge block)

| Element (task/gateway/event) | In reference | In generated | Status (Common/Missing/Addition) | Addition valid? | Reason / linked passage |
|---|---|---|---|---|---|
| Start event | `start` (StartEvent_1) | `Inquiry` (se1, Customer pool) | Common | — | Both start the process at the inquiry |
| Task: receive inquiry | Receive customer inquiry (Task_5) | — (only start event se1 "Inquiry" + message flow "Inquiry" se1→t1) | Missing [uncertain] | — | Trigger is shown as an event, not as a task |
| Task: collect information | Collect customer information (Task_2) | Collect Information (t1) | Common | — | Same meaning |
| Task: address concerns | Address customer concerns or questions (Task_7) | Address Concerns (t2) | Common | — | Same meaning; in sequence after t1, not in parallel |
| Parallel split / join | ParallelGateway_2, ParallelGateway_1 | — | Missing | — | t1 → t2 is sequential |
| Exclusive split: customer interested? | ExclusiveGateway_4 | — | Missing | — | No decision modelled |
| Task: guide selection | Guide customer in selecting product/service (Task_3) | — | Missing | — | |
| Task: provide quote | Provide quote (Task_4) | Provide Quote (t3) | Common | — | Same meaning |
| Exclusive split: quote approved? | ExclusiveGateway_2 | — (Customer event ice1 "Quote Approved") | Missing | — | No decision; approval only as an event |
| Task: place order | Place order (Task_6) | — (message flow "Order" t3→se2, Sales start event "Order Received") | Missing [uncertain] | — | Order placement appears only as a message/event |
| Task: record order | Record order in system (Task_1) | Record Order (t4) | Common | — | Same meaning |
| Task: send confirmation | Send order confirmation to customer (Task_8) | — (message flow "Confirmation" se2→ice2) | Missing [uncertain] | — | Confirmation only as a message flow, no task |
| Exclusive merges | ExclusiveGateway_1, ExclusiveGateway_3 | — | Missing | — | |
| End event | `end` (EndEvent_1) | `Order Complete` (ee1, Customer pool) | Common | — | Both end the process |
| Intermediate catch event | — | Quote Approved (ice1, Customer) | Addition | PROPOSED: valid | Description: "after approval from the customer"; no passage (C1) |
| Intermediate catch event | — | Order Confirmed (ice2, Customer) | Addition | PROPOSED: valid | Description: "the customer receives confirmation of their order"; no passage |
| Message start event | — | Order Received (se2, Sales pool) | Addition | PROPOSED: invalid | Sales pool starts with "Order Received" and then collects information and quotes, which reverses the order in the description |
| End event | — | Done (ee2, Sales pool) | Addition | PROPOSED: valid | End of the second pool; structural, no new content |

Notes: BPMNGen cleanup added one sequence flow `auto_link_out_se1_to_ice2` (Customer pool; auto_links_added = 1).
Message flows mf1, mf2 (se1→t1, t1→t2) connect elements inside the same or crossing pools in an unusual way; not scored here.

**Expected step present: no** (not expected either: base case 01, no knowledge block, reference 01 has no Task_9).

---

## 2. oracle_01.1/C2/01.1 (reference: 01.1; passages Art35-9, Art7-4, Art30-2, Art12-6, Art13-1 raw)

| Element (task/gateway/event) | In reference | In generated | Status (Common/Missing/Addition) | Addition valid? | Reason / linked passage |
|---|---|---|---|---|---|
| Start event | `start` (StartEvent_1) | `Inquiry` (se1, Customer pool) | Common | — | Both start at the inquiry |
| Task: receive inquiry | Receive customer inquiry (Task_5) | — (Sales message start event se2 "Inquiry Received") | Missing [uncertain] | — | Shown as an event, not as a task |
| Task: collect information | Collect customer information (Task_2) | Collect Information (t1) | Common | — | Same meaning |
| **Task: inform about data use (expected step)** | Inform customer about how their contact details will be used (Task_9) | — | Missing | — | GDPR-Art13-1 was in the prompt verbatim; no task, event or message about informing the customer |
| Task: address concerns | Address customer concerns or questions (Task_7) | Address Concerns (t2) | Common | — | Sequential after t1, not in parallel |
| Parallel split / join | ParallelGateway_2, ParallelGateway_1 | — | Missing | — | |
| Exclusive split: customer interested? | ExclusiveGateway_4 | — | Missing | — | |
| Task: guide selection | Guide customer in selecting product/service (Task_3) | — | Missing | — | |
| Task: provide quote | Provide quote (Task_4) | Provide Quote (t3) | Common | — | Same meaning |
| Exclusive split: quote approved? | ExclusiveGateway_2 | — | Missing | — | Approval is a task (t4), no decision |
| Task: place order | Place order (Task_6) | — (Customer end event "Order Placed") | Missing [uncertain] | — | Only as end-event label |
| Task: record order | Record order in system (Task_1) | Record Order (t5) | Common | — | Same meaning |
| Task: send confirmation | Send order confirmation to customer (Task_8) | — (message flow "Order Confirmation" t5→ice3) | Missing [uncertain] | — | Only as a message flow |
| Exclusive merges | ExclusiveGateway_1, ExclusiveGateway_3 | — | Missing | — | |
| End event | `end` (EndEvent_1) | `Order Placed` (ee1, Customer pool) | Common | — | Both end the process |
| Task | — | Wait for Approval (t4) | Addition | PROPOSED: valid | Description: "after approval from the customer"; no passage |
| Intermediate catch event | — | Information Collected (ice1, Customer) | Addition | PROPOSED: invalid | Description gives no message to the customer after collection [uncertain]; no passage |
| Intermediate catch event | — | Quote Received (ice2, Customer) | Addition | PROPOSED: valid | Description: "the sales representative provides a quote"; no passage |
| Intermediate catch event | — | Order Confirmed (ice3, Customer) | Addition | PROPOSED: valid | Description: "the customer receives confirmation"; no passage |
| End event | — | Order Confirmed (ee2, Sales pool) | Addition | PROPOSED: valid | End of the second pool; structural |

Notes: no BPMNGen auto-repairs (all 0). Message flow mf4 "Approval" points to `se3`, which is not an element in the
file; mf1 runs from t1 to the Sales start event se2 (same pool). None of the additions relates to any of the five passages.

**Expected step present: no.**

---

## 3. oracle_01.1/C3/01.1 (reference: 01.1; C3 block = one requirement [GDPR-Art13-1], label Applicable)

| Element (task/gateway/event) | In reference | In generated | Status (Common/Missing/Addition) | Addition valid? | Reason / linked passage |
|---|---|---|---|---|---|
| Start event | `start` (StartEvent_1) | `Inquiry` (se1, Customer pool) | Common | — | Both start at the inquiry |
| Task: receive inquiry | Receive customer inquiry (Task_5) | — (Sales message start event se2 "Inquiry Received") | Missing [uncertain] | — | Shown as an event, not as a task |
| Task: collect information | Collect customer information (Task_2) | Collect Information (t1) | Common | — | Same meaning |
| **Task: inform about data use (expected step)** | Inform customer about how their contact details will be used (Task_9) | — | Missing | — | The C3 block stated GDPR-Art13-1 as an applicable requirement ("at the time when personal data are obtained during the inquiry ... provide the data subject with ..."); no task, event or message for it |
| Task: address concerns | Address customer concerns or questions (Task_7) | Address Concerns (t2) | Common | — | Sequential after t1, not in parallel |
| Parallel split / join | ParallelGateway_2, ParallelGateway_1 | — | Missing | — | |
| Exclusive split: customer interested? | ExclusiveGateway_4 | Customer Interested? (g1, exclusiveGateway) | Common [uncertain] | — | Same question, but placed after Provide Quote and with only one outgoing flow (g1→t4); reference places it before guiding, with two branches |
| Task: guide selection | Guide customer in selecting product/service (Task_3) | — | Missing | — | |
| Task: provide quote | Provide quote (Task_4) | Provide Quote (t3) | Common | — | Same meaning |
| Exclusive split: quote approved? | ExclusiveGateway_2 | — | Missing | — | Approval is a task (t4), no decision |
| Task: place order | Place order (Task_6) | — (Customer end event "Order Placed") | Missing [uncertain] | — | Only as end-event label |
| Task: record order | Record order in system (Task_1) | Record Order (t5) | Common | — | Same meaning |
| Task: send confirmation | Send order confirmation to customer (Task_8) | — (message flow "Order Confirmation" t5→ice2) | Missing [uncertain] | — | Only as a message flow |
| Exclusive merges | ExclusiveGateway_1, ExclusiveGateway_3 | — | Missing | — | |
| End event | `end` (EndEvent_1) | `Order Placed` (ee1, Customer pool) | Common | — | Both end the process |
| Task | — | Request Approval (t4) | Addition | PROPOSED: valid | Description: "after approval from the customer"; no passage |
| Intermediate catch event | — | Quote Received (ice1, Customer) | Addition | PROPOSED: valid | Description: "the sales representative provides a quote"; no passage |
| Intermediate catch event | — | Order Confirmed (ice2, Customer) | Addition | PROPOSED: valid | Description: "the customer receives confirmation"; no passage |
| End event | — | Order Confirmed (ee2, Sales pool) | Addition | PROPOSED: valid | End of the second pool; structural |

Notes: BPMNGen cleanup added `auto_link_out_se1_to_ice2` (auto_links_added = 1); ice1 has no incoming sequence flow.
Message flows mf2 and mf4 point to `se3` and `se5`, which are not elements in the file. `thinking_detected` = True:
the raw answer contains one stray `</think>` (line 71 of generated.bpmn), inside the `<bpmndi:BPMNDiagram>` section,
so the di_stripped copy does not contain it. None of the additions relates to GDPR-Art13-1 or the other passages.

**Expected step present: no.**

---

## Not scorable

- **variant_01.1/C2/01.1**: XML does not parse — "error parsing attribute name, line 68, column 28" (`<bpmn:intermediateCatch, id="ice8" ...>`, inside the process part, so the DI rescue does not apply).
- **variant_01.1/C3/01.1**: XML does not parse — "Namespace prefix bpmndi on BPMNDiagram is not defined, line 51, column 41"; the di_stripped copy parses but fails the validator (sequence flows f4_dup2, f5, f6, f7 in SalesProcess reference `ice1`, `ice2`, `ee1` of CustomerProcess), so it is not rescued.
