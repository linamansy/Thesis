"""Build the silver legal reference ONCE and freeze it (like the retrieval). It must be complete before the
evaluation (python -m src.evaluate), not before the generation runs: it never uses generated models.

For every working case and every one of its 5 frozen passages, SilverAnnotator (openai/gpt-oss-120b on Groq,
config.yaml silver section; see src/agents/silver_annotator.py) labels the passage applicable / not_applicable /
indeterminate / irrelevant and lists the process steps it requires. Code then:
  - checks every evidence quote against the description (QuoteChecker) and records the result
  - removes required_steps from passages that are not "applicable" and possible_steps from passages that are
    not "indeterminate", so the file is always consistent
Output: data/silver/silver_reference.json with, per case, the passages and the list of required steps, plus
the annotator model version, the prompt checksum and the frozen-retrieval checksum (proof of what it used).

Rules:
  - It reads only descriptions and frozen passages. It never reads a generated model or a C3 output.
  - One annotator model for the whole file: after every call, the model name in the API's answer must equal
    silver.model in config.yaml (Google once served gemini-3.6-flash for gemini-3.5-flash requests). If it
    differs, the run stops at once WITHOUT saving that case and prints both names (ModelMismatchError).
    A saved file made by another model is refused in the same way.
  - Recorded: the provider, the dates the cases were annotated on (annotation_dates; each case also has
    annotated_at), and for Groq the system_fingerprint of every answer (which backend build answered).
    For Gemini, annotator_model_version (from Gemini's model list) is stored and checked as well.
  - Change of annotator (19 Oct 2026): gemini-3.6-flash -> openai/gpt-oss-120b via Groq, because the Gemini free
    tier allows only 20 requests/day. The 3 Gemini cases are kept in data/silver/_discarded/gemini_partial/.
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
from src.llm.groq_llm import GroqLLM
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.mediation.quote_checker import QuoteChecker

STATUS = "silver: AI-made reference, not checked by a human (provisional, never gold)"


class ModelMismatchError(RuntimeError):
    """The API answered with (or the saved file was made by) another model than silver.model in config.yaml."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_annotator_llm(config: dict) -> LLMClient:
    """The annotator's LLM: config.yaml silver section (mock in tests)."""
    silver = config["silver"]
    if config["llm"]["provider"] == "mock":  # THESIS_FORCE_MOCK (tests)
        answer = project_path(config["paths"]["mock_silver_response"]).read_text(encoding="utf-8")
        return MockLLM([answer])
    if silver["provider"] == "groq":
        return GroqLLM.from_config(config)
    if silver["provider"] != "gemini":
        raise ValueError(f"silver.provider must be groq or gemini, not {silver['provider']!r}")
    annotator_config = dict(config, llm=dict(config["llm"], model=silver["model"],
                                             temperature=silver["temperature"], max_tokens=silver["max_tokens"]))
    return GeminiLLM.from_config(annotator_config)


