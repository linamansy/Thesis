/**
 * run_bpmngen.ts — calls BPMNGen's OpenSourceLLM (Ollama) generator for ONE case,
 * WITHOUT the web server, database or login, and WITHOUT modifying any BPMNGen file.
 *
 * Why this file exists (thesis): BPMNGen is the fixed generator for C1, C2 and C3.
 * The normal route (POST /threads) needs PostgreSQL, a user account and the frontend,
 * and the Ollama class is switched off in tools/useGPT.ts. This harness imports
 * BPMNGen's own classes and runs the same steps createBPMN() runs:
 *   build prompt -> mapPromptInput -> generateContent (Ollama + BPMNGen's XML cleanup)
 *   -> processResponse -> convertResponseToDiagramOutput -> validateBpmnXml
 * Only the DB steps (thread, history, title, saving) are skipped. History is empty,
 * exactly like a brand-new thread.
 *
 * It also records the exact HTTP request sent to Ollama and the raw model output
 * (before BPMNGen's cleanup), plus Ollama's token counts and done_reason, so we can
 * prove the prompt fitted in the context window.
 *
 * Run it FROM the BPMNGen server folder (BPMNGen reads its prompt files relative to it):
 *   cd <BPMNGen-backend>/server
 *   npx ts-node --transpile-only <Thesis-BPMN>/bpmngen_harness/run_bpmngen.ts \
 *       --description <Thesis-BPMN>/data/cases/01/description.txt \
 *       --out <Thesis-BPMN>/results/bpmngen_smoke/C1/01 \
 *       --base-url http://localhost:11434 --model qwen3:8b
 * Optional: --knowledge <file.txt>  knowledge block (run_experiment.py always passes one; C1's is
 *           "No domain knowledge provided.", so C1/C2/C3 have the same layout)
 *           --label "<text>"         neutral label in front of the block (config.yaml generator.knowledge_label)
 *           --think false            Ollama's own thinking switch, added to BPMNGen's request (config.yaml
 *                                    generator.think_param). BPMNGen asks for no thinking with "/no_think" in the
 *                                    prompt, but newer Ollama versions let qwen3 think anyway and return the
 *                                    thinking in a separate field BPMNGen never reads (found 18 Oct 2026).
 *                                    think:false makes Ollama do what BPMNGen intends. No BPMNGen file is changed.
 *           --list-files             no generation and no Ollama call: load BPMNGen, build a prompt, and print the
 *                                    BPMNGen files Node loaded or read, as one JSON line {"bpmngen_files": [...]}.
 *                                    src/bpmngen_files.py hashes them for run_info.json (audit 19 Oct 2026).
 *
 * Two safety rules (thesis decision 18 Oct 2026), both recorded in meta.json:
 *   - thinking text: Ollama's separate "thinking" field is always saved (raw_thinking.txt) and counted;
 *     raw_has_think_block is true if thinking appears in the answer (<think> or </think>) OR in that field.
 *   - cut-off: if the streamed output passes the context window (num_ctx tokens), the request is aborted
 *     (Ollama then stops generating) and the case is a FAILED generation: done_reason "cut_off_by_harness",
 *     context_limit_hit true. Without this, qwen3 could loop for an hour (Ollama keeps going past num_ctx).
 */
import * as fs from "fs";
import * as path from "path";

// ---------- 1. read command-line arguments ----------
function arg(name: string, fallback?: string): string | undefined {
    const i = process.argv.indexOf(`--${name}`);
    return i >= 0 ? process.argv[i + 1] : fallback;
}
const descriptionFile = arg("description");
const knowledgeFile = arg("knowledge");
const outDir = arg("out");
const baseUrl = arg("base-url", "http://localhost:11434")!;
const model = arg("model", "qwen3:8b")!;
// PROVISIONAL neutral label (to be agreed with supervisors / Ulm). Same text for C2 and C3.
const knowledgeLabel = arg("label", "[Domain information (it may or may not apply to this process):]")!;
const thinkArg = arg("think");  // "false" / "true"; not given = BPMNGen's request is sent unchanged
const thinkParam: boolean | undefined = thinkArg === undefined ? undefined : thinkArg === "true";
const listFiles = process.argv.includes("--list-files");
if (!listFiles && (!descriptionFile || !outDir)) {
    console.error("Usage: --description <file> --out <dir> [--knowledge <file>] [--base-url URL] [--model NAME]");
    process.exit(2);
}

// ---------- 2. environment BPMNGen needs at import time ----------
// environment.ts throws if these are undefined. They are NOT used by the Ollama path.
for (const k of ["OPENAI_API_KEY", "GEMINI_API_KEY", "GROKAI_API_KEY", "CLAUDE_API_KEY", "JWT_SECRET"]) {
    if (process.env[k] === undefined) process.env[k] = "unused-by-harness";
}
if (process.env.PRODUCTION === undefined) process.env.PRODUCTION = "False";
if (process.env.FRONTEND_URLS === undefined) process.env.FRONTEND_URLS = "http://localhost:4200";
process.env.OPENSOURCE_LLM_BASE_URL = baseUrl;

