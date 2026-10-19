# BPMNGen analysis: how it works with Ollama, and what that means for C1/C2/C3

Date: 16 Oct 2026. Code read: `BPMNGen-backend-main` (server/) as downloaded, no changes made.
BPMNGen is private Ulm code: keep this repo private and never push BPMNGen itself.
Written before any real model output: everything below comes from reading the code, plus one end-to-end test against a **mock** Ollama server. Real qwen3:8b output followed on 18 Oct 2026 (smoke runs and Study 1, `results/runs/ollama_rep1`-`ollama_rep3`, 117 generations).

## 1. From description to BPMN (Ollama path), step by step

| Step | What happens | Where |
|---|---|---|
| 1 | `POST /threads` receives `inputString`, `model`, `mode`, `format`, optional `file` | routes/threads/threads.ts ~L123 |
| 2 | If the file is a DMN, it is turned into a WHEN/THEN rule list (`dmnContext`) | threads.ts ~L145, ai.ts `dmnToRules` |
| 3 | `createBPMN` builds the prompt: description, then optionally `[Document content:]` (PDF) and `[DMN decision rules the generated process MUST follow:]` | tools/ai/ai.ts L63–71 |
| 4 | `OpenSourceLLM.mapPromptInput` builds the messages: **one fixed system prompt** + chat history (empty for a new thread) + user prompt + `/no_think` for qwen3 | tools/ai/opensource.ts L281–318 |
| 5 | **One** call to Ollama `/api/chat` (streamed and buffered) | opensource.ts L105–145 |
| 6 | Deterministic cleanup of the XML (see section 3) | opensource.ts L359 ff. |
| 7 | XML extracted (`convertResponseToDiagramOutput`), saved to DB | ai.ts L1371 |
| 8 | A second Ollama call makes a chat **title**. It does not affect the diagram | opensource.ts L50 |

There are **no retries, no self-correction loop and no second generation call**. That's good for fairness: every condition gets exactly one generation call.

## 2. Settings for qwen3:8b

| Setting | Value | Set explicitly? |
|---|---|---|
| Model | `qwen3:8b` (whatever is installed in Ollama under that tag) | yes (L38) |
| Context window `num_ctx` | **16384** tokens (input + output share it) | yes (L26, L117) |
| Temperature | **0.3** | yes, hard-coded (L317) |
| Seed | none, so runs are **not** reproducible | no |
| Max output tokens | Ollama default (unlimited until num_ctx is full) | no |
| Thinking mode | disabled by appending `/no_think` to the user message; leftover `<think>` blocks are stripped | yes (L293–296, L350) |
| Output format | **XML only**. The LLM writes BPMN XML directly | yes |

Notes:
- `format: "json"` must not be used with Ollama. The class always returns XML, so the JSON parser would fail.
- Your CLAUDE.md says "temperature 0" and "no LLM writes BPMN XML directly". Both are false for BPMNGen+Ollama, so Chapter 3 and CLAUDE.md must be updated.
  *Correction (19 Oct 2026): CLAUDE.md has since been updated (BPMNGen keeps temperature 0.3; qwen3 writes BPMN XML directly). Chapter 3 still needs the same update.*

## 3. Important: BPMNGen's cleanup can ADD structure

After the model answers, `cleanupModelXml` fixes common small-model mistakes. Most fixes are harmless (quotes, namespaces). Three of them **add** things the model did not produce:
- `ensureSequenceFlows`: if a process has no flows at all, it chains all nodes **in document order**.
- `connectIsolatedFlowNodes`: links nodes without incoming/outgoing flows to their document neighbours.
- `repairCollapsedFirstAction`: inserts a first task when the start event was named after the first action.
  *Correction (19 Oct 2026): the first-task repair cannot run in this code path; see CLAUDE.md. Verified against the hash-matched BPMNGen download; first_task_inserted is false in 117/117 generations.*

These run identically in C1/C2/C3, so they are not a confound by themselves. But they change the order/logic metrics, and they may fire more often in one condition (e.g. when longer prompts make the model sloppier). **The harness counts them for every run** (`meta.json → auto_repairs`). Report them per condition.

