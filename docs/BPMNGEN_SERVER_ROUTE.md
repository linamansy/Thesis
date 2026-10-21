# BPMNGen server route (POST /threads): models, prompts, database, setup

Written 21 Oct 2026 from a read-only reading of
`../BPMNGen-backend-main/BPMNGen-backend-main/server` (no file was run, changed or copied).
BPMNGen is private Ulm code; this file only describes it and quotes at most a few words.
File paths below are relative to that `server/` folder. Line numbers are as read on 21 Oct 2026.

**Unsure** marks anything I could not confirm from the code alone (for example, it would need a
running server, a real API call or a provider's documentation).

Short answer for the thesis: the server route can NOT run our qwen3:8b on Ollama as it is,
because `OpenSourceLLM` (the class our harness uses) is commented out in `tools/useGPT.ts`.
Using the route would mean changing a BPMNGen file, which our rules forbid. See section 6.

---

## 1. Enabled model classes and the model names they accept

`tools/useGPT.ts` lines 13-24 build the list `AI_INSTANCES`. Enabled:

| Class | File | Model names in `getModelNamesWithPriority()` |
|---|---|---|
| `ChatGPT` | tools/ai/openai.ts:61-69 | `gpt-5.6-terra`, `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra` |
| `GrokAI` | tools/ai/grok.ts:57-61 | none (the only entry, `grok-3-mini`, is commented out) |
| `Claude` | tools/ai/claude.ts:57-64 | `claude-opus-4-8`, `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` |
| `Gemini` | tools/ai/gemini.ts:55-62 | `gemini-2.5-pro`, `gemini-3.1-pro-preview`, `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-4-argon` |
| `OpenRouterLLM` | tools/ai/openrouter.ts:70-80 | `deepseek/deepseek-v4-pro`, `deepseek/deepseek-v4-flash`, `moonshotai/kimi-k2.5`, `mistralai/mistral-large-2512`, `qwen/qwen3.5-397b-a17b` — **only if `OPENROUTER_API_KEY` is set** when the server starts, otherwise none |
| `OpenRouterSelfLayoutLLM` | tools/ai/openrouterSelfLayout.ts:28-36 | `deepseek/deepseek-r1-0528:sl`, `deepseek/deepseek-v4-pro:sl`, `moonshotai/kimi-k2.5:sl` — same `OPENROUTER_API_KEY` condition |
| `ChatGPTAssistantDefaultJson` | tools/ai/openai.ts:541-550 | `gpt-assistant2` (json only) |
| `ChatGPTAssistantDefaultXml` | tools/ai/openai.ts:598-602 | `gpt-assistant1` (xml only) |

Disabled (commented out, lines 6-7 and 18-19): `OpenSourceLLM` (tools/ai/opensource.ts, the Ollama
class our harness uses) and `OpenSourceCloudLLM`.

**How a name is accepted.** `availableGPTs` (useGPT.ts:103-121) holds, for every name above, the keys
`"<name> (xml)"`, `"<name> (json)"` (one per format the class allows; the default class allows both)
and the bare `"<name>"` (= the class's first format, xml for most). The request field `model` must be
one of these keys (middlewares/endpointValidation.ts:116-122), otherwise the request gets HTTP 400.
Negative priorities (e.g. `gemini-2.5-flash-lite`, or the `json: -1` of the GPT names) only hide a
model from `GET /models` (`recommendedGPTs`); they are still accepted by `POST /threads`.
If `model` is missing, the first entry of `availableGPTs` is used (useGPT.ts:39-46), which by
construction order should be `gpt-5.6-terra (xml)`. **Unsure:** I did not run the code to confirm
the map's first key.

**Unsure:** for the two `ChatGPTAssistant…` classes, `availableGPTs` calls
`new ai.constructor(name, format)`, but their constructors take only `(apiKey)`. So the model name
(e.g. `gpt-assistant2`) would end up as the API key. Also `promptAiForDiagram` (openai.ts:486-512)
creates the message on one OpenAI thread but starts the run on `this.createThread()`, which in the
base class returns a random UUID, not an OpenAI thread. Both look like bugs, so these two classes
probably do not work. Not tested.

## 2. Per enabled class: system prompt, temperature, max tokens, `input.instructions`

**Where the system prompt comes from (all classes).** `Ai.createBPMN` (tools/ai/ai.ts:63-99) builds
`instructions` from two text files in `data/assistant/knowledge/`, read at request time
(`readInstructionsFile`, ai.ts:1066-1074):

- format part (ai.ts:1084-1108): xml → `instructions_xml.txt` + `example-burger-restaurant.bpmn`;
  json → `instructions_current_json.txt` + `example-burger-restaurant.json`;
  mode conversation / choreography (xml) → their own instruction + example files.
- mode part (ai.ts:1116-1137): quick → `instructions_quick.txt`; detail → `instructions_detail.txt`;
  unified → `instructions_unified.txt`; description → `instructions_description.txt` + `dispatch-of-goods.json`;
  conversation / choreography → nothing extra.
- only if a DMN file is attached: `instructions_dmn_input.txt`.
- PATCH /threads/:id (update) also adds the latest saved diagram and its moddle warnings (ai.ts:1233-1256).

If a file cannot be read, a fixed fallback sentence is used instead (ai.ts:1072), without an error.
These go into `PromptInput.instructions`; the user text goes into `PromptInput.prompt`.

| Class | How `input.instructions` is sent | Temperature | Max tokens |
|---|---|---|---|
| `ChatGPT` (openai.ts:176-210) | Yes: each instruction as its own `role: "system"` item in the Responses API `input` | not set → OpenAI default | not set |
| `GrokAI` (grok.ts:167-185) | Yes: joined with `"\n"` into `system` (Vercel AI SDK) | not set → provider default | not set |
| `Claude` (claude.ts:179-224) | Yes: each instruction as a text block in `system` | not set → Anthropic default | `max_tokens: 15000`; a `max_tokens` stop throws an error (claude.ts:150) |
| `Gemini` (gemini.ts:152-379) | Yes, but as `role: "model"` turns at the start of `contents`, not as Gemini's `systemInstruction` | not set (a `temperature: 0.0` config block is commented out, lines 194-377) | not set |
| `OpenRouterLLM` (openrouter.ts:340-405) | Yes: joined with `"\n"`, then extra text appended: `instructions_xml_openrouter.txt`, `example-parallel-lanes.bpmn`, a fixed "do not generate bpmndi" paragraph, and `"/no-think"` for qwen3 (non-thinking) and DeepSeek V3/V4 names | `0` (the code comment says 0.2; the code sends 0) | not set (the doc comment above still lists 32 000 / 12 000 / 8 000; this is out of date) |
| `OpenRouterSelfLayoutLLM` (openrouterSelfLayout.ts:69-113) | Yes: as OpenRouterLLM but without the "no bpmndi" paragraph and without `/no-think`; strips `:sl` from the model id | `0` | not set |
| `ChatGPTAssistantDefaultJson` / `…Xml` (openai.ts:477-512) | **No**: only `input.prompt` is sent; the system prompt is stored inside the OpenAI Assistant (`asst_…` ids in openai.ts:447-450) and is not in this repository | set in the Assistant (unknown) | unknown |

Other request settings worth knowing:

- `ChatGPT`: for format json + mode quick it asks for structured output with the zod `PoolsSchema`
  (openai.ts:201).
- Chat history: every earlier chat message text of the thread (user and AI, not SYSTEM) is sent as
  history (ai.ts:71, 1847-1857). For a new thread this is empty, because the thread id is a fresh UUID.
- OpenRouterLLM non-streaming: if the answer stops with `finish_reason = length`, it sends ONE
  continuation request and joins the two parts (openrouter.ts:145-168). It also strips
  `<think>` blocks, markdown fences and any `bpmndi` section from the answer (openrouter.ts:207-213).
- All classes: titles are made by a SECOND, different model call (e.g. `gpt-5-nano`, `claude-haiku-4-5`,
  `gemini-2.5-flash`, `grok-3-mini-fast-latest`, `meta-llama/llama-4-maverick`), see each `createTitle`.
- **Unsure:** provider defaults (temperature, output limit) are set by OpenAI / Anthropic / Google / xAI /
  OpenRouter and may change; I did not check their documentation.

## 3. POST /threads: what it expects and what it returns

Route: routes/threads/threads.ts:94-225, mounted at `/threads` (app.ts:556). Server port 1207
(server.ts), HTTP when `PRODUCTION` is not `"True"`, HTTPS with `certificates/key.pem` and `cert.pem`
when it is.

**Authentication (JWT).** Header `Authorization: Bearer <sessionToken>` (tools/authentication.ts:216-231).
The token is signed with `JWT_SECRET`, holds `{userId}` and expires after **15 minutes**.
You get one from `POST /auth/signup` (email, password, name; plus `invitationCode` when
`PRODUCTION=True`), `POST /auth/login` (email, password) or `POST /auth/guest-login` (no body);
a refresh cookie renews it at `POST /auth/refresh`. The user must also exist in the database (threads.ts:128-131).

**API key used for the model** (routes/threads/helper.ts:5-33):
- `role = USER` or `ADMIN` and `useOwnKey` false → the server key from `.env`.
- `role = GUEST` (every guest login) or `useOwnKey: true` → the user's own key, stored encrypted in
  the `ApiKey` table (set with `PUT /user/api-keys` `{provider, apiKey}`). The provider is guessed from
  the model name (contains "claude" / "gemini" / "grok", contains "/" → OpenRouter, else OpenAI).
  No stored key → HTTP 401.

**Body fields** (JSON; limit ~15 MB, app.ts:546-549):

| Field | Required | Check | Meaning |
|---|---|---|---|
| `inputString` | yes | string, not empty, at most 30 000 **characters** (the constant is called `MAX_INPUT_TOKENS`, but `isLength` counts characters) | the process description |
| `model` | no | one of the `availableGPTs` keys (section 1) | e.g. `"claude-sonnet-5-5 (xml)"` |
| `mode` | no, default `quick` | `quick`, `detail`, `description`, `unified`, `conversation`, `choreography` | which mode instruction file is used; `description` (or `unified` with a BPMN file / image) turns the request into model-to-text |
| `format` | no | `xml` or `json` | forced to `xml` for conversation / choreography; json answers are converted to XML by `jsonToXml` |
| `stream` | no, default false | boolean | SSE stream instead of one JSON reply |
| `file` | no | image data URI (jpeg/png/gif, ≤ 10 MB); for some modes also BPMN XML or a PDF data URI | PDF text is added to the prompt and pages are sent as images; a DMN file becomes rules the model must follow |
| `samples` | no | not validated | up to 5 extra model names, run in parallel on the same input |
| `useOwnKey` | no | not validated | see API key above |

**What it returns** (ai.ts:63-99, 436-456, 496-608):
- `stream` false: **HTTP 201** with JSON `{xml, json?, text?, model, threadId, samples?}`.
  `model` is `"<name> (<format>)"`. In `quick` (and conversation / choreography) mode only the diagram
  is kept, no `text`. `json` is a string, only for format json.
  The reply is sent only after the title call and the database save have finished.
- `stream` true: **HTTP 202**, `text/event-stream`. Events: `start` (threadId), `alive` (every second),
  `delta` (text), `diagram-start`, `diagram-end`, `diagram` (the XML), `end` (the same JSON as above),
  then `save` (`success`) after the title call and database save.
- Errors: 400 `{errors: [...]}` for failed checks, 401 for auth / missing key, 500 `{error}` otherwise
  (or an SSE `error` event once streaming has started).

**What happens to the model's answer before it is returned:** the XML is cut out of the answer with a
regular expression and two incoming/outgoing tag typos are repaired (`convertStringToXml`, ai.ts:1452-1460).
In streaming mode only, a layout (`generateLayout`, tools/ai/bpmnLayout.ts) is added when the XML has
no `bpmndi:BPMNDiagram` (ai.ts:530-536, 584-588). **Unsure:** the non-streaming path (`startResponse`)
does not call `generateLayout`, so for OpenRouterLLM (which strips bpmndi) a non-streamed answer would
seem to come back without a diagram section. Not tested.

## 4. What is saved in the database per thread

Saved by `saveNewThreadToDB` (ai.ts:824-891); schema in prisma/schema.prisma:

- `Thread`: `threadId` (UUID), `title` (from the second, title model call), `userId`, `lastEditedAt`.
- `ChatMessage` 1: `text` = **the user's `inputString` only**, `author = USER`, and (quick mode)
  `model` and the diagram.
- `ChatMessage` 2 (only when the model also wrote text, e.g. detail mode): `text` = the model's text
  part, `author = AI`, `model`, and the diagram.
- `Diagram` (linked to a chat message): `xmlContent` (after the cleanup in section 3),
  `jsonContent` (json format only), `previewImageSVG` (rendered with puppeteer).
- Samples are saved as extra `Diagram` rows on the same chat message (ai.ts:1011-1024).

**The full prompt sent to the model is NOT saved.** The system instructions, the example files,
the OpenRouter extras, the chat history, the PDF text and the DMN rules are not stored (the code says
so for PDF / DMN at ai.ts:68). The raw model answer, token counts, temperature and model version
are not stored either; only `"<name> (<format>)"`.

The only place where the full request and raw answer are written is the **debug file**: when
`PRODUCTION` is `"false"` (any upper/lower case, ai.ts:39; any other value, e.g. `True` or `dev`,
turns it off), every diagram call writes
`data/assistant/debug/generated/debug_<threadId>_<time>.html` with `ai_input` (the exact request
object), `ai_output` (the raw response), tokens, cost and timings (ai.ts:450-451, 1260-1284).
**Unsure:** before inserting it, the code removes `\n`, `\r`, `\"` escapes and backticks from that JSON
(ai.ts:1270-1272), so the saved text is not byte-identical to what was sent. Token counts and costs
are also printed to the console (`[AI-USAGE]` lines).

## 5. `.env` variables and setup steps

`.env` lives in `server/` and is read by `dotenv` (environment.ts). Variables:

| Variable | Required? | Used for |
|---|---|---|
| `OPENAI_API_KEY` | **yes, the server stops at start if missing** (`notFound`); may be empty (README) | ChatGPT, assistants |
| `GEMINI_API_KEY` | yes (same) | Gemini; also routes/brainstorm.ts |
| `GROKAI_API_KEY` | yes (same) | GrokAI |
| `CLAUDE_API_KEY` | yes (same) | Claude |
| `PRODUCTION` | yes | `"True"` = HTTPS, no `/dev` routes, invitation codes for signup, secure cookies; anything else = development. Debug files (section 4) only when the value is `false` |
| `JWT_SECRET` | yes | signs the JWTs and is also the key (via scrypt) that encrypts the stored user API keys (tools/encryption.ts:5); README: at least 32 random bytes, e.g. `openssl rand -hex 32` |
| `FRONTEND_URLS` | yes | comma-separated CORS origins, e.g. `http://localhost:4200` |
| `DATABASE_URL` | yes (read by Prisma, not by environment.ts) | e.g. `postgresql://postgres:<password>@localhost:5432/bpmn` |
| `OPENROUTER_API_KEY` | no (default empty) | without it, no OpenRouter model names exist |
| `OPENSOURCE_LLM_BASE_URL`, `OPENSOURCE_LLM_API_KEY` (default `ollama`) | no | only for the disabled `OpenSourceLLM` |
| `OPENSOURCE_CLOUD_BASE_URL`, `OPENSOURCE_CLOUD_API_KEY` | no | only for the disabled `OpenSourceCloudLLM` (and two test scripts) |
| `ASSEMBLYAI_API_KEY` | no | voice input in routes/brainstorm.ts only |

"Required" means the variable must exist; an empty value passes the check because
`notFound` only runs when the value is `undefined`. **Unsure:** whether an empty key then fails only
when that provider is called, or already when the SDK client is created at start (`new OpenAI({apiKey: ""})`
etc. in each constructor). Not tested.

Setup steps (README.md "Installation", "Configuration", "Usage"; package.json):

1. Node.js 18 or newer.
2. PostgreSQL installed and running; create a database, e.g. `psql -U postgres` then `CREATE DATABASE bpmn;`
   (docker-compose.yml uses the `postgres:16` image).
3. In `server/`: `npm install`. Its `postinstall` runs `npx prisma generate` (builds the Prisma client).
   Puppeteer downloads a Chrome for the SVG previews (tools/format/xml-svg.ts). **Unsure:** whether this
   download works on the thesis PC without extra steps.
4. Write `.env` with the variables above.
5. Create the tables: `npx prisma migrate dev` (local; 20 migrations in prisma/migrations/) or
   `npm run db:deploy` (= `npx prisma migrate deploy`, used in Docker).
6. Start: `npm start` (ts-node server.ts) or `npm run dev` (nodemon). Port 1207.
7. If `PRODUCTION=True`: put `certificates/key.pem` and `certificates/cert.pem` in place, and create
   invitation codes with `npm run db:generate-invites` before anyone can sign up.
8. Get a token (`POST /auth/signup` or `/auth/login`; a guest needs its own stored API key), then call
   `POST /threads` within 15 minutes.

## 6. What this means for the thesis

- Our generator (qwen3:8b on Ollama via `OpenSourceLLM`) is not reachable through `POST /threads`,
  because that class is commented out in `tools/useGPT.ts`. Enabling it would change a BPMNGen file.
  The closest enabled option, `qwen/qwen3.5-397b-a17b` on OpenRouter, is a different, much larger
  model, so it would break "same generator as in the finished runs".
- Even for enabled models, the route adds things our harness avoids on purpose: a database,
  login, a second title call, chat history, a second request on a length stop (OpenRouter), and
  different extra system text for OpenRouter models.
- The database does not keep the full prompt or the raw answer. To meet "save every input and output
  of every LLM call", we would have to rely on the debug HTML files, which are not byte-identical
  (section 4). Our harness (bpmngen_harness/run_bpmngen.ts) saves both exactly.
