"""Count how many tokens a generator prompt has, to check that it fits in the context window (llm.num_ctx).

Ollama silently cuts off the beginning of a prompt that is longer than num_ctx, so this must be
checked before the real runs. The prompt is built exactly as in run_experiment.py (same template,
same knowledge block) and sent to the local Ollama model with an answer of only 1 token; Ollama
reports the prompt length in the model's own tokens (prompt_eval_count, including the chat template).

Usage (C1 and C2 only: the C3 knowledge block exists only after mediation):
    .venv\\Scripts\\python.exe -m src.count_prompt_tokens --condition C2 --cases 19

Before counting, the model is unloaded from memory (POST /api/generate with keep_alive 0), so that no
cached part of an earlier prompt makes the count smaller. The result is saved to
results/context_check/<condition>_<case_id>.json.
"""

import argparse
import json
from datetime import datetime, timezone

from src.config import load_config, project_path
from src.generator import NO_KNOWLEDGE_TEXT, BPMNGenerator, format_passages
from src.llm.ollama_llm import OllamaLLM


def build_prompt(config: dict, condition: str, case_id: str) -> str:
    """The generator prompt of one case, exactly as the experiment builds it."""
    paths = config["paths"]
    description = (project_path(paths["cases"]) / case_id / paths["case_description_file"]).read_text(encoding="utf-8")
    if condition == "C1":
        knowledge = NO_KNOWLEDGE_TEXT
    else:
        frozen = json.loads(project_path(paths["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
        knowledge = format_passages(frozen[case_id]["passages"])
    generator = BPMNGenerator(llm=None, logger=None)   # only its prompt template is used: no LLM call
    return generator.build_prompt(description=description, knowledge_block=knowledge)


def main() -> None:
    config = load_config()
    if config["llm"]["provider"] != "ollama":
        raise SystemExit("llm.provider must be ollama in config.yaml")
    parser = argparse.ArgumentParser(description="Count the tokens of generator prompts with the Ollama model.")
    parser.add_argument("--condition", required=True, choices=["C1", "C2"])
    parser.add_argument("--cases", nargs="+", default=config["cases"]["ids"])
    args = parser.parse_args()

    llm = OllamaLLM.from_config(config)
    num_ctx, max_tokens = llm.num_ctx, llm.max_tokens
    llm.max_tokens = 1   # only the prompt is of interest
    out_dir = project_path("results/context_check")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'case':<6}{'prompt tokens':>15}{'room left for answer':>23}  (num_ctx {num_ctx}, max_tokens {max_tokens})")
    for case_id in args.cases:
        llm.client.post("/api/generate", json={"model": llm.model, "keep_alive": 0})   # unload: empty cache
        prompt = build_prompt(config, args.condition, case_id)
        llm.complete(prompt)
        tokens = llm.last_prompt_tokens
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "condition": args.condition,
                  "case_id": case_id, "model": llm.model, "model_digest": llm.model_digest,
                  "prompt_chars": len(prompt), "prompt_tokens": tokens, "num_ctx": num_ctx,
                  "max_tokens": max_tokens, "fits_with_full_answer": tokens + max_tokens <= num_ctx,
                  "prompt": prompt}
        (out_dir / f"{args.condition}_{case_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"{case_id:<6}{tokens:>15}{num_ctx - tokens:>23}")


if __name__ == "__main__":
    main()