## 4. Where knowledge can enter, and the problem with the DMN option

- The DMN route adds the label "…MUST follow" **and** a set of instructions (`instructions_dmn_input.txt`: "MUST implement every rule", "DMN rules win").
- **Finding:** `OpenSourceLLM.mapPromptInput` **ignores `input.instructions` completely**. It only sends its own fixed system prompt. So with Ollama, only the "MUST" label reaches the model; the DMN instructions don't. The DMN route is still unsuitable because of the "MUST" wording, and because your knowledge isn't a DMN table.
- The PDF route uses a neutral label (`[Document content:]`), but needs a PDF file and also sends rendered page images. Not suitable.
- **Proposed approach (implemented in the harness, to be agreed with Ulm/supervisors):** append the knowledge to the prompt exactly as `createBPMN` does for DMN/PDF, but with one neutral label, identical for C2 and C3:
  `[Domain information (it may or may not apply to this process):]`
  **Decided (16 Oct):** C1 uses the same label with the block "No domain knowledge provided.", so all three conditions have an identical layout.

## 5. Ollama is switched off in this version

In `tools/useGPT.ts` (L6, L18), `OpenSourceLLM` is **commented out**. So the web app as downloaded cannot use Ollama/qwen3. Ask the PhD students whether they have a branch where it's enabled.
The harness avoids this: it imports the class directly, so no BPMNGen file has to be edited.

## 6. Installation findings

- Full server needs Node ≥18, PostgreSQL, `.env` (API keys, JWT_SECRET, FRONTEND_URLS, PRODUCTION), `npx prisma migrate dev`.
- `npm ci` fails: package-lock.json is out of sync (`@bpmn-io/cm-theme` missing). Use `npm install`.
- `npm install` runs `prisma generate` (downloads Prisma engines, needs internet). No database is needed for that step.
- The harness needs **no** PostgreSQL, no login and no frontend.

## 7. How to call it programmatically

- Via the server: `POST /threads` with JSON `{inputString, model: "qwen3:8b", mode: "quick", format: "xml", stream: false}` plus login (JWT). This needs the DB, an account, and Ollama enabled in useGPT.ts.
- **Recommended for the experiment:** `bpmngen_harness/run_bpmngen.ts`. It uses the same BPMNGen classes, makes one call per case, and saves the exact request, raw output, cleaned output, BPMN, validation, token counts and `done_reason`.

## 8. Fairness checklist (C1/C2/C3 differ only in knowledge)

| Risk | Status |
|---|---|
| Same system prompt in all conditions | yes (fixed, L192) |
| Same model, num_ctx, temperature | yes (hard-coded). **Decided (16 Oct): keep 0.3** (no seed), so expect run-to-run variance; the 3 repetitions measure it |
| Same knowledge label and position for C2 and C3 | yes (harness) |
| Prompt truncation | automatic: a cut-off answer is recorded as a failed generation with `context_limit_hit = True` and counted per condition |
| Chat history leaking between cases | none: the harness uses an empty history (like a new thread) |
| Auto-repairs differ between conditions | measured (`auto_repairs`); report per condition |
| Mediation agents (C3) use another model than the generator | **decided (16 Oct): same qwen3:8b**; the exact Ollama digest is stored in run_info.json |

## 9. Rough size check (from the frozen retrieval, no model run)

Retrieved passages per case: 2.3k–6.1k characters (≈0.6k–1.5k tokens); descriptions 0.5k–1.3k characters.
The system prompt is ≈2k tokens. So input is ≈3k–4k tokens, which leaves ≥12k tokens for the XML.
This should fit, but must be confirmed with the real `prompt_eval_count` and `eval_count` values.

## 10. Questions for the PhD students

1. Is the harness approach (importing OpenSourceLLM, skipping DB/title) an acceptable way to use BPMNGen as a fixed generator?
2. Is a neutral context label appended to the prompt OK, or do they prefer another injection point?
3. Should temperature stay at 0.3 (BPMNGen default) or may it be set to 0 for all conditions?
4. Is there a branch where Ollama is enabled in useGPT.ts?
