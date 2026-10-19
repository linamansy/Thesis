"""BPMNGenLibraries: the installed versions of BPMNGen's libraries, for run_info.json (audit 19 Oct 2026, B8).

BPMNGen's cleanup and its bpmnlint check run inside libraries from its node_modules folder (e.g. bpmnlint,
bpmn-moddle). Their versions can change with every `npm install`, so each run records them. Everything here is
READ ONLY: it runs `node --version`, `npm --version` and `npm ls` in the BPMNGen server folder; npm ls only lists
what is installed and changes nothing. No BPMNGen file is opened.

Stored in run_info.json as "bpmngen_library_versions":
    node, npm          the Node.js and npm versions
    top_level          {package: version} of every direct dependency of BPMNGen (npm ls --depth=0)
    key_libraries      {package: [every installed version]} for config.yaml generator.bpmngen_key_libraries,
                       found at any depth (a package can be installed in several versions; [] = not installed)
    problems           what npm ls reports as wrong (e.g. missing or invalid packages); [] if nothing
Because it is a run setting, RunFolder refuses a later part of the same run with other versions.
"""

import json
import shutil
import subprocess
from typing import Callable

from src.bpmngen_generator import resolve, run_with_tree_kill

VERSIONS_KEY = "bpmngen_library_versions"   # key in run_info.json


def installed_versions(tree: dict, names: set[str]) -> dict[str, list[str]]:
    """Every version of the named packages anywhere in an `npm ls --json` tree, sorted, without duplicates."""
    found: dict[str, set[str]] = {name: set() for name in names}

    def walk(node: dict) -> None:
        for name, info in (node.get("dependencies") or {}).items():
            if name in found and info.get("version"):
                found[name].add(info["version"])
            walk(info)

    walk(tree)
    return {name: sorted(versions) for name, versions in sorted(found.items())}


class BPMNGenLibraries:
    """Reads the installed versions of BPMNGen's libraries (read only)."""

    def __init__(self, config: dict, runner: Callable = run_with_tree_kill):
        """runner can be replaced in tests (no Node.js, no npm)."""
        g = config["generator"]
        self.server_dir = resolve(g["bpmngen_server_dir"])
        self.key_libraries = list(g["bpmngen_key_libraries"])
        self.timeout_seconds = g["timeout_seconds"]
        self.npm = g.get("npm_command") or shutil.which("npm") or "npm"
        self.node = shutil.which("node") or "node"
        self.runner = runner

    def _run(self, command: list[str], allowed_codes: tuple[int, ...] = (0,)) -> str:
        try:
            result = self.runner(command, cwd=str(self.server_dir), timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"{' '.join(command[1:])} timed out after {self.timeout_seconds} s") from e
        if result.returncode not in allowed_codes:
            raise RuntimeError(f"{' '.join(command)} failed (exit code {result.returncode}): "
                               f"{((result.stderr or '') + (result.stdout or ''))[-500:]}")
        return result.stdout or ""

    def _npm_ls(self, *args: str) -> dict:
        """npm ls --json. npm ls exits with code 1 when it finds problems, but still prints the full tree."""
        output = self._run([self.npm, "ls", *args, "--json"], allowed_codes=(0, 1))
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"npm ls did not return JSON: {output[-500:]}") from e

    def versions(self) -> dict:
        top = self._npm_ls("--depth=0")
        key = self._npm_ls(*self.key_libraries, "--all")
        return {
            "node": self._run([self.node, "--version"]).strip(),
            "npm": self._run([self.npm, "--version"]).strip(),
            "top_level": {name: info.get("version") or "MISSING"
                          for name, info in sorted((top.get("dependencies") or {}).items())},
            "key_libraries": installed_versions(key, set(self.key_libraries)),
            "problems": sorted(set(top.get("problems") or []) | set(key.get("problems") or [])),
        }
