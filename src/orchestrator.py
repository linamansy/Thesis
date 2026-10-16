"""Orchestrator: runs the mediation steps of C3 for each frozen passage of a case.

For every passage of the case, in rank order:
  1. RelevanceAgent (+ RelevanceEvidenceChecker records whether its process quote is real)
     not relevant              -> label "Irrelevant", stop
  2. ApplicabilityAgent, then ApplicabilityResolver (code, no LLM) -> label
     "Applicable", "Not applicable" or "Indeterminate"
  3. RequirementAgent, ONLY for "Applicable"
If an agent still fails after its retry (invalid output, or another error), the passage is labelled
"Mediation failed" and the next passage is processed; a case is never stopped for that.
Exception: LLMUnavailableError (the API gave an error instead of an answer, e.g. the daily free-tier
limit after all API retries, or 404 model not found) is NOT a mediation result. It is passed on, so the run stops and can be resumed.

The C3 knowledge block is then built from the labels. It ALWAYS has the same two headings,
each followed by the same fixed explanation line (REQUIREMENTS_EXPLANATION, UNCONFIRMED_EXPLANATION):
  REQUIREMENTS                              one line per Applicable passage with its requirement
  RULES WITH UNCONFIRMED APPLICABILITY      id and title of each Indeterminate passage, followed by
                                            "Unconfirmed: <condition>" for each of its conditions whose
                                            final status (after the resolver) is not_stated
An empty section contains "(none)". Irrelevant, Not applicable and failed passages are left out.
Everything comes from the saved agent outputs and resolver results; no extra LLM call.

Saved (provenance, by code) in the run's C3/mediation/ folder:
  <case_id>.json     per passage: id, text, label, every agent output, the relevance quote check,
                     the resolver's checked conditions and downgrades, the requirement, and the
                     knowledge block of the case. Written only when the case's mediation is complete.
                     If it already exists (a resumed run), it is reused and the agents are not called again.
  run_summary.json   counts over all mediation files of the run (so it also covers resumed runs)
"""

import json
from collections import Counter
from pathlib import Path

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.llm.base_llm import LLMUnavailableError
from src.mediation.applicability_resolver import APPLICABLE, INDETERMINATE, NOT_APPLICABLE, ApplicabilityResolver
from src.mediation.relevance_evidence_checker import RelevanceEvidenceChecker

IRRELEVANT = "Irrelevant"
MEDIATION_FAILED = "Mediation failed"
LABELS = [APPLICABLE, INDETERMINATE, NOT_APPLICABLE, IRRELEVANT, MEDIATION_FAILED]
REQUIREMENTS_HEADING = "REQUIREMENTS"
REQUIREMENTS_EXPLANATION = "These rules were checked and apply to this process."
UNCONFIRMED_HEADING = "RULES WITH UNCONFIRMED APPLICABILITY"
# Descriptive only (16 Oct 2026): an instruction such as "Do not add steps for them" would be an extra
# INSTRUCTION that only C3 gets, so C3 would differ from C2 in more than the knowledge. The block states
# what mediation found (the status of each rule); what the generator does with it is left to the generator.
UNCONFIRMED_EXPLANATION = "These rules may apply, but the description does not confirm that their conditions are met."
EMPTY_SECTION_TEXT = "(none)"


