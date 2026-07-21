# intellikit

## Summary
The AMD uProf MCP server lives in the `uprof_mcp/` subdirectory of the IntelliKit monorepo (https://github.com/AMDResearch/intellikit), AMD Research's toolkit of seven packages for AMD GPU/CPU performance work (Kerncap, Metrix, Linex, Nexus, rocm_mcp, uprof_mcp, Accordo). It is pure Python (>=3.10) built on FastMCP (`fastmcp>=2.0.0`), packaged with setuptools/uv. The whole component is tiny: four source files under `uprof_mcp/src/uprof_mcp/` (`__init__.py`, `_version.py`, `uprof_profiler.py`, `uprof_profiler_mcp.py`), a README, `pyproject.toml`, `uv.lock`, and one LangChain example (`uprof_mcp/examples/uprof_profiler.py`).

The server (`FastMCP(name="uprof_profiler", instructions="MCP server for profiling x86 CPU code for hotspots using AMD uProf.")`) exposes exactly ONE tool: `profile_for_hotspots(ctx, executable, executable_arguments, output_dir=None)` — "Profiles the x86 executable with the arguments to identify performance hotspots." It returns a `str`. The console entry point is `uprof-profiler-mcp` -> `uprof_mcp.uprof_profiler_mcp:main`, supporting `--transport stdio` (default) or `http` (streamable-http, defaults host 127.0.0.1, port 8000, path /uprof_mcp). Under the hood, `UProfProfiler.find_hotspots()` in `uprof_profiler.py` shells out to AMDuProfCLI with the argv `[profiler_exe, "profile", "--config", "hotspots", "--output-dir", <dir>, "--log-path", <dir>, <executable>, *executable_args]` (default timeout 180 s), then regex-parses AMDuProfCLI stdout for "Generated data files path: (.*)" and "Generated report file: (.*)" to build a `UProfProfilerResult` dataclass (`results_path`, `report_path`). The CLI binary is resolved via env var `INTELLIKIT_UPROF_CLI`, then constructor arg `uprof`, then the hard-coded default `/opt/AMDuProf_5.1-701/bin/AMDuProfCLI`. Error paths raise FileNotFoundError, TimeoutExpired, CalledProcessError, or RuntimeError.

Profile data handling is minimal and raw: the MCP tool simply opens the report file AMDuProfCLI generated (`with result.report_path.open() as file: return file.read()`) and returns the ENTIRE report contents to the model with no CSV parsing, summarization, truncation, or filtering. (AMDuProfCLI's hotspots config auto-generates a CSV-format report; the intellikit code itself is format-agnostic and never parses it.) License is MIT — "Copyright (c) 2025 Advanced Micro Devices, Inc. All Rights Reserved." — so reuse/adaptation is permitted with attribution/license retention; `pyproject.toml` also declares MIT. The repo ships agent SKILL.md files for accordo, kerncap, linex, metrix, and nexus (installed to Cursor/Claude/Codex via `install/skills/install.sh --target claude` etc.), but there is NO skill or prompt for uprof_mcp — it is MCP-config-only. The example demonstrates a LangChain agent using `MultiServerMCPClient` with `{"profile": {"transport": "stdio", "command": "uprof-profiler-mcp", "args": []}}` asking for the top-5 CPU-consuming functions, plus a `--classic` non-agent mode that calls `UProfProfiler` directly.

## Key facts
- Repo: github.com/AMDResearch/intellikit; uProf MCP server is the subdirectory uprof_mcp/ (package name 'uprof-mcp', description 'MCP server for profiling CPU code via AMD uprof')
- Language/framework: Python >=3.10 + FastMCP (dependency 'fastmcp>=2.0.0' from the fastmcp package, not mcp.server); setuptools>=61.0 build; uv workflow; NOT TypeScript
- Exactly one MCP tool: profile_for_hotspots(ctx: Context, executable: str|Path, executable_arguments: list[str], output_dir: str|Path|None = None) -> str; docstring: 'Profiles the x86 executable with the arguments to identify performance hotspots.'
- FastMCP server object: FastMCP(name="uprof_profiler", instructions="MCP server for profiling x86 CPU code for hotspots using AMD uProf.")
- Console script entry point: uprof-profiler-mcp -> uprof_mcp.uprof_profiler_mcp:main; main() argparse flags: --transport {stdio,http} (default stdio), --host (127.0.0.1), --port (8000), --path (/uprof_mcp); http mode uses mcp.run(transport="streamable-http", ...)
- AMDuProfCLI invocation (uprof_profiler.py, UProfProfiler.find_hotspots): subprocess argv = [profiler_exe, 'profile', '--config', 'hotspots', '--output-dir', str(output_dir), '--log-path', str(output_dir), str(executable), *executable_args]; DEFAULT_TIMEOUT = 180 seconds
- Output parsing: regex on AMDuProfCLI stdout — 'Generated data files path: (.*)' -> results_path and 'Generated report file: (.*)' -> report_path; returned as dataclass UProfProfilerResult(results_path: Path, report_path: Path)
- Profile data handling: the MCP tool returns the raw report file verbatim — `with result.report_path.open() as file: return file.read()` — no CSV parsing, summarizing, or truncation in the repo code
- uProf CLI path resolution priority: env var INTELLIKIT_UPROF_CLI > constructor arg uprof > DEFAULT_EXE_PATH '/opt/AMDuProf_5.1-701/bin/AMDuProfCLI' (README example uses /opt/AMDuProf_5.3-521/bin/AMDuProfCLI)
- License: MIT — 'Copyright (c) 2025 Advanced Micro Devices, Inc. All Rights Reserved.' (repo-root LICENSE; pyproject also says MIT) — code can be reused/adapted with copyright+license notice retained
- Full uprof_mcp file list: uprof_mcp/README.md, uprof_mcp/pyproject.toml, uprof_mcp/uv.lock, uprof_mcp/examples/uprof_profiler.py, uprof_mcp/src/uprof_mcp/{__init__.py, _version.py, uprof_profiler.py, uprof_profiler_mcp.py}
- Repo top level: accordo/ apptainer/ docker/ docs/ install/ kerncap/ linex/ metrix/ nexus/ rocm_mcp/ uprof_mcp/ plus AGENTS.md, CMakeLists.txt, LICENSE, README.md, ruff.toml, .devcontainer/, .github/, .readthedocs.yaml
- Skills shipped: SKILL.md files at accordo/skill/, kerncap/skill/, linex/skill/, metrix/skill/, nexus/skill/ installed via install/skills/install.sh (--target cursor|claude|codex|generic); NO skill or prompt exists for uprof_mcp (no path in the repo contains 'prompt')
- Sibling MCP servers in rocm_mcp/: hip-compiler-mcp, hip docs, rocminfo, amd-smi-mcp; other packages expose metrix-mcp and kerncap-mcp console scripts
- Errors raised by find_hotspots: FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError, RuntimeError (when stdout regexes fail to match)
- Example (uprof_mcp/examples/uprof_profiler.py): LangChain agent via langchain_mcp_adapters.client.MultiServerMCPClient with config {'profile': {'transport': 'stdio', 'command': 'uprof-profiler-mcp', 'args': []}}; asks for top-5 CPU-consuming functions; --classic flag bypasses the agent and calls UProfProfiler directly; examples deps: langchain>=1.0.5, langchain-mcp-adapters>=0.1.12, langchain-openai>=1.0.2, python-dotenv>=1.2.1

## Example commands
    export INTELLIKIT_UPROF_CLI=/opt/AMDuProf_5.3-521/bin/AMDuProfCLI
    uv run --directory /path/to/uprof_mcp uprof-profiler-mcp
    {
      "mcpServers": {
        "uprof-profiler-mcp": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/uprof_mcp", "uprof-profiler-mcp"],
          "env": {
            "INTELLIKIT_UPROF_CLI": "/opt/AMDuProf_5.3-521/bin/AMDuProfCLI"
          }
        }
      }
    }
    # Underlying CLI command the server constructs:
    AMDuProfCLI profile --config hotspots --output-dir <output_dir> --log-path <output_dir> <executable> [executable_args...]
    from uprof_mcp.uprof_profiler import UProfProfiler
    import tempfile
    
    profiler = UProfProfiler()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = profiler.find_hotspots(
            output_dir=tmpdir,
            executable="./my_app",
            executable_args=["arg1", "arg2"],
        )
    # result.report_path, result.results_path
    install/skills/install.sh --target claude   # installs SKILL.md files for kerncap/metrix/linex/nexus/accordo (uprof has none)
    uv sync --dev && uv run uprof-profiler-mcp   # dev setup and local test run

## Caveats
- The report format returned to the model: the repo code never parses it — it returns report_path contents verbatim. That AMDuProfCLI's 'profile --config hotspots' emits a CSV report (report.csv) is standard uProf behavior, not something asserted in the intellikit source I read; verify against your uProf version.
- Returning the entire report file raw can be very large for big binaries — there is no truncation, so an adapted design may want to summarize or window the CSV before handing it to the model.
- Hard-coded default CLI path /opt/AMDuProf_5.1-701/bin/AMDuProfCLI is Linux-specific and version-pinned; the server is x86-Linux oriented (relevant since your working dir is a vtune-mcp project on macOS — AMD uProf does not run on macOS).
- Source-file contents were extracted via WebFetch summarization of raw.githubusercontent.com pages, not a local clone; method signatures and the subprocess argv were reproduced by the fetch model and matched across the README and two independent fetches of the MCP file, but exact whitespace/line numbers were not verified.
- The uprof_mcp README mentions pytest, but the recursive git tree listing showed no tests/ directory under uprof_mcp/ — test coverage for this component appears absent or lives elsewhere.
- Version pins in pyproject (e.g. pytest>=9.0.1, ruff>=0.14.4) and repo state reflect the main branch as of 2026-07-21; the repo is actively developed and details may drift.
- MIT license permits reuse/adaptation (including commercially) provided you retain the copyright notice ('Copyright (c) 2025 Advanced Micro Devices, Inc.') and the MIT license text in copies or substantial portions.