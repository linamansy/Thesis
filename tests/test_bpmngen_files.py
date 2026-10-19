"""Tests for the BPMNGen file hashes (src/bpmngen_files.py) and their checks (audit 19 Oct 2026, finding 1).

No Node.js and no real BPMNGen: a fake server folder with dummy files and a fake runner that answers like
`run_bpmngen.ts --list-files`.
"""

import hashlib
import json
import subprocess

import pytest

from run_experiment import bpmngen_file_settings
from src.bpmngen_files import HASHES_KEY, BPMNGenFiles, check_same_study
from src.config import load_config
from src.run_folder import RunFolder

NAMED = ["tools/ai/opensource.ts", "tools/ai/ai.ts", "tools/utils/xml-validator.ts", "environment.ts"]
LOADED = ["environment.ts", "tools/ai/ai.ts", "tools/ai/opensource.ts", "tools/utils/xml-validator.ts",
          "tools/ai/prompts/system.txt", "tsconfig.json"]
STUDY = ["ollama_rep1", "ollama_rep2", "ollama_rep3"]


def fake_server(tmp_path, files=LOADED):
    """A BPMNGen server folder with one dummy file per path (content = its own path)."""
    server = tmp_path / "server"
    for relative in files:
        (server / relative).parent.mkdir(parents=True, exist_ok=True)
        (server / relative).write_text(f"dummy {relative}", encoding="utf-8")
    return server


def config_for(server, tmp_path):
    config = load_config()
    config["generator"] = dict(config["generator"], type="bpmngen", bpmngen_server_dir=str(server),
                               npx_command="npx", bpmngen_hashed_files=NAMED)
    config["paths"] = dict(config["paths"], runs=str(tmp_path / "runs"))
    config["statistics"] = dict(config["statistics"], runs=STUDY)
    return config


def lister(files=LOADED, returncode=0, calls=None, noise="BPMNGen log line"):
    """Answers like the harness in --list-files mode (BPMNGen may print other lines first)."""
    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        stdout = f"{noise}\n{json.dumps({'bpmngen_files': files})}\n"
        return subprocess.CompletedProcess(command, returncode, stdout if returncode == 0 else "", "boom")
    return run


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- (1) hashing ----------

def test_hashes_cover_named_and_loaded_files(tmp_path):
    server = fake_server(tmp_path)
    calls = []
    hashes = BPMNGenFiles(config_for(server, tmp_path), runner=lister(calls=calls)).hashes()

    assert list(hashes) == sorted(LOADED)                      # named + loaded, each once, sorted
    assert hashes["tools/ai/opensource.ts"] == sha("dummy tools/ai/opensource.ts")
    assert hashes["tools/ai/prompts/system.txt"] == sha("dummy tools/ai/prompts/system.txt")  # found by the harness
    command, kwargs = calls[0]
    assert command[-1] == "--list-files" and kwargs["cwd"] == str(server)


def test_excluded_files_are_not_hashed(tmp_path):
    server = fake_server(tmp_path, LOADED + [".env"])
    config = config_for(server, tmp_path)
    config["generator"]["bpmngen_hash_exclude"] = [".env"]   # BPMNGen's secrets file
    hashes = BPMNGenFiles(config, runner=lister(LOADED + [".env"])).hashes()
    assert ".env" not in hashes and list(hashes) == sorted(LOADED)


def test_hashing_never_changes_the_files(tmp_path):
    server = fake_server(tmp_path)
    before = {p: p.read_bytes() for p in server.rglob("*") if p.is_file()}
    BPMNGenFiles(config_for(server, tmp_path), runner=lister()).hashes()
    assert {p: p.read_bytes() for p in server.rglob("*") if p.is_file()} == before


def test_a_changed_file_gives_another_hash(tmp_path):
    server = fake_server(tmp_path)
    files = BPMNGenFiles(config_for(server, tmp_path), runner=lister())
    first = files.hashes()
    (server / "tools/ai/ai.ts").write_text("dummy tools/ai/ai.ts, edited", encoding="utf-8")
    second = files.hashes()
    assert first["tools/ai/ai.ts"] != second["tools/ai/ai.ts"]
    assert {k: v for k, v in first.items() if k != "tools/ai/ai.ts"} == \
           {k: v for k, v in second.items() if k != "tools/ai/ai.ts"}


def test_missing_named_file_stops(tmp_path):
    server = fake_server(tmp_path, [f for f in LOADED if f != "environment.ts"])
    with pytest.raises(FileNotFoundError, match="environment.ts"):
        BPMNGenFiles(config_for(server, tmp_path), runner=lister([f for f in LOADED if f != "environment.ts"])).hashes()