class Orchestrator:
    """Runs RelevanceAgent -> ApplicabilityAgent + resolver -> RequirementAgent per passage."""

    def __init__(self, relevance_agent: RelevanceAgent, applicability_agent: ApplicabilityAgent,
                 requirement_agent: RequirementAgent, frozen_cases: dict, titles: dict[str, str],
                 output_dir: Path):
        self.relevance_agent = relevance_agent
        self.applicability_agent = applicability_agent
        self.requirement_agent = requirement_agent
        self.frozen_cases = frozen_cases   # "cases" part of frozen_retrieval.json
        self.titles = titles               # passage id -> article title
        self.output_dir = Path(output_dir)
        self.resolver = ApplicabilityResolver()
        self.relevance_checker = RelevanceEvidenceChecker()
        self.reused_cases = []   # cases whose saved mediation was reused (resumed run)

    # ---------- one case ----------

    def mediate_case(self, case_id: str, description: str) -> dict:
        """Mediate all frozen passages of one case, save the result and return it.

        If this case's mediation file already exists (complete mediation from an earlier part of the
        run), it is returned unchanged and no agent is called.
        """
        if case_id not in self.frozen_cases:
            raise KeyError(f"case {case_id} is missing from the frozen retrieval file")
        path = self.output_dir / f"{case_id}.json"
        if path.exists():
            self.reused_cases.append(case_id)
            return json.loads(path.read_text(encoding="utf-8"))

        passages = sorted(self.frozen_cases[case_id]["passages"], key=lambda p: p["rank"])
        records = [self.mediate_passage(case_id, description, p) for p in passages]
        result = {"case_id": case_id, "passages": records, "knowledge_block": self.knowledge_block(records)}

        self.output_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result

    def mediate_passage(self, case_id: str, description: str, passage: dict) -> dict:
        """The three steps for one passage. Returns the full provenance record."""
        passage_id, text = passage["passage_id"], passage["text"]
        record = {
            "rank": passage["rank"],
            "passage_id": passage_id,
            "title": self.titles.get(passage_id, ""),
            "passage_text": text,
            "label": None,
            "failed_step": None,
            "error": None,
            "relevance": None,       # agent output + quote_found
            "applicability": None,   # agent output, unchanged
            "resolution": None,      # resolver: label, checked conditions, downgrades
            "requirement": None,
        }
        inputs = {"case_id": case_id, "description": description, "passage_id": passage_id, "passage_text": text}

        # Step 1: relevance
        relevance = self._call(self.relevance_agent, record, "relevance", **inputs)
        if relevance is None:
            return record
        record["relevance"] = self.relevance_checker.check(relevance, description)
        if not relevance.relevant:
            record["label"] = IRRELEVANT
            return record

        # Step 2: applicability (agent) + resolver (code)
        applicability = self._call(self.applicability_agent, record, "applicability", **inputs)
        if applicability is None:
            return record
        record["applicability"] = applicability.model_dump()
        resolution = self.resolver.resolve(applicability.conditions, description)
        record["resolution"] = resolution
        record["label"] = resolution["label"]
        if resolution["label"] != APPLICABLE:
            return record

        # Step 3: requirement, only for Applicable rules
        requirement = self._call(self.requirement_agent, record, "requirement",
                                 satisfied_conditions=ApplicabilityResolver.satisfied_conditions(resolution), **inputs)
        if requirement is not None:
            record["requirement"] = requirement.model_dump()
        return record

    def _call(self, agent, record: dict, step: str, **inputs):
        """Run one agent. On failure, mark the passage "Mediation failed" and return None."""
        try:
            output = agent.run(**inputs)
            error = None if output is not None else "no valid output after retry (see the log file)"
        except LLMUnavailableError:
            raise  # the API is unreachable: stop the run (it can be resumed), do not record a result
        except Exception as e:  # any other error: record it and go on with the next passage
            output, error = None, f"{type(e).__name__}: {e}"
        if output is None:
            record["label"] = MEDIATION_FAILED
            record["failed_step"] = step
            record["error"] = error
        return output

    # ---------- knowledge block ----------

    def knowledge_block(self, records: list[dict]) -> str:
        """The C3 knowledge block (see the module comment)."""
        requirements = [r for r in records if r["label"] == APPLICABLE and r["requirement"]]
        unconfirmed = [r for r in records if r["label"] == INDETERMINATE]

        requirement_lines = []
        for r in requirements:
            q = r["requirement"]
            requirement_lines.append(
                f"- [{r['passage_id']}] Actor: {q['actor']}. Action: {q['action']}. "
                f"Condition: {q['condition'] or 'none stated'}. Ordering: {q['ordering'] or 'none stated'}.")

        unconfirmed_lines = []
        for r in unconfirmed:
            unconfirmed_lines.append(f"- [{r['passage_id']}] {r['title']}")
            unconfirmed_lines += [f"  Unconfirmed: {c['condition']}"
                                  for c in r["resolution"]["conditions"] if c["status"] == "not_stated"]

        return "\n".join([REQUIREMENTS_HEADING, REQUIREMENTS_EXPLANATION, *(requirement_lines or [EMPTY_SECTION_TEXT]),
                          "",
                          UNCONFIRMED_HEADING, UNCONFIRMED_EXPLANATION, *(unconfirmed_lines or [EMPTY_SECTION_TEXT])])

    # ---------- whole run ----------

    def save_run_summary(self, run_id: str) -> dict:
        """Counts over ALL saved mediation files of the run, so a resumed run is counted completely."""
        cases = sorted(p.stem for p in self.output_dir.glob("*.json") if p.name != "run_summary.json")
        records = [r for case in cases for r in
                   json.loads((self.output_dir / f"{case}.json").read_text(encoding="utf-8"))["passages"]]
        labels = Counter(r["label"] for r in records)
        conditions = [c for r in records if r["resolution"] for c in r["resolution"]["conditions"]]
        quotes = [r["relevance"]["quote_found"] for r in records
                  if r["relevance"] and r["relevance"]["quote_found"] is not None]
        summary = {
            "run_id": run_id,
            "cases": cases,
            "n_passages": len(records),
            "passages_per_label": {label: labels.get(label, 0) for label in LABELS},
            "applicability_resolver": {
                "conditions_checked": len(conditions),
                "downgraded": sum(c["downgraded"] for c in conditions),
                "downgraded_quote_not_found": sum(c["note"] == "evidence quote not found in the description"
                                                  for c in conditions),
                "downgraded_no_quote": sum(c["note"] == "no evidence quote given" for c in conditions),
            },
            "relevance_evidence_checker": {"process_quotes_checked": len(quotes),
                                           "process_quotes_not_found": quotes.count(False)},
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
