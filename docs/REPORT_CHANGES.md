# Changes needed in the Interim 1 report (and for Chapter 3)

These are places where the report now disagrees with the experiment as built, or where it contradicts itself.
I didn't edit the .docx. Change these sentences yourself so the wording stays yours.

## A. The report no longer matches the design (because BPMNGen is now the generator)

1. **2.3.3, last paragraph.** It says: "The LLM produces a structured process representation under the same schema in C1, C2, and C3, after which a deterministic builder produces BPMN."
   Now: BPMNGen's qwen3:8b writes BPMN 2.0 XML directly. BPMNGen then applies a deterministic cleanup (fixes namespaces and quotes, and can add missing sequence flows). The same generator, prompt and cleanup are used in all three conditions.
   Suggested replacement: *"In this study the downstream generator is BPMNGen [10] with an open-weight model (qwen3:8b) served locally. The generator writes BPMN 2.0 XML directly and BPMNGen applies the same deterministic post-processing in every condition. Because this post-processing can add sequence flows the model did not produce, the number of such repairs is recorded per condition."*
2. **2.1, last paragraph.** "deterministic serialization and validation address syntactic reliability". Change to "deterministic post-processing and validation".
3. **Chapter 3 must state the fixed settings:** qwen3:8b with its exact Ollama digest, BPMNGen's system prompt unchanged, temperature 0.3 (BPMNGen default, no seed, hence 3 repetitions), context window 16,384 tokens, thinking disabled, one generation call per case, no retries.
4. **Chapter 3 must state the knowledge injection:** the knowledge is appended after the description under one neutral label, identical in C1/C2/C3. C1's block is "No domain knowledge provided." BPMNGen's own DMN option was not used, because it tells the model the rules "MUST" be followed.
5. **Chapter 3, mediation model:** the mediation agents use the same model as the generator (qwen3:8b, temperature 0). Say why: so C3 cannot gain from a stronger model.

## B. Contradictions inside the report (an examiner may notice these)

6. **Appendix Table 1A vs. the gap claim.** The table marks *Explicit mediation = "Yes"* for **Tarifa & Kouki** and **Sai & Rinderle-Ma**. Sections 2.6.2, 2.10 and 2.11 argue that agentic pipelines are *not* explicit applicability mediation. Either change those cells to "Partial" or "No" with a short reason, or explain in 2.11 why their "mediation" differs from yours (e.g. no case-specific applicability judgment). As it stands, your own table weakens your gap.
7. **Appendix Table 1A, BPMNGen framework row [10].** It marks *NL→BPMN = "Not established from reviewed source"*, but 2.3.1 says this work "addresses the transformation of natural-language process descriptions into BPMN 2.0 models". That should be "Yes".
8. **2.4 promises outcomes that are not all measured yet.** It lists "requirement coverage, unsupported additions, applicability accuracy, requirement-transformation fidelity, and provenance support" as distinct outcomes. Current state:
   - unsupported additions: implemented (extra tasks, plus a *provisional* "knowledge-traceable" count; threshold not calibrated yet)
   - provenance: saved for every C3 passage
   - applicability accuracy, requirement-transformation fidelity, requirement coverage (RQ3): **postponed**. They need validated labels, and AI-made labels may only be called provisional.
   Either plan RQ3 into the timeline or narrow the wording now.
9. **2.8 / RQ2.** With 13 cases, a moderation test has very little power. Call RQ2 *exploratory* in Chapter 3.

## C. Expectation to set in Chapter 3

10. The PMo reference models were drawn from the descriptions, not from EU law. A correct legal step added in C2/C3 therefore counts as an extra task and lowers precision. The realistic hypothesis for RQ1 is: C3 adds fewer unsupported (knowledge-traceable) tasks than C2 while keeping recall, i.e. C3 ≈ C1 > C2 on precision. It is not "C3 beats C1". State this before you see results, so it can't look like you chose it afterwards.