def test_harness_failure_or_no_list_stops(tmp_path):
    config = config_for(fake_server(tmp_path), tmp_path)
    with pytest.raises(RuntimeError, match="exit code 1"):
        BPMNGenFiles(config, runner=lister(returncode=1)).hashes()

    def silent(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "nothing useful", "")
    with pytest.raises(RuntimeError, match="did not report"):
        BPMNGenFiles(config, runner=silent).hashes()


def test_run_info_stores_the_hashes(tmp_path):
    server = fake_server(tmp_path)
    config = config_for(server, tmp_path)
    settings = bpmngen_file_settings(config, "ollama_rep1", BPMNGenFiles(config, runner=lister()), runs=[])
    folder = RunFolder(config, "ollama_rep1", 1, settings)
    folder.start_part("C1", 1, tmp_path / "log.jsonl")
    assert folder.read_info()[HASHES_KEY] == settings[HASHES_KEY]
    assert set(settings[HASHES_KEY]) == set(LOADED)


def test_no_hashes_for_the_legacy_generator(tmp_path):
    config = config_for(fake_server(tmp_path), tmp_path)
    config["generator"]["type"] = "json_builder"
    assert bpmngen_file_settings(config, "mock_rep1", files=None, runs=[]) == {}


# ---------- (2) checks ----------

HASHES = {"environment.ts": "a" * 64, "tools/ai/ai.ts": "b" * 64}


def run_info(run_id, hashes):
    return {"run_id": run_id, **({HASHES_KEY: hashes} if hashes is not None else {})}


def test_same_hashes_in_the_study_are_accepted():
    check_same_study("ollama_rep2", HASHES, [run_info("ollama_rep1", dict(HASHES))], STUDY)


def test_different_hash_in_the_study_stops_with_a_clear_error():
    other = dict(HASHES, **{"tools/ai/ai.ts": "c" * 64})
    with pytest.raises(ValueError, match=r"BPMNGen differs from run 'ollama_rep1'.*tools/ai/ai\.ts"):
        check_same_study("ollama_rep2", HASHES, [run_info("ollama_rep1", other)], STUDY)


def test_a_file_more_or_less_also_stops():
    more = dict(HASHES, **{"tools/ai/prompts/system.txt": "d" * 64})
    with pytest.raises(ValueError, match="system.txt"):
        check_same_study("ollama_rep3", HASHES, [run_info("ollama_rep1", more)], STUDY)


def test_runs_outside_the_study_old_runs_and_the_run_itself_are_not_compared():
    other = {"environment.ts": "e" * 64}
    runs = [run_info("smoke_bpmngen", other),      # not in the study
            run_info("ollama_rep1", None),          # made before hashes were stored
            run_info("ollama_rep2", other)]         # the run itself (its parts: RunFolder, next test)
    check_same_study("ollama_rep2", HASHES, runs, STUDY)
    check_same_study("smoke_new", HASHES, [run_info("ollama_rep1", other)], STUDY)  # a smoke run is not checked


def test_study_check_uses_the_saved_run_folders(tmp_path):
    server = fake_server(tmp_path)
    config = config_for(server, tmp_path)
    files = BPMNGenFiles(config, runner=lister())
    first = RunFolder(config, "ollama_rep1", 1, bpmngen_file_settings(config, "ollama_rep1", files))
    first.start_part("C1", 1, tmp_path / "log.jsonl")

    (server / "tools/ai/opensource.ts").write_text("dummy, edited", encoding="utf-8")
    with pytest.raises(ValueError, match="tools/ai/opensource.ts"):
        bpmngen_file_settings(config, "ollama_rep2", files)


def test_a_later_part_of_the_same_run_with_other_hashes_is_refused(tmp_path):
    server = fake_server(tmp_path)
    config = config_for(server, tmp_path)
    files = BPMNGenFiles(config, runner=lister())
    folder = RunFolder(config, "ollama_rep1", 1, bpmngen_file_settings(config, "ollama_rep1", files, runs=[]))
    folder.start_part("C1", 1, tmp_path / "log.jsonl")

    (server / "environment.ts").write_text("dummy, edited", encoding="utf-8")
    later = RunFolder(config, "ollama_rep1", 1, bpmngen_file_settings(config, "ollama_rep1", files, runs=[]))
    with pytest.raises(ValueError, match=f"other settings.*{HASHES_KEY}"):
        later.check_can_start("C1")
