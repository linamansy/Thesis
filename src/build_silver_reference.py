"""Build the silver legal reference ONCE, before any experiment run, and freeze it (like the retrieval).

For every working case and every one of its 5 frozen passages, SilverAnnotator (Gemini, see
src/agents/silver_annotator.py) labels the passage applicable / not_applicable / indeterminate / irrelevant
and lists the process steps it requires. Code then:
  - checks every evidence quote against the description (QuoteChecker) and records the result
  - removes required_steps from passages that are not "applicable" and possible_steps from passages that are
    not "indeterminate", so the file is always consistent
Output: data/silver/silver_reference.json with, per case, the passages and the list of required steps, plus
the annotator model version, the prompt checksum and the frozen-retrieval checksum (proof of what it used).

Rules:
  - It reads only descriptions and frozen passages. It never reads a generated model or a C3 output.
  - Resumable: finished cases are kept and skipped; rerun the same command after an API stop.
  - Labels are SILVER (AI-made, not human-checked). Report them as provisional.

Run from the project root:
  .venv\\Scripts\\python.exe -m src.build_silver_reference
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents.silver_annotator import SilverAnnotator
from src.config import load_config, project_path
from src.llm.base_llm import LLMClient, LLMUnavailableError
from src.llm.gemini_llm import GeminiLLM
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.quote_checker import QuoteChecker

STATUS = "silver: AI-made reference, not checked by a human (provisional, never gold)"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_annotator_llm(config: dict) -> LLMClient:
    """The annotator's LLM: config.yaml silver section (mock in tests)."""
    silver = config["silver"]
    if config["llm"]["provider"] == "mock":  # THESIS_FORCE_MOCK (tests)
        answer = project_path(config["paths"]["mock_silver_response"]).read_text(encoding="utf-8")
        return MockLLM([answer])
    if silver["provider"] != "gemini":
        raise ValueError(f"silver.provider must be gemini, not {silver['provider']!r}")
    annotator_config = dict(config, llm=dict(config["llm"], model=silver["model"],
                                             temperature=silver["temperature"], max_tokens=silver["max_tokens"]))
    return GeminiLLM.from_config(annotator_config)


class SilverReferenceBuilder:
    def __init__(self, config: dict, annotator: SilverAnnotator, output_path: Path):
        paths = config["paths"]
        self.config = config
        self.annotator = annotator
        self.output_path = Path(output_path)
        self.case_ids = config["cases"]["ids"]
        self.cases_dir = project_path(paths["cases"])
        self.description_file = paths["case_description_file"]
        self.frozen_path = project_path(paths["frozen_retrieval"])
        self.frozen = json.loads(self.frozen_path.read_text(encoding="utf-8"))["cases"]
        self.prompt_path = project_path(paths["silver_prompt"])
        self.quotes = QuoteChecker()

    def load(self) -> dict:
        if self.output_path.exists():
            data = json.loads(self.output_path.read_text(encoding="utf-8"))
            if data["frozen_retrieval_sha256"] != sha256(self.frozen_path):
                raise ValueError("the frozen retrieval changed since the silver reference was built; "
                                 "build a new silver reference (new file) instead of mixing them")
            return data
        return {"status": STATUS, "created_at": datetime.now(timezone.utc).isoformat(),
                "annotator_model": None, "prompt_sha256": sha256(self.prompt_path),
                "frozen_retrieval_sha256": sha256(self.frozen_path), "cases": {}}

    def save(self, data: dict) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def annotate_case(self, case_id: str) -> dict:
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        passages = sorted(self.frozen[case_id]["passages"], key=lambda p: p["rank"])
        records = []
        for p in passages:
            out = self.annotator.run(case_id=case_id, description=description,
                                     passage_id=p["passage_id"], passage_text=p["text"])
            if out is None:
                records.append({"passage_id": p["passage_id"], "label": "annotation_failed",
                                "required_steps": [], "possible_steps": []})
                continue
            data = out.model_dump()
            if data["label"] != "applicable":
                data["required_steps"] = []
            if data["label"] != "indeterminate":
                data["possible_steps"] = []
            data["evidence_found"] = [self.quotes.found(q, description) for q in data["evidence"]]
            records.append({"passage_id": p["passage_id"], **data})
        required = [{"passage_id": r["passage_id"], **s} for r in records for s in r["required_steps"]]
        possible = [{"passage_id": r["passage_id"], **s} for r in records for s in r["possible_steps"]]
        return {"passages": records, "required_steps": required, "possible_steps": possible}

    def build(self) -> dict:
        data = self.load()
        for case_id in self.case_ids:
            if case_id in data["cases"]:
                continue
            data["cases"][case_id] = self.annotate_case(case_id)  # LLMUnavailableError stops here; progress kept
            data["annotator_model"] = self.annotator.llm.model_for_log
            self.save(data)
        return data


def main() -> None:
    config = load_config()
    paths = config["paths"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = RunLogger(project_path(paths["logs"]), "SILVER", f"silver_{stamp}")
    builder = SilverReferenceBuilder(config, SilverAnnotator(create_annotator_llm(config), logger),
                                     project_path(paths["silver_reference"]))
    try:
        data = builder.build()
    except LLMUnavailableError as e:
        raise SystemExit(f"Stopped (API error): {e}\nFinished cases are saved; run the same command again later.")
    labels = [p["label"] for c in data["cases"].values() for p in c["passages"]]
    print(f"Silver reference: {len(data['cases'])} cases, annotator {data['annotator_model']}")
    print({label: labels.count(label) for label in sorted(set(labels))})
    print(f"required steps: {sum(len(c['required_steps']) for c in data['cases'].values())}")
    print(f"Saved {builder.output_path}  ({STATUS})")


if __name__ == "__main__":
    main()
