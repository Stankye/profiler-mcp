"""Subprocess execution for profiler CLIs.

One narrow contract: build argv, run it with a deadline, hand back exit code
and both streams. Interpretation (exit!=0 meaning, stdout parsing) belongs to
the per-tool modules — neither vendor documents numeric exit codes, so nothing
here assigns meaning beyond zero/nonzero.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp.exceptions import ToolError


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    elapsed_sec: float

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def run_command(
    argv: list[str],
    *,
    timeout_sec: float,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a profiler CLI invocation. Raises ToolError on timeout or missing binary."""
    import os
    import time

    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(cwd) if cwd else None,
            env=full_env,
        )
    except FileNotFoundError as e:
        raise ToolError(
            f"Profiler binary not found: {argv[0]!r}. "
            "Run the *_check tool to see how the binary is resolved, or set "
            "VTUNE_MCP_BIN / UPROF_MCP_BIN."
        ) from e
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        raise ToolError(
            f"Profiler command timed out after {timeout_sec:.0f}s: {' '.join(argv)}. "
            "Partial output: " + stdout[-500:]
        ) from e

    return CommandResult(
        argv=list(argv),
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        elapsed_sec=time.monotonic() - start,
    )


def require_success(result: CommandResult, context: str) -> CommandResult:
    """Fail with an actionable ToolError when the CLI reported failure."""
    if result.ok:
        return result
    detail = (result.stderr.strip() or result.stdout.strip())[-1000:] or "no diagnostic output"
    raise ToolError(f"{context} failed (exit {result.exit_code}): {detail}")
