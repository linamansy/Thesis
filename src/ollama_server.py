"""Facts about the Ollama SERVER that a run depends on, so the thesis can report them.

Two things influence speed and (slightly) the numbers the model computes, but are not part of any request:
  - the Ollama version (Ollama updates itself on Windows)
  - server settings that are environment variables of the Ollama program, here:
      OLLAMA_FLASH_ATTENTION=1   a faster way to compute attention that needs less GPU memory
      OLLAMA_KV_CACHE_TYPE=q8_0  the model's working memory for the context stored with 8 bits instead of 16
    With both, qwen3:8b with a 16384-token context fits completely on the 8 GB GPU.
The expected values are in config.yaml (model.ollama_server_env). When a run starts, run_experiment.py reads the
real values, refuses to start if they differ, and stores them (and the version) in run_info.json.

Where the variables are read: on Windows they are user (or machine) environment variables, which the Ollama
program reads when it starts. They are read from the Windows registry, because a terminal that was opened
before they were set does not see them. On other systems they are read from the environment.
Ollama must be restarted after a variable is changed; this module cannot see what the running server uses.
"""

import os
import sys
from typing import Callable

import httpx

from src.llm.base_llm import LLMUnavailableError

WINDOWS_KEYS = [  # user variables win over machine variables, as in Windows itself
    ("HKEY_CURRENT_USER", r"Environment"),
    ("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
]


def read_environment_variable(name: str) -> str | None:
    """The value of a (Windows user/machine) environment variable, or None if it is not set."""
    if sys.platform == "win32":
        import winreg
        for root, key in WINDOWS_KEYS:
            try:
                with winreg.OpenKey(getattr(winreg, root), key) as k:
                    return str(winreg.QueryValueEx(k, name)[0])
            except FileNotFoundError:
                continue
    return os.environ.get(name)


def server_environment(expected: dict, reader: Callable[[str], str | None] = read_environment_variable) -> dict:
    """The real value of every variable in expected (config.yaml model.ollama_server_env).

    Raises ValueError if any differs from config.yaml, so a run never starts with other server settings.
    """
    actual = {name: reader(name) for name in expected}
    different = {name: (actual[name], str(value)) for name, value in expected.items() if actual[name] != str(value)}
    if different:
        raise ValueError(f"Ollama server settings differ from config.yaml model.ollama_server_env (now vs expected): "
                         f"{different}. Set them as Windows user environment variables and restart Ollama.")
    return actual


def ollama_version(base_url: str, client: httpx.Client) -> str:
    """The version of the running Ollama server (GET /api/version)."""
    try:
        return client.get(f"{base_url.rstrip('/')}/api/version").json()["version"]
    except httpx.TransportError as e:
        raise LLMUnavailableError(f"Ollama not reachable at {base_url}: {e}") from e