// ---------- 3. record (and minimally adjust) the Ollama request; read the stream ----------
type Captured = { url: string; requestBody: any; rawContent: string; rawThinking: string; finalChunk: any;
                  streamedTokens: number; cutOff: boolean };
const captured: Captured[] = [];
class ContextLimitCutOff extends Error {}
const realFetch = globalThis.fetch;
globalThis.fetch = (async (url: any, init?: any) => {
    if (!String(url).includes("/api/chat")) return realFetch(url, init);
    const body = JSON.parse(init?.body ?? "{}");
    if (thinkParam !== undefined) body.think = thinkParam;  // the ONLY change to BPMNGen's request
    const numCtx: number | undefined = body.options?.num_ctx;
    const rec: Captured = { url: String(url), requestBody: body, rawContent: "", rawThinking: "", finalChunk: null,
                            streamedTokens: 0, cutOff: false };
    captured.push(rec);
    const controller = new AbortController();
    const resp = await realFetch(url, { ...init, body: JSON.stringify(body), signal: controller.signal });
    if (!resp.ok || !resp.body) return resp;  // BPMNGen reports HTTP errors itself ("Ollama error ...")

    // Ollama streams one JSON object per line, about one token each. Read it as it arrives, so a
    // runaway answer can be stopped instead of waiting for it to end.
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let all = "", pending = "";
    const handle = (line: string) => {
        if (!line.trim()) return;
        try {
            const c = JSON.parse(line);
            if (c.message?.content) { rec.rawContent += c.message.content; rec.streamedTokens++; }
            if (c.message?.thinking) { rec.rawThinking += c.message.thinking; rec.streamedTokens++; }
            if (c.done) rec.finalChunk = c;
        } catch { /* ignore */ }
    };
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const text = decoder.decode(value, { stream: true });
        all += text;
        pending += text;
        const lines = pending.split("\n");
        pending = lines.pop() ?? "";
        lines.forEach(handle);
        if (numCtx && rec.streamedTokens > numCtx) {
            rec.cutOff = true;
            controller.abort();  // closes the connection: Ollama stops generating
            throw new ContextLimitCutOff(`output passed the context window (${rec.streamedTokens} > ${numCtx} tokens)`);
        }
    }
    handle(pending);
    // give BPMNGen an identical response body to parse
    return new Response(all, { status: resp.status, headers: resp.headers });
}) as any;

// ---------- 4. load BPMNGen (cwd must be the BPMNGen server folder) ----------
const serverDir = process.cwd();
// --list-files only: remember every file read through fs.readFileSync (e.g. prompt files), so the files BPMNGen
// reads are hashed too, not only its modules. Not installed for a generation, which therefore runs unchanged.
const filesRead = new Set<string>();
if (listFiles) {
    const realFs = require("fs");  // the shared module object, so BPMNGen's reads go through the wrapper
    const realRead = realFs.readFileSync;
    realFs.readFileSync = function (file: any, ...rest: any[]) {
        const content = realRead.call(realFs, file, ...rest);  // throws for a file that does not exist
        if (typeof file === "string") filesRead.add(path.resolve(file));  // so only files really read are kept
        return content;
    };
}
// BPMNGen's own files among the given absolute paths: inside the server folder, not in node_modules;
// returned relative to the server folder with "/" separators, sorted.
function bpmngenFiles(paths: Iterable<string>): string[] {
    const inside = [...paths].map((p) => path.relative(serverDir, p))
        .filter((rel) => rel && !rel.startsWith("..") && !path.isAbsolute(rel)
                         && !rel.split(path.sep).includes("node_modules"));
    return [...new Set(inside.map((rel) => rel.split(path.sep).join("/")))].sort();
}
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { OpenSourceLLM } = require(path.join(serverDir, "tools/ai/opensource"));
const { Ai, PromptInput } = require(path.join(serverDir, "tools/ai/ai"));
const { validateBpmnXml } = require(path.join(serverDir, "tools/utils/xml-validator"));

