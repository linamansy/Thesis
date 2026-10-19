"""The current config.yaml (and prompts/) reproduces the stored Study 1 prompts byte for byte (fix B7+C1).

Reads the real Study 1 outputs (results/runs/ollama_rep1-3 and results/logs/C3_ollama_rep*.jsonl) READ ONLY;
skipped where they are not present (results/ is not in git).

  generator  for all 117 generations: the knowledge block rebuilt from config (C1 text, C2 frozen passages, C3 block
             template + the stored mediation records) equals the stored knowledge_block.txt, and BPMNGen's user
             message equals  description + "\\n\\n" + knowledge_label + "\\n" + knowledge block + "\\n\\n/no_think"
             built from the stored input files exactly as the harness joins them. Model, temperature, num_ctx,
             think and the SHA-256 of BPMNGen's system prompt equal the config values (BPMNGenGenerator.check_request).
  agents     every logged C3 agent prompt equals the prompt the agent class builds from config (its prompt file,
             the description, the passage; after an invalid answer + the retry note from prompts/), and the
             logged temperature and model digest equal config.
"""

import json
from pathlib import Path

import pytest

from src.agents.applicability_agent import ApplicabilityAgent
from src.agents.relevance_agent import RelevanceAgent
from src.agents.requirement_agent import RequirementAgent
from src.bpmngen_generator import BPMNGenGenerator
from src.config import PROJECT_ROOT, load_config, project_path
from src.generator import format_passages
from src.llm.mock_llm import MockLLM
from src.logger import RunLogger
from src.orchestrator import Orchestrator
from src.prompt_texts import load_c3_block_template, load_no_knowledge_text

CONFIG = load_config()
STUDY_RUNS = ["ollama_rep1", "ollama_rep2", "ollama_rep3"]
REAL_RESULTS = PROJECT_ROOT / "results"   # the real folder, not the redirected test folder (read only)
RUNS = [REAL_RESULTS / "runs" / run for run in STUDY_RUNS]
LOGS = [REAL_RESULTS / "logs" / f"C3_{run}.jsonl" for run in STUDY_RUNS]
FROZEN = json.loads(project_path(CONFIG["paths"]["frozen_retrieval"]).read_text(encoding="utf-8"))["cases"]
CASES_DIR = project_path(CONFIG["paths"]["cases"])
pytestmark = pytest.mark.skipif(not all(r.exists() for r in RUNS) or not all(l.exists() for l in LOGS),
                                reason="Study 1 outputs (results/) not present")


def rebuilt_block(condition: str, case_dir: Path) -> str:
    """The knowledge block of one case, rebuilt from config and the frozen / mediation data only."""
    case_id = case_dir.name
    if condition == "C1":
        return load_no_knowledge_text(CONFIG)
    if condition == "C2":
        return format_passages(FROZEN[case_id]["passages"])
    mediation = json.loads((case_dir.parent / CONFIG["paths"]["mediation_dir"] / f"{case_id}.json")
                           .read_text(encoding="utf-8"))
    orchestrator = Orchestrator(None, None, None, FROZEN, {}, case_dir, load_c3_block_template(CONFIG),
                                CONFIG["paths"]["mediation_summary_file"])
    return orchestrator.knowledge_block(mediation["passages"])


def generations():
    return [(run.name, condition, run / condition / case_id)
            for run in RUNS for condition in CONFIG["conditions"] for case_id in CONFIG["cases"]["ids"]]


def test_all_117_generations_are_covered():
    assert len(generations()) == 117
    assert all((d / CONFIG["paths"]["bpmngen_output_dir"] / CONFIG["paths"]["bpmngen_request_file"]).exists()
               for _, _, d in generations())


@pytest.mark.parametrize("run_id,condition,case_dir", generations(),
                         ids=[f"{r}-{c}-{d.name}" for r, c, d in generations()])
def test_generator_prompt_is_reproduced(run_id, condition, case_dir):
    paths = CONFIG["paths"]
    block = rebuilt_block(condition, case_dir)
    stored_file = case_dir / paths["knowledge_block_file"]
    # 1. the knowledge text built from config is exactly the stored knowledge_block.txt (text, newline-normalised)
    assert stored_file.read_text(encoding="utf-8") == block.strip() + "\n"

    # 2. BPMNGen's user message = the harness join of the stored input files (bytes, incl. Windows line endings)
    request = json.loads((case_dir / paths["bpmngen_output_dir"] / paths["bpmngen_request_file"])
                         .read_text(encoding="utf-8"))
    description = (CASES_DIR / case_dir.name / paths["case_description_file"]).open(encoding="utf-8", newline="").read()
    knowledge = stored_file.open(encoding="utf-8", newline="").read()
    expected_user = (f"{description.strip()}\n\n{CONFIG['generator']['knowledge_label']}\n{knowledge.strip()}"
                     f"\n\n/no_think")
    users = [m["content"] for m in request["messages"] if m["role"] == "user"]
    assert users == [expected_user]

    # 3. model, BPMNGen's fixed temperature and num_ctx, think and system prompt hash = config
    BPMNGenGenerator(CONFIG, logger=None).check_request(request)


AGENTS = {"RelevanceAgent": RelevanceAgent, "ApplicabilityAgent": ApplicabilityAgent,
          "RequirementAgent": RequirementAgent}


def agent_records():
    records = []
    for log in LOGS:
        for line in log.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["component"] in AGENTS:
                records.append(record)
    return records


def test_every_logged_agent_prompt_is_reproduced(tmp_path):
    records = agent_records()
    assert records, "no agent calls found in the Study 1 logs"
    logger = RunLogger(tmp_path, "C3", "check")
    agents = {name: cls(MockLLM(["{}"]), logger) for name, cls in AGENTS.items()}
    previous = {}   # (case, component) -> the record before, to rebuild a retry prompt
    checked = 0
    for record in records:
        agent = agents[record["component"]]
        case_id = record["case_id"]
        description = (CASES_DIR / case_id / CONFIG["paths"]["case_description_file"]).read_text(encoding="utf-8")
        passages = [p for p in FROZEN[case_id]["passages"]
                    if f"[{p['passage_id']}] {p['text'].strip()}" in record["prompt"]]
        assert len(passages) == 1, (case_id, record["component"])
        p = passages[0]
        expected = agent.build_prompt(description=description, passage_id=p["passage_id"], passage_text=p["text"])
        if record["retries"] > 0:
            _, error = agent.parse_output(previous[(case_id, record["component"])]["raw_output"])
            expected += agent.retry_note.format(error=error)
        assert record["prompt"] == expected, (case_id, record["component"], p["passage_id"])
        assert record["temperature"] == CONFIG["llm"]["temperature"]
        assert record["model_digest"] == CONFIG["model"]["ollama_model_digest"]
        previous[(case_id, record["component"])] = record
        checked += 1
    assert checked == len(records)
