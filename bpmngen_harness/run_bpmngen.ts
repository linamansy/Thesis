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
if (!descriptionFile || !outDir) {
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

// ---------- 3. record the exact Ollama request and raw stream ----------
type Captured = { url: string; requestBody: any; rawContent: string; finalChunk: any };
const captured: Captured[] = [];
const realFetch = globalThis.fetch;
globalThis.fetch = (async (url: any, init?: any) => {
    const resp = await realFetch(url, init);
    if (!String(url).includes("/api/chat")) return resp;
    const text = await resp.text(); // Ollama streams NDJSON; read it all
    const rec: Captured = { url: String(url), requestBody: JSON.parse(init?.body ?? "{}"), rawContent: "", finalChunk: null };
    for (const line of text.split("\n")) {
        if (!line.trim()) continue;
        try {
            const c = JSON.parse(line);
            if (c.message?.content) rec.rawContent += c.message.content;
            if (c.done) rec.finalChunk = c;
        } catch { /* ignore */ }
    }
    captured.push(rec);
    // give BPMNGen an identical response body to parse
    return new Response(text, { status: resp.status, headers: resp.headers });
}) as any;

// ---------- 4. load BPMNGen (cwd must be the BPMNGen server folder) ----------
const serverDir = process.cwd();
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { OpenSourceLLM } = require(path.join(serverDir, "tools/ai/opensource"));
const { Ai, PromptInput } = require(path.join(serverDir, "tools/ai/ai"));
const { validateBpmnXml } = require(path.join(serverDir, "tools/utils/xml-validator"));

async function main() {
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
    const output = await llm.generateContent(input, mode, false);
    const cleaned: string = llm.processResponse(output);
    const diagram = (Ai as any).convertResponseToDiagramOutput(cleaned, fmt, mode);
    const validation = await validateBpmnXml(diagram?.xml);
    const seconds = (Date.now() - t0) / 1000;

    fs.mkdirSync(outDir!, { recursive: true });
    const call = captured[captured.length - 1];
    const fc = call?.finalChunk ?? {};
    const numCtx = call?.requestBody?.options?.num_ctx;
    const meta = {
        model, base_url: baseUrl, mode, format: fmt,
        knowledge_file: knowledgeFile ?? null, knowledge_label: knowledge ? knowledgeLabel : null,
        num_ctx: numCtx, temperature: call?.requestBody?.options?.temperature ?? null,
        ollama_model_reported: fc.model ?? null,
        prompt_tokens: fc.prompt_eval_count ?? null, output_tokens: fc.eval_count ?? null,
        done_reason: fc.done_reason ?? null,
        fits_context: fc.prompt_eval_count != null && numCtx ? (fc.prompt_eval_count + (fc.eval_count ?? 0)) < numCtx : null,
        raw_has_think_block: /<think>/i.test(call?.rawContent ?? ""),
        // BPMNGen's cleanup can ADD structure the model did not produce. Count it per run,
        // because it affects order/logic metrics and must be reported per condition.
        auto_repairs: {
            auto_flows_added: ((diagram?.xml ?? "").match(/id="auto_flow_/g) ?? []).length,
            auto_links_added: ((diagram?.xml ?? "").match(/id="auto_link_/g) ?? []).length,
            first_task_inserted: /_firstTask"/.test(diagram?.xml ?? ""),
        },
        valid: validation.valid, seconds,
        timestamp: new Date().toISOString(),
    };
    fs.writeFileSync(path.join(outDir!, "ollama_request.json"), JSON.stringify(call?.requestBody ?? null, null, 2));
    fs.writeFileSync(path.join(outDir!, "raw_model_output.txt"), call?.rawContent ?? "");
    fs.writeFileSync(path.join(outDir!, "bpmngen_cleaned_output.txt"), cleaned ?? "");
    fs.writeFileSync(path.join(outDir!, "generated.bpmn"), diagram?.xml ?? "");
    fs.writeFileSync(path.join(outDir!, "validation.json"), JSON.stringify(validation, null, 2));
    fs.writeFileSync(path.join(outDir!, "meta.json"), JSON.stringify(meta, null, 2));
    console.log(JSON.stringify(meta, null, 2));
}

main().catch((e) => { console.error("Harness failed:", e); process.exit(1); });
