"""C3 v2 development test of RelevanceAgent v2, on development cases only (docs/C3_V2_DEVELOPMENT.md).

For every frozen passage of every development case of both laws, RelevanceAgentV2 (qwen3:8b on Ollama, the agents'
settings in config.yaml: temperature 0, seed 42, thinking off) gives its answer, and RelevanceV2Checker checks the
two quotes and decides the final label. The result is compared with the silver labels and with v1's relevance answer
for the same passages:

  law           cases                                frozen retrieval                     silver                    v1 labels from
  consumer_law  cases.development_ids (13 Study 1)   paths.frozen_retrieval (Study 1)     paths.silver_reference    results/runs/ollama_rep1
  gdpr          study2_gdpr.development_ids (7)      study2_gdpr.frozen_retrieval (rerank) study2_gdpr.silver_reference_dev (rerank top 5)  results/runs/smoke_gdpr_dev

Silver-relevant = silver label applicable, indeterminate or not_applicable; silver-irrelevant = irrelevant.
Test cases (cases.test_ids) are refused. Nothing outside paths.relevance_v2_dev_dir/round<n>/ is written:
  answers_<law>.json   one record per passage: silver label, v1 answer, v2 answer, quote checks, final label
                       (written after every case; a rerun skips finished cases and never relabels them)
  logs/                every LLM call (RunLogger, condition c3_v2_dev.log_condition)
  metrics.json         per law and overall: silver x relevant tables, recall, specificity, quote checks, valid JSON,
                       the same for v1, and each success criterion (section 2.3) met / not met
  report.md            the same as readable tables

Run from the project root (Ollama running):  .venv\\Scripts\\python.exe -m src.relevance_v2_dev --round 1
"""

import argparse
import json
import sys
from pathlib import Path

from src.agents.relevance_agent_v2 import RelevanceAgentV2
from src.config import load_config, project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError
from src.logger import RunLogger
from src.mediation.relevance_v2_checker import RelevanceV2Checker
from src.study2_config import study2_view

SILVER_LABELS = ["applicable", "indeterminate", "not_applicable", "irrelevant"]
SILVER_RELEVANT = {"applicable", "indeterminate", "not_applicable"}


