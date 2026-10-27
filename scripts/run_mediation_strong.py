"""Stronger-model mediation diagnostic (docs/MEDIATION_TEST_CRITERIA.md section 6). MEASUREMENT ONLY.

The same mediation test as src/mediation_test.py (C3 v2 agents, same prompts, same code rules, no BPMN generation), but:
  - setting O only, the 8 development variants + their base cases (mediation_test.development_variants)
  - the C3 agents use the Groq model in config.yaml c3_agents_llm.groq (switched in memory; the file keeps ollama)
Only the target passage of each variant and base case is mediated (Groq free-tier rate limits; the other 4 passages are
still given to the second look); T3/T4 are not measured. The result decides only whether the model is the bottleneck; nothing is changed because of it.

Outputs in c3_agents_llm.groq.output_dir/<model id>/dev/: answers.json, logs/ (every LLM call, RunLogger),
metrics.json, report.md, progress.txt (one line per passage), connection_retries.json (every 429 wait).
Groq answers are cached (c3_agents_llm.groq.cache_dir), so a rerun resends nothing and skips finished case runs.

Run from the project root:  .venv\\Scripts\\python.exe -m scripts.run_mediation_strong
"""

import contextlib
import copy
import json

from run_experiment import create_llm
from src.config import load_config, project_path
from src.mediation_test import run


def main() -> None:
    config = copy.deepcopy(load_config())
    config["c3_agents_llm"]["provider"] = "groq"
    groq = config["c3_agents_llm"]["groq"]
    llm = create_llm(config, "relevance", {})   # one client for all three agents
    out_dir = project_path(groq["output_dir"]) / groq["model"].replace("/", "__") / "dev"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "progress.txt", "a", encoding="utf-8") as progress, contextlib.redirect_stdout(progress):
        m = run(config, "dev", llm=llm, out_dir=out_dir, run_settings=("O",), model_label=f"{groq['model']} on Groq",
                 target_only=True)
    (out_dir / "connection_retries.json").write_text(json.dumps(
        {"connection_retries": llm.connection_retries, "cache_hits": llm.cache_hits}, indent=2), encoding="utf-8")

    s, rows = m["summary"], m["per_variant"]
    n = s["n_variants"]
    print(f"Model {groq['model']} (Groq), setting O, target passage only, {n} development variants + base cases")
    print(f"T1 target hit   {s['T1_hits']}/{n}  (target >= 6/8)")
    print(f"T2 control      {s['T2_pass']}/{n}  (target >= 7/8)")
    for r in rows:
        boxes = [b for x in m["misses"] if x["measure"] in ("T1", "T2") and x["variant"] == r["variant"]
                 for b in [f"{x['measure']}: " + "; ".join(x["boxes"])]]
        print(f"{r['variant']} {r['target']}: {r['O_variant_target_label']} (base {r['O_base_target_label']})"
              f" - {' | '.join(boxes) or 'hit'}"[:300])
    print(f"Saved in {out_dir}")


if __name__ == "__main__":
    main()
