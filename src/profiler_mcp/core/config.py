"""Server configuration: binary resolution, mock mode, results location.

Resolution order for the profiler binary (per docs/DESIGN.md):
  1. Explicit env override (VTUNE_MCP_BIN / UPROF_MCP_BIN)
  2. Bare name on PATH
  3. Conventional install locations
Mode selection (PROFILER_MCP_MODE): "real", "mock", or "auto" (default) —
auto uses the real binary when found, otherwise the in-package mock.
"""

from __future__ import annotations

import glob
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .models import Mode

VTUNE_DEFAULT_PATHS = [
    "/opt/intel/oneapi/vtune/latest/bin64/vtune",
    str(Path.home() / "intel/oneapi/vtune/latest/bin64/vtune"),
    r"C:\Program Files (x86)\Intel\oneAPI\vtune\latest\bin64\vtune.exe",
]

UPROF_GLOB_PATTERNS = [
    "/opt/AMDuProf_*/bin/AMDuProfCLI",
    r"C:\Program Files\AMD\AMDuProf\bin\AMDuProfCLI.exe",
]

_MOCK_SCRIPTS = {"vtune": "vtune_mock.py", "uprof": "uprof_mock.py"}
_BIN_ENV = {"vtune": "VTUNE_MCP_BIN", "uprof": "UPROF_MCP_BIN"}
_BIN_NAMES = {"vtune": "vtune", "uprof": "AMDuProfCLI"}


@dataclass(frozen=True)
class ServerConfig:
    server: str  # "vtune" | "uprof"
    mode: Mode
    binary: str  # what we report to users (real path, mock script path, or unresolved name)
    argv_prefix: list[str] = field(default_factory=list)  # how to actually invoke it
    results_dir: Path = field(default_factory=Path)
    timeout_grace: float = 120.0

    @property
    def available(self) -> bool:
        return self.mode != "unavailable"


def _find_real_binary(server: str) -> str | None:
    env_bin = os.environ.get(_BIN_ENV[server])
    if env_bin:
        return env_bin if Path(env_bin).is_file() else None
    on_path = shutil.which(_BIN_NAMES[server])
    if on_path:
        return on_path
    if server == "vtune":
        candidates = [p for p in VTUNE_DEFAULT_PATHS if Path(p).is_file()]
        return candidates[0] if candidates else None
    # uprof: version-sorted glob, newest install wins
    hits: list[str] = []
    for pattern in UPROF_GLOB_PATTERNS:
        hits.extend(glob.glob(pattern))
    return sorted(hits)[-1] if hits else None


def _mock_script(server: str) -> Path | None:
    env_mock = os.environ.get("PROFILER_MCP_MOCK_BIN")
    if env_mock and Path(env_mock).is_file():
        return Path(env_mock)
    try:
        path = resources.files("profiler_mcp.mocks") / _MOCK_SCRIPTS[server]
        with resources.as_file(path) as concrete:
            return concrete if concrete.is_file() else None
    except (ModuleNotFoundError, FileNotFoundError):
        return None


def resolve(server: str) -> ServerConfig:
    """Build the effective configuration for one server from the environment."""
    if server not in _MOCK_SCRIPTS:
        raise ValueError(f"unknown server {server!r}")

    requested = os.environ.get("PROFILER_MCP_MODE", "auto").lower()
    if requested not in ("auto", "real", "mock"):
        requested = "auto"

    results_base = os.environ.get("PROFILER_MCP_RESULTS_DIR")
    results_dir = (
        Path(results_base) / server if results_base else Path.home() / ".profiler-mcp" / server
    )
    grace = float(os.environ.get("PROFILER_MCP_TIMEOUT_GRACE", "120"))

    real = _find_real_binary(server) if requested in ("auto", "real") else None
    if requested in ("auto", "real") and real:
        return ServerConfig(
            server=server,
            mode="real",
            binary=real,
            argv_prefix=[real],
            results_dir=results_dir,
            timeout_grace=grace,
        )

    if requested in ("auto", "mock"):
        mock = _mock_script(server)
        if mock:
            return ServerConfig(
                server=server,
                mode="mock",
                binary=str(mock),
                argv_prefix=[sys.executable, str(mock)],
                results_dir=results_dir,
                timeout_grace=grace,
            )

    return ServerConfig(
        server=server,
        mode="unavailable",
        binary=os.environ.get(_BIN_ENV[server], _BIN_NAMES[server]),
        argv_prefix=[],
        results_dir=results_dir,
        timeout_grace=grace,
    )


def platform_summary() -> str:
    return f"{platform.system()} {platform.release()} {platform.machine()}"