async function main() {
    if (listFiles) {
        // Build a prompt exactly as below (no Ollama call), so prompt files BPMNGen reads are seen as well.
        const mode = "quick";
        const instructions = [].concat((Ai as any).formatInstructions("xml", mode), (Ai as any).modeInstructions(mode));
        new OpenSourceLLM(model, "xml").mapPromptInput(new PromptInput(instructions, "list files", undefined, [], ""),
                                                       mode, false);
        const loaded = [...Object.keys(require.cache), ...filesRead];
        console.log(JSON.stringify({ bpmngen_files: bpmngenFiles(loaded) }));
        return;
    }
    const description = fs.readFileSync(descriptionFile!, "utf8").trim();
    const knowledge = knowledgeFile ? fs.readFileSync(knowledgeFile, "utf8").trim() : "";

    // Same construction as Ai.createBPMN(): prompt + appended context block.
    const aiPrompt = knowledge ? `${description}\n\n${knowledgeLabel}\n${knowledge}` : description;
    const mode = "quick";
    const fmt = "xml"; // the Ollama class always produces XML
    const instructions = [].concat((Ai as any).formatInstructions(fmt, mode), (Ai as any).modeInstructions(mode));
    const promptInput = new PromptInput(instructions, aiPrompt, undefined, [], "");

    const llm = new OpenSourceLLM(model, fmt);
    const t0 = Date.now();
    const input = llm.mapPromptInput(promptInput, mode, false);
    let cleaned: string | null = null, diagram: any = null, validation: any = null;
    try {
        const output = await llm.generateContent(input, mode, false);
        cleaned = llm.processResponse(output);
        diagram = (Ai as any).convertResponseToDiagramOutput(cleaned, fmt, mode);
        validation = await validateBpmnXml(diagram?.xml);
    } catch (e) {
        if (!(e instanceof ContextLimitCutOff)) throw e;  // anything else: harness failure (exit code 1)
        console.error(`Cut off: ${e.message}`);
    }
    const seconds = (Date.now() - t0) / 1000;

    fs.mkdirSync(outDir!, { recursive: true });
    const call = captured[captured.length - 1];
    const fc = call?.finalChunk ?? {};
    const numCtx = call?.requestBody?.options?.num_ctx;
    const cutOff = call?.cutOff ?? false;
    const thinking = call?.rawThinking ?? "";
    const thinkTags = ((call?.rawContent ?? "").match(/<\/?think>/gi) ?? []).length;
    const meta = {
        model, base_url: baseUrl, mode, format: fmt,
        knowledge_file: knowledgeFile ?? null, knowledge_label: knowledge ? knowledgeLabel : null,
        num_ctx: numCtx, temperature: call?.requestBody?.options?.temperature ?? null,
        think_param: call?.requestBody?.think ?? null,  // what was sent to Ollama (null = not sent)
        ollama_model_reported: fc.model ?? null,
        prompt_tokens: fc.prompt_eval_count ?? null,
        // cut off: Ollama sends no final counts, so the tokens streamed until the abort are reported
        output_tokens: cutOff ? call.streamedTokens : (fc.eval_count ?? null),
        done_reason: cutOff ? "cut_off_by_harness" : (fc.done_reason ?? null),
        fits_context: cutOff ? false
            : (fc.prompt_eval_count != null && numCtx ? (fc.prompt_eval_count + (fc.eval_count ?? 0)) < numCtx : null),
        cut_off_by_harness: cutOff,
        // thinking in the answer (<think> or </think> tags) OR in Ollama's separate thinking field; should be
        // none with think:false. qwen3 can still write a draft and then "</think>" without an opening tag
        // (smoke test 18 Oct 2026), so closing tags count too. Nothing is repaired; it is only flagged.
        raw_has_think_block: thinkTags > 0 || thinking.length > 0,
        think_tags_in_answer: thinkTags,
        thinking_chars: thinking.length,
        // BPMNGen's cleanup can ADD structure the model did not produce. Count it per run,
        // because it affects order/logic metrics and must be reported per condition.
        auto_repairs: {
            auto_flows_added: ((diagram?.xml ?? "").match(/id="auto_flow_/g) ?? []).length,
            auto_links_added: ((diagram?.xml ?? "").match(/id="auto_link_/g) ?? []).length,
            first_task_inserted: /_firstTask"/.test(diagram?.xml ?? ""),
        },
        valid: validation ? validation.valid : false, seconds,
        timestamp: new Date().toISOString(),
    };
    fs.writeFileSync(path.join(outDir!, "ollama_request.json"), JSON.stringify(call?.requestBody ?? null, null, 2));
    fs.writeFileSync(path.join(outDir!, "raw_model_output.txt"), call?.rawContent ?? "");
    fs.writeFileSync(path.join(outDir!, "raw_thinking.txt"), thinking);
    if (!cutOff) {  // a cut-off answer has no model: no cleaned output, BPMN or BPMNGen validation
        fs.writeFileSync(path.join(outDir!, "bpmngen_cleaned_output.txt"), cleaned ?? "");
        fs.writeFileSync(path.join(outDir!, "generated.bpmn"), diagram?.xml ?? "");
        fs.writeFileSync(path.join(outDir!, "validation.json"), JSON.stringify(validation, null, 2));
    }
    fs.writeFileSync(path.join(outDir!, "meta.json"), JSON.stringify(meta, null, 2));
    console.log(JSON.stringify(meta, null, 2));
}

main().catch((e) => { console.error("Harness failed:", e); process.exit(1); });
