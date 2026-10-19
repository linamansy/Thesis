"""Tests for the BPMNGen library versions in run_info.json (src/bpmngen_libraries.py, fix B8).

No Node.js and no npm: a fake runner answers like `node --version`, `npm --version` and `npm ls --json`.
"""

import json
import subprocess

import pytest

from run_experiment import bpmngen_library_settings
from src.bpmngen_libraries import VERSIONS_KEY, BPMNGenLibraries, installed_versions
from src.config import load_config
from src.run_folder import RunFolder

TOP = {"name": "server", "dependencies": {
    "bpmnlint": {"version": "11.7.2"}, "bpmn-moddle": {"version": "9.0.4"}, "express": {"version": "5.1.0"}}}
KEY = {"name": "server", "dependencies": {   # shaped like the real `npm ls bpmnlint bpmn-moddle --all --json`
    "bpmn-auto-layout": {"version": "1.2.0", "dependencies": {"bpmn-moddle": {"version": "10.0.0"}}},
    "bpmn-moddle": {"version": "9.0.4"},
    "bpmnlint": {"version": "11.7.2", "dependencies": {"bpmn-moddle": {"version": "9.0.4"}}}}}


def fake_tools(top=TOP, key=KEY, ls_code=0, calls=None, node="v24.20.0"):
    def run(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        if command[1:] == ["--version"]:
            out = node + "\n" if "node" in command[0] else "11.19.0\n"
            return subprocess.CompletedProcess(command, 0, out, "")
        tree = top if "--depth=0" in command else key
        return subprocess.CompletedProcess(command, ls_code, json.dumps(tree), "")
    return run


def config_for(tmp_path, key_libraries=("bpmnlint", "bpmn-moddle")):
    config = load_config()
    config["generator"] = dict(config["generator"], type="bpmngen", bpmngen_server_dir=str(tmp_path / "server"),
                               bpmngen_key_libraries=list(key_libraries), npm_command="npm")
    config["paths"] = dict(config["paths"], runs=str(tmp_path / "runs"))
    return config


def test_versions_of_node_npm_direct_and_key_libraries(tmp_path):
    calls = []
    versions = BPMNGenLibraries(config_for(tmp_path), runner=fake_tools(calls=calls)).versions()

    assert versions["node"] == "v24.20.0" and versions["npm"] == "11.19.0"
    assert versions["top_level"] == {"bpmn-moddle": "9.0.4", "bpmnlint": "11.7.2", "express": "5.1.0"}
    assert versions["key_libraries"] == {"bpmn-moddle": ["10.0.0", "9.0.4"], "bpmnlint": ["11.7.2"]}
    assert versions["problems"] == []
    assert all(kwargs["cwd"] == str(tmp_path / "server") for _, kwargs in calls)   # run in BPMNGen's folder
    ls_commands = [c for c, _ in calls if c[1:2] == ["ls"]]
    assert all("--json" in c for c in ls_commands)
    assert not any(word in c for c, _ in calls for word in ("install", "update", "ci", "uninstall"))  # read only


def test_installed_versions_finds_every_depth_and_reports_missing():
    assert installed_versions(KEY, {"bpmn-moddle", "bpmnlint", "not-there"}) == \
        {"bpmn-moddle": ["10.0.0", "9.0.4"], "bpmnlint": ["11.7.2"], "not-there": []}


def test_npm_problems_are_recorded_not_fatal(tmp_path):
    broken = dict(TOP, problems=["missing: foo@1.0.0, required by server@1.0.0"],
                  dependencies=dict(TOP["dependencies"], foo={"required": "1.0.0", "missing": True}))
    versions = BPMNGenLibraries(config_for(tmp_path), runner=fake_tools(top=broken, ls_code=1)).versions()
    assert versions["top_level"]["foo"] == "MISSING"
    assert versions["problems"] == ["missing: foo@1.0.0, required by server@1.0.0"]


def test_unusable_npm_output_stops(tmp_path):
    def garbage(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "v1" if command[1:] == ["--version"] else "not json", "")
    with pytest.raises(RuntimeError, match="did not return JSON"):
        BPMNGenLibraries(config_for(tmp_path), runner=garbage).versions()

    def failing(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, "", "npm ERR! something")
    with pytest.raises(RuntimeError, match="exit code 2"):
        BPMNGenLibraries(config_for(tmp_path), runner=failing).versions()


def test_run_info_stores_the_versions(tmp_path):
    config = config_for(tmp_path)
    settings = bpmngen_library_settings(config, BPMNGenLibraries(config, runner=fake_tools()))
    folder = RunFolder(config, "ollama_rep1", 1, settings)
    folder.start_part("C1", 1, tmp_path / "log.jsonl")
    assert folder.read_info()[VERSIONS_KEY]["key_libraries"]["bpmnlint"] == ["11.7.2"]


def test_a_later_part_with_other_versions_is_refused(tmp_path):
    config = config_for(tmp_path)
    first = RunFolder(config, "ollama_rep1", 1,
                      bpmngen_library_settings(config, BPMNGenLibraries(config, runner=fake_tools())))
    first.start_part("C1", 1, tmp_path / "log.jsonl")
    later = RunFolder(config, "ollama_rep1", 1, bpmngen_library_settings(
        config, BPMNGenLibraries(config, runner=fake_tools(node="v25.0.0"))))
    with pytest.raises(ValueError, match=f"other settings.*{VERSIONS_KEY}"):
        later.check_can_start("C1")


def test_nothing_recorded_for_the_legacy_generator(tmp_path):
    config = config_for(tmp_path)
    config["generator"]["type"] = "json_builder"
    assert bpmngen_library_settings(config) == {}