def law_setup(config: dict, law: str) -> dict:
    """Cases, frozen passages, silver labels and v1 run of one law (development cases only)."""
    if law == "consumer_law":
        view, case_ids = config, list(config["cases"]["development_ids"])
        silver_path, version = config["paths"]["silver_reference"], None
    elif law == "gdpr":
        view = study2_view(config)
        case_ids = list(config["study2_gdpr"]["development_ids"])
        silver_path, version = config["study2_gdpr"]["silver_reference_dev"], config["study2_gdpr"]["retrieval_version"]
    else:
        raise ValueError(f"unknown law {law!r}")
    test_cases = [c for c in case_ids if c in config["cases"]["test_ids"]]
    if test_cases:
        raise ValueError(f"test cases are never used in C3 v2 development: {test_cases}")
    frozen = json.loads(project_path(view["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
    silver = json.loads(project_path(silver_path).read_text(encoding="utf-8"))
    labels = {}
    for case_id in case_ids:
        in_version = set(silver["case_versions"][case_id][version]) if version else None
        for p in silver["cases"][case_id]["passages"]:
            if in_version is None or p["passage_id"] in in_version:
                labels[(case_id, p["passage_id"])] = p["label"]
    return {"case_ids": case_ids, "frozen": frozen, "silver": labels,
            "v1_dir": project_path(view["paths"]["runs"]) / config["c3_v2_dev"]["v1_runs"][law] / "C3" /
            view["paths"]["mediation_dir"]}


def v1_answers(v1_dir: Path, case_id: str) -> dict:
    """v1's relevance answer per passage of a case: {passage_id: True / False / None (v1 failed)}."""
    path = v1_dir / f"{case_id}.json"
    if not path.exists():
        return {}
    passages = json.loads(path.read_text(encoding="utf-8"))["passages"]
    return {p["passage_id"]: (p["relevance"] or {}).get("relevant") for p in passages}


def law_metrics(records: list[dict], key: str) -> dict:
    """Silver label x relevant table, recall and specificity for one relevance key ("v2_relevant" or "v1_relevant")."""
    table = {label: {"relevant": 0, "irrelevant": 0} for label in SILVER_LABELS}
    for r in records:
        table[r["silver_label"]]["relevant" if r[key] else "irrelevant"] += 1
    n_rel = sum(table[l]["relevant"] + table[l]["irrelevant"] for l in SILVER_RELEVANT)
    found = sum(table[l]["relevant"] for l in SILVER_RELEVANT)
    n_irr = table["irrelevant"]["relevant"] + table["irrelevant"]["irrelevant"]
    wrong = table["irrelevant"]["relevant"]
    return {"table": table, "n_silver_relevant": n_rel, "silver_relevant_found": found,
            "recall": round(found / n_rel, 4) if n_rel else None,
            "n_silver_irrelevant": n_irr, "silver_irrelevant_called_relevant": wrong,
            "specificity": round((n_irr - wrong) / n_irr, 4) if n_irr else None}


def quote_metrics(records: list[dict]) -> dict:
    """Code check of v2's quotes (non-empty quotes only) and valid JSON after the retry."""
    found = [r["v2"][k] for r in records if r["v2"] for k in ("law_quote_found", "description_quote_found")
             if r["v2"][k] is not None]
    by_kind = {k: [r["v2"][k] for r in records if r["v2"] and r["v2"][k] is not None]
               for k in ("law_quote_found", "description_quote_found")}
    valid = sum(r["valid_json"] for r in records)
    return {"quotes_checked": len(found), "quotes_failed": found.count(False),
            "evidence": round(found.count(True) / len(found), 4) if found else None,
            "law_quotes_failed": by_kind["law_quote_found"].count(False),
            "description_quotes_failed": by_kind["description_quote_found"].count(False),
            "answers": len(records), "valid_json": valid,
            "stability": round(valid / len(records), 4) if records else None}


def criteria_result(per_law: dict, overall: dict, criteria: dict) -> dict:
    """Each success criterion of section 2.3: met / not met (1 and 2 per law, 3 = all of them, 4 and 5 overall)."""
    result = {}
    for law, m in per_law.items():
        result[f"1_recall_{law}"] = m["v2"]["recall"] is not None and m["v2"]["recall"] >= criteria["recall"]
        result[f"2_specificity_{law}"] = (m["v2"]["specificity"] is not None
                                          and m["v2"]["specificity"] >= criteria["specificity"])
    result["3_generality"] = all(result.values())
    result["4_evidence"] = overall["evidence"] is not None and overall["evidence"] >= criteria["evidence"]
    result["5_stability"] = overall["stability"] is not None and overall["stability"] >= criteria["stability"]
    return result


class RelevanceV2Dev:
    """Runs RelevanceAgentV2 on the development passages of both laws and scores it."""

    def __init__(self, config: dict, round_no: int, llm: LLMClient | None = None):
        settings = config["c3_v2_dev"]
        if not 1 <= round_no <= settings["max_rounds"]:
            raise ValueError(f"round must be between 1 and {settings['max_rounds']} (c3_v2_dev.max_rounds)")
        self.config, self.round_no, self.laws, self.criteria = config, round_no, settings["laws"], settings["criteria"]
        self.out_dir = project_path(config["paths"]["relevance_v2_dev_dir"]) / f"round{round_no}"
        self.cases_dir = project_path(config["paths"]["cases"])
        self.description_file = config["paths"]["case_description_file"]
        self.llm = llm
        self.checker = RelevanceV2Checker()

    def answers_path(self, law: str) -> Path:
        return self.out_dir / f"answers_{law}.json"

    def run_law(self, law: str) -> list[dict]:
        setup = law_setup(self.config, law)
        path = self.answers_path(law)
        records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        done = {r["case_id"] for r in records}
        logger = RunLogger(self.out_dir / "logs", self.config["c3_v2_dev"]["log_condition"],
                           f"round{self.round_no}_{law}", part=1 + len(list((self.out_dir / "logs").glob(
                               f"{self.config['c3_v2_dev']['log_condition']}_round{self.round_no}_{law}*.jsonl"))))
        agent = RelevanceAgentV2(self.llm, logger)
        for case_id in setup["case_ids"]:
            if case_id in done:
                continue
            description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
            v1 = v1_answers(setup["v1_dir"], case_id)
            for passage in sorted(setup["frozen"][case_id]["passages"], key=lambda p: p["rank"]):
                pid, text = passage["passage_id"], passage["text"]
                answer = agent.run(case_id, description=description, passage_id=pid, passage_text=text)
                checked = self.checker.check(answer, text, description) if answer else None
                records.append({"law": law, "case_id": case_id, "rank": passage["rank"], "passage_id": pid,
                                "silver_label": setup["silver"][(case_id, pid)], "v1_relevant": bool(v1.get(pid)),
                                "v1_answer": v1.get(pid), "valid_json": answer is not None, "v2": checked,
                                "v2_relevant": bool(checked and checked["final_relevant"])})
            self.out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        return records

    def metrics(self, records_by_law: dict) -> dict:
        per_law = {law: {"v2": law_metrics(r, "v2_relevant"), "v1": law_metrics(r, "v1_relevant"),
                         "quotes": quote_metrics(r)} for law, r in records_by_law.items()}
        overall = quote_metrics([r for records in records_by_law.values() for r in records])
        return {"round": self.round_no, "per_law": per_law, "overall_quotes": overall,
                "criteria_thresholds": self.criteria,
                "criteria": criteria_result(per_law, overall, self.criteria)}

    def report(self, metrics: dict) -> str:
        lines = [f"# RelevanceAgent v2, development round {self.round_no}", "",
                 "Silver is AI-made and provisional: these numbers are agreement with a stronger model, not correctness.",
                 ""]
        for law, m in metrics["per_law"].items():
            lines += [f"## {law}", "", "| silver label | v2 relevant | v2 irrelevant | v1 relevant | v1 irrelevant |",
                      "|---|---|---|---|---|"]
            for label in SILVER_LABELS:
                v2, v1 = m["v2"]["table"][label], m["v1"]["table"][label]
                lines.append(f"| {label} | {v2['relevant']} | {v2['irrelevant']} | {v1['relevant']} | {v1['irrelevant']} |")
            q = m["quotes"]
            lines += ["", f"- v2: silver-relevant found {m['v2']['silver_relevant_found']}/{m['v2']['n_silver_relevant']} "
                          f"(recall {m['v2']['recall']}); silver-irrelevant called relevant "
                          f"{m['v2']['silver_irrelevant_called_relevant']}/{m['v2']['n_silver_irrelevant']} "
                          f"(specificity {m['v2']['specificity']})",
                      f"- v1: silver-relevant found {m['v1']['silver_relevant_found']}/{m['v1']['n_silver_relevant']} "
                      f"(recall {m['v1']['recall']}); silver-irrelevant called relevant "
                      f"{m['v1']['silver_irrelevant_called_relevant']}/{m['v1']['n_silver_irrelevant']} "
                      f"(specificity {m['v1']['specificity']})",
                      f"- quotes failed the code check: {q['quotes_failed']}/{q['quotes_checked']} (law_quote "
                      f"{q['law_quotes_failed']}, description_quote {q['description_quotes_failed']}); valid JSON "
                      f"{q['valid_json']}/{q['answers']}", ""]
        o = metrics["overall_quotes"]
        lines += ["## Success criteria (section 2.3)", "",
                  f"Overall quotes: {o['quotes_checked'] - o['quotes_failed']}/{o['quotes_checked']} found "
                  f"(evidence {o['evidence']}); valid JSON {o['valid_json']}/{o['answers']} (stability {o['stability']})",
                  "", "| criterion | met |", "|---|---|"]
        lines += [f"| {name} | {'yes' if met else 'no'} |" for name, met in metrics["criteria"].items()]
        return "\n".join(lines) + "\n"

    def run(self) -> dict:
        records = {law: self.run_law(law) for law in self.laws}
        metrics = self.metrics(records)
        (self.out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (self.out_dir / "report.md").write_text(self.report(metrics), encoding="utf-8")
        return metrics


def main() -> None:
    from run_experiment import create_llm   # the same agent client as C3 (provider, model, digest check)
    parser = argparse.ArgumentParser(description="C3 v2 development test of RelevanceAgent v2.")
    parser.add_argument("--round", type=int, required=True)
    args = parser.parse_args()
    config = load_config()
    try:
        dev = RelevanceV2Dev(config, args.round, create_llm(config, "relevance"))
        metrics = dev.run()
    except (ValueError, LLMUnavailableError) as e:
        sys.exit(f"Stopped: {e}\nRun the same command again to continue with the unfinished cases.")
    print(dev.report(metrics))


if __name__ == "__main__":
    main()
