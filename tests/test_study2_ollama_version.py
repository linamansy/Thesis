"""Test that src/run_study2.py stops at startup when the installed Ollama version differs from
config.yaml study2_gdpr.ollama_version. No Ollama: ollama_settings is replaced by a fake that returns a version."""

import pytest

import src.run_study2 as run_study2
from src.run_study2 import main as run_main

from test_study2_run import CASE, study_config


class PassedVersionCheck(Exception):
    """Raised by the step after the version check, so the test knows the check let the run through."""


def fake_startup(monkeypatch, tmp_path, version):
    config = study_config(tmp_path)
    monkeypatch.setattr(run_study2, "load_config", lambda: config)
    monkeypatch.setattr(run_study2, "ollama_settings", lambda view: {"ollama_version": version})
    monkeypatch.setattr(run_study2, "bpmngen_file_settings", lambda view, run_id: {})
    monkeypatch.setattr(run_study2, "bpmngen_library_settings", lambda view: {})

    def next_step(*args):
        raise PassedVersionCheck()
    monkeypatch.setattr(run_study2, "RunFolder", next_step)
    return str(config["study2_gdpr"]["ollama_version"])


def test_runner_stops_when_the_ollama_version_differs(monkeypatch, tmp_path):
    expected = fake_startup(monkeypatch, tmp_path, "0.0.1")
    with pytest.raises(SystemExit) as stop:
        run_main(["--case", CASE, "--run-id", "study2_test"])
    message = str(stop.value)
    assert message.startswith("Not started:") and "'0.0.1'" in message and repr(expected) in message


def test_runner_goes_on_when_the_ollama_version_matches(monkeypatch, tmp_path):
    expected = fake_startup(monkeypatch, tmp_path, None)
    monkeypatch.setattr(run_study2, "ollama_settings", lambda view: {"ollama_version": expected})
    with pytest.raises(PassedVersionCheck):
        run_main(["--case", CASE, "--run-id", "study2_test"])
