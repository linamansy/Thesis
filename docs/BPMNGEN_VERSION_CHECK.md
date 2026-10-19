# BPMNGen version check, 19 Oct 2026

One-time, read-only check of the BPMNGen files on the experiment PC (audit finding 1, `docs/AUDIT_2026-10-19.md`).
The files were only read to compute SHA-256 hashes; nothing was changed, copied or quoted.
Folder: `..\BPMNGen-backend-main\BPMNGen-backend-main\server` (config.yaml `generator.bpmngen_server_dir`).

## 1. The four expected files

| File | Expected SHA-256 | Found on this PC | Result |
|---|---|---|---|
| `tools/ai/opensource.ts` | `d95e8533aa0a6a2e0c05726a1de4df76b7bc966fa7ba0d82f27670c703f73481` | `d95e8533aa0a6a2e0c05726a1de4df76b7bc966fa7ba0d82f27670c703f73481` | **MATCH** |
| `tools/ai/ai.ts` | `aa30891fd25b4bc050955893811ec02a710cf8e5ca84fb9b95011bd502a9394c` | `aa30891fd25b4bc050955893811ec02a710cf8e5ca84fb9b95011bd502a9394c` | **MATCH** |
| `tools/utils/xml-validator.ts` | `dbf5850759e13bbc5ac7baaeb388bfc9bfa9be280db9dfc1626160be601076c7` | `dbf5850759e13bbc5ac7baaeb388bfc9bfa9be280db9dfc1626160be601076c7` | **MATCH** |
| `environment.ts` | `c3fab344f48e13bfc20c6ad927fae38753cf4baaa0fcf5c0eb86132ebae82445` | `c3fab344f48e13bfc20c6ad927fae38753cf4baaa0fcf5c0eb86132ebae82445` | **MATCH** |

## 2. Every BPMNGen file the harness loads

`run_bpmngen.ts --list-files` loads BPMNGen exactly as for a generation and builds a prompt, without calling Ollama.
It reports 16 BPMNGen files outside `node_modules`: 13 code files plus 3 files BPMNGen reads while building the prompt.
The table lists all 16, with each file compared against the same file inside the original download,
`Downloads\BPMNGen-backend-main.zip` (SHA-256 `752d8ff405960c7221fa20ad00ed3b7e8ff70da6527b8aa071e15600c0220fed`,
3,147,933 bytes, dated 16 Oct 2026 21:21).

| File | SHA-256 on this PC | Same as in the zip? | Last modified |
|---|---|---|---|
| `data/assistant/knowledge/example-burger-restaurant.bpmn` | `f59470075bd5279e57ec19eb38458d9391dc212f38dd91d5e30908c6e5396b2d` | same | 2026-10-18 14:32:47 |
| `data/assistant/knowledge/instructions_quick.txt` | `f74a2412f1c956d16c12e7319e815d9179be08ea70920c126e4776413a64e2a8` | same | 2026-10-18 14:32:47 |
| `data/assistant/knowledge/instructions_xml.txt` | `7d0ebad737fbd0b7fe6aa4e66a485cd2befc2766176474045332b30f327a6e1b` | same | 2026-10-18 14:32:47 |
| `databaseServer.ts` | `70e95f3591c080dbca3f4361cca903a761bae90adf75e7a386690c5e35b4f5bf` | same | 2026-10-18 14:32:46 |
| `environment.ts` | `c3fab344f48e13bfc20c6ad927fae38753cf4baaa0fcf5c0eb86132ebae82445` | same | 2026-10-18 14:32:46 |
| `package.json` | `557f3545479d410584c1809b78507712ad6c6aa7d62bf9ea71fa831a86e2db0f` | same | 2026-10-18 14:32:46 |
| `tools/ai/ai.ts` | `aa30891fd25b4bc050955893811ec02a710cf8e5ca84fb9b95011bd502a9394c` | same | 2026-10-18 14:32:48 |
| `tools/ai/bpmnLayout.ts` | `5bf509dad45df6cf962ab8bd4b8f70c04500ea2928c2bee9e9a1d3847e12bfcf` | same | 2026-10-18 14:32:48 |
| `tools/ai/opensource.ts` | `d95e8533aa0a6a2e0c05726a1de4df76b7bc966fa7ba0d82f27670c703f73481` | same | 2026-10-18 14:32:48 |
| `tools/format/custom-moddle.ts` | `ecd3a7b5c3f54d634399963ee5654cdaa0f66ac88b112db7e7698438343b7ed7` | same | 2026-10-18 14:32:48 |
| `tools/format/json-xml.ts` | `ca1e5068700c2449c8597697da5e1535c1bd8a4566e64274dea3ff4189d00106` | same | 2026-10-18 14:32:48 |
| `tools/format/xml-json.ts` | `6c2ff29cf728ca8e83c4391164d224b7b91bd88df6955a95baf727b12bfcad22` | same | 2026-10-18 14:32:48 |
| `tools/format/xml-svg.ts` | `b37fc4ff292b2bfd78495dca57dff45b860143e373326a3d7092e23cef7ed45a` | same | 2026-10-18 14:32:48 |
| `tools/utils/description-processing.ts` | `49cd1daf7f4bd47e6828450eafb0c70933cb6cd85d5809e81e2af78c60a79c46` | same | 2026-10-18 14:32:48 |
| `tools/utils/pdf-processing.ts` | `4c154728ec69336de8f1174b0e22a29f3febb1a0e9ecdd008830b2bebdbc6fa7` | same | 2026-10-18 14:32:48 |
| `tools/utils/xml-validator.ts` | `dbf5850759e13bbc5ac7baaeb388bfc9bfa9be280db9dfc1626160be601076c7` | same | 2026-10-18 14:32:48 |

## 3. What this shows, and what it does not

- All four expected hashes match, and all 16 files the harness loads are byte-identical to the original BPMNGen download.
  So the BPMNGen code on this PC is unmodified.
- Every file was last modified on 18 Oct 2026 at 14:32 (local time), when the zip was extracted. Repetition 1 started at
  20:43 the same day (run_info.json `created_at` 17:43 UTC), so no file was changed after the runs began.
  Modification times are supporting evidence only: they can be reset.
- The hashes were computed **after** the runs (19 Oct). They prove the state of the files now. They are not a record taken
  during the runs. Report it that way: "BPMNGen files were verified unchanged against the original download after the
  runs; from 19 Oct 2026 every run records these hashes in run_info.json and refuses to start if they differ."
- `node_modules` (BPMNGen's dependencies, e.g. bpmnlint) is not hashed.
- BPMNGen's `.env` is excluded from hashing (config.yaml `generator.bpmngen_hash_exclude`), because it holds secrets.
  On this PC it does not exist; BPMNGen only looks for it.
