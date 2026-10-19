# bpmngen_harness: run BPMNGen (Ollama/qwen3) on one case

Calls BPMNGen's own `OpenSourceLLM` generator directly. No server, database or login, and no BPMNGen file is changed. See `docs/BPMNGEN_ANALYSIS.md` for why.

## One-time setup (on the PC that runs Ollama, Windows)
1. Install Node.js 18+ (nodejs.org). Check with `node -v`.
2. Copy the folders `BPMNGen-backend-main` and `Thesis-BPMN` to that PC (USB or private transfer, **not** a public repo).
3. In a terminal:
   ```
   cd BPMNGen-backend-main\BPMNGen-backend-main\server
   npm install
   ```
   (`npm ci` fails because the lock file is out of sync. `npm install` also runs `prisma generate` and needs internet.)
4. Check Ollama: `ollama list` must show `qwen3:8b`.

## Smoke test (C1, case 01)
Run it from the BPMNGen **server** folder (BPMNGen reads its prompt files from there):
```
cd BPMNGen-backend-main\BPMNGen-backend-main\server
npx ts-node --cwdMode --transpile-only ..\..\..\Thesis-BPMN\bpmngen_harness\run_bpmngen.ts --description ..\..\..\Thesis-BPMN\data\cases\01\description.txt --out ..\..\..\Thesis-BPMN\results\bpmngen_smoke\C1\01 --base-url http://localhost:11434 --model qwen3:8b
```
Adjust the `..\..\..\` parts if the folders are not next to each other. `--cwdMode` is required.

## What you get in the output folder
| File | Meaning |
|---|---|
| `ollama_request.json` | exact messages + options sent to Ollama (proof of what the model saw) |
| `raw_model_output.txt` | model text before BPMNGen's cleanup |
| `raw_thinking.txt` | Ollama's separate thinking field (should be empty: the harness sends `think: false`, `--think false`) |
| `bpmngen_cleaned_output.txt` | after BPMNGen's cleanup |
| `generated.bpmn` | the BPMN that gets evaluated |
| `validation.json` | BPMNGen's own bpmnlint check |
| `meta.json` | model, num_ctx, temperature, prompt/output tokens, done_reason, `fits_context`, `auto_repairs`, time |

Check in `meta.json`: `done_reason` = "stop", `fits_context` = true, `ollama_model_reported` = "qwen3:8b", `think_param` = false, `raw_has_think_block` = false.

A runaway answer (more output tokens than `num_ctx`) is stopped by the harness: `done_reason` = "cut_off_by_harness", no `generated.bpmn`; `run_experiment.py` records it as a failed generation (`context_limit_hit`). A run longer than `generator.timeout_seconds` is killed with its whole process tree (failed generation, `timed_out`).

## BPMNGen file hashes (`--list-files`)
`run_experiment.py` starts the harness once per run with `--list-files`: it loads BPMNGen and builds a prompt (no Ollama call), then prints the BPMNGen files it loaded or read. `src/bpmngen_files.py` hashes those files plus `generator.bpmngen_hashed_files` and stores them in run_info.json (`bpmngen_file_hashes`). A run with different hashes than an earlier part, or than another run of the study, does not start.

## C2 / C3
You normally don't call the harness by hand: `run_experiment.py` does it for every case (src/bpmngen_generator.py). It writes `knowledge_block.txt` for every condition and passes it with `--knowledge`. C1's block is "No domain knowledge provided.", so all three conditions get the same layout. The block is appended after the description under the neutral label from config.yaml (`generator.knowledge_label`, PROVISIONAL, still to be agreed).

## Running the whole experiment
`run_experiment.py` calls this harness for every case (config.yaml, `generator.type: bpmngen`). Two set-ups work:
- **Everything on the GPU PC:** copy `Thesis-BPMN` (with its Python venv) and `BPMNGen-backend-main` there, as sibling folders. Keep `ollama_base_url: http://localhost:11434` (both in `llm` and `generator`).
- **Python + Node on your laptop, Ollama on the GPU PC:** on the GPU PC set the environment variable `OLLAMA_HOST=0.0.0.0` and restart Ollama. In config.yaml, set both `ollama_base_url` values to `http://<GPU-PC-IP>:11434`.

Then, from the Thesis-BPMN folder: `.venv\Scripts\python.exe run_experiment.py --condition C1 --repetition 1 --run-id smoke_bpmngen --cases 01`

## Tested
- The harness, end-to-end against a mock Ollama server.
- The whole pipeline (C1, C2, C3 for one case, including the mediation agents through OllamaLLM), against a mock Ollama server.
These check the plumbing only and say nothing about quality.
- Real qwen3:8b runs through this harness: the smoke runs (from 18 Oct 2026) and Study 1, `results/runs/ollama_rep1`-`ollama_rep3` (13 cases × C1/C2/C3 × 3 repetitions = 117 generations, 18 Oct 2026).