class SilverReferenceBuilder:
    def __init__(self, config: dict, annotator: SilverAnnotator, output_path: Path,
                 expected_model: str | None = None, model_version: str | None = None):
        """expected_model: silver.model; every answer must come from it (None = not checked, mock tests).
        model_version: internal version of that model in Gemini's model list (e.g. "3.6-flash-07-2026"),
        stored in the file header; a saved file with another version is refused (None = not checked)."""
        paths = config["paths"]
        self.config = config
        self.annotator = annotator
        self.expected_model = expected_model
        self.model_version = model_version
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
            saved_model = data.get("annotator_model")
            if self.expected_model and saved_model and saved_model != self.expected_model:
                raise ModelMismatchError(f"the saved silver reference was made by {saved_model!r}, but "
                                         f"silver.model is {self.expected_model!r}; one file must have one annotator")
            saved_version = data.get("annotator_model_version")
            if self.model_version and saved_version and saved_version != self.model_version:
                raise ModelMismatchError(f"the saved silver reference was made by version {saved_version!r}, but "
                                         f"Gemini now lists {self.model_version!r}; one file must have one annotator")
            if self.model_version:
                data["annotator_model_version"] = self.model_version
            return data
        return {"status": STATUS, "created_at": datetime.now(timezone.utc).isoformat(),
                "annotator_provider": self.config["silver"]["provider"],
                "annotator_model": None, "annotator_model_version": self.model_version,
                "annotation_dates": [], "prompt_sha256": sha256(self.prompt_path),
                "frozen_retrieval_sha256": sha256(self.frozen_path), "cases": {}}

    def save(self, data: dict) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def annotate_case(self, case_id: str) -> dict:
        description = (self.cases_dir / case_id / self.description_file).read_text(encoding="utf-8")
        passages = sorted(self.frozen[case_id]["passages"], key=lambda p: p["rank"])
        records, fingerprints = [], set()
        for p in passages:
            out = self.annotator.run(case_id=case_id, description=description,
                                     passage_id=p["passage_id"], passage_text=p["text"])
            self.check_model()   # before anything of this case is saved
            fingerprint = getattr(self.annotator.llm, "last_system_fingerprint", None)
            if fingerprint:
                fingerprints.add(fingerprint)
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
        return {"annotated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "system_fingerprints": sorted(fingerprints),
                "passages": records, "required_steps": required, "possible_steps": possible}

    def check_model(self) -> None:
        """Stop if the API's last answer came from another model than silver.model."""
        served = self.annotator.llm.model_for_log
        if self.expected_model and served != self.expected_model:
            raise ModelMismatchError(f"the API answered with model {served!r}, but silver.model in config.yaml "
                                     f"is {self.expected_model!r}")

    def build(self) -> dict:
        data = self.load()
        for case_id in self.case_ids:
            if case_id in data["cases"]:
                continue
            data["cases"][case_id] = self.annotate_case(case_id)  # LLMUnavailableError stops here; progress kept
            data["annotator_model"] = self.annotator.llm.model_for_log
            day = data["cases"][case_id]["annotated_at"][:10]
            data.setdefault("annotation_dates", [])
            if day not in data["annotation_dates"]:
                data["annotation_dates"].append(day)
            self.save(data)
        return data


def main() -> None:
    config = load_config()
    paths = config["paths"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = RunLogger(project_path(paths["logs"]), "SILVER", f"silver_{stamp}")
    llm = create_annotator_llm(config)
    expected_model = None if config["llm"]["provider"] == "mock" else config["silver"]["model"]
    try:
        model_version = llm.listed_version() if isinstance(llm, GeminiLLM) else None
        builder = SilverReferenceBuilder(config, SilverAnnotator(llm, logger), project_path(paths["silver_reference"]),
                                         expected_model, model_version)
        data = builder.build()
    except LLMUnavailableError as e:
        raise SystemExit(f"Stopped (API error): {e}\nFinished cases are saved; run the same command again later.")
    except ModelMismatchError as e:
        raise SystemExit(f"Stopped (model mismatch, this case was NOT saved): {e}")
    labels = [p["label"] for c in data["cases"].values() for p in c["passages"]]
    print(f"Silver reference: {len(data['cases'])} cases, annotator {data.get('annotator_provider')}/"
          f"{data['annotator_model']} (version {data.get('annotator_model_version')}), "
          f"annotated on {', '.join(data.get('annotation_dates') or [])}")
    print("all passages:", {label: labels.count(label) for label in sorted(set(labels))})
    for case_id, case in sorted(data["cases"].items()):
        case_labels = [p["label"] for p in case["passages"]]
        print(f"  case {case_id}: {dict(sorted((l, case_labels.count(l)) for l in set(case_labels)))}")
    with_applicable = [c for c, case in data["cases"].items() if any(p["label"] == "applicable" for p in case["passages"])]
    print(f"cases with at least one applicable rule: {len(with_applicable)} {sorted(with_applicable)}")
    print(f"required steps: {sum(len(c['required_steps']) for c in data['cases'].values())}")
    print(f"Saved {builder.output_path}  ({STATUS})")


if __name__ == "__main__":
    main()
