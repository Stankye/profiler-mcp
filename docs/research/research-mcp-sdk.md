# mcp-sdk

## Summary
As of 2026-07-21 the official MCP Python SDK ("mcp" on PyPI, github.com/modelcontextprotocol/python-sdk) is at stable v1.28.1 (released 2026-06-26), requiring Python >=3.10; `pip install mcp` still resolves to the 1.x line. A major v2 rewrite is in beta on the main branch (v2.0.0b2, 2026-07-14), with stable v2.0.0 targeted for ~2026-07-27/28 alongside the MCP 2026-07-28 spec. In v2 the server class is renamed FastMCP -> MCPServer (`from mcp.server import MCPServer`) and a first-class `from mcp import Client` appears; v1 docs and code now live on the `v1.x` branch, and the docs site is py.sdk.modelcontextprotocol.io. For production today, use v1.x and pin `mcp>=1.28,<2`. The v1 FastMCP API is unchanged in name: `from mcp.server.fastmcp import FastMCP` (also re-exported as `from mcp.server import FastMCP`), with decorators `@mcp.tool()`, `@mcp.resource("uri://{param}")`, `@mcp.prompt()`. `@mcp.tool()` accepts name, title, description, annotations (ToolAnnotations), icons, meta, structured_output. Structured output is automatic from return-type annotations: Pydantic BaseModel subclasses, TypedDicts, dataclasses/classes with type hints, and dict[str, T] become output schemas with automatic validation; primitives and generics (list, Union, etc.) are wrapped in {"result": value}; suppress with structured_output=False; return CallToolResult directly (optionally `Annotated[CallToolResult, SomeModel]`) for full control including _meta. The Context object is injected into any tool/resource parameter annotated `Context` (typed as `Context[ServerSession, AppContextType]`, imports: `from mcp.server.fastmcp import Context, FastMCP`; `from mcp.server.session import ServerSession`): `await ctx.info/debug/warning/error(...)`, `await ctx.report_progress(progress, total=None, message=None)`, `await ctx.read_resource(uri)`, `await ctx.elicit(message, schema=PydanticModel)` (form-mode elicitation returning ElicitationResult with .action in accept/decline/cancel and validated .data), `await ctx.elicit_url(...)` (URL-mode elicitation, 2025-11-25 spec), plus `ctx.session.send_tool_list_changed()/send_resource_list_changed()/send_prompt_list_changed()/send_resource_updated(uri)/create_message(...)` (sampling) and `ctx.request_context.lifespan_context` for typed lifespan state. Lifespan is an `@asynccontextmanager` taking the FastMCP instance and yielding a typed context, passed as `FastMCP("My App", lifespan=app_lifespan)`.

Transports: `mcp.run()` defaults to stdio; `mcp.run(transport="streamable-http")` serves at http://host:port/mcp (default port 8000). Streamable HTTP is the recommended production transport, ideally `FastMCP(name, stateless_http=True, json_response=True)`; POST bodies are capped at 4 MiB by default (`max_request_body_size` to change). For ASGI deployment, mount `mcp.streamable_http_app()` in Starlette with `mcp.session_manager.run()` entered in the app lifespan; SSE (`transport="sse"`, `mcp.sse_app()`) is officially superseded by streamable HTTP, and WebSocket transport plus the experimental tasks API got deprecation warnings in v1.28. Dev workflow: `uv run mcp dev server.py` (MCP Inspector), `uv run mcp run server.py`, `uv run mcp install server.py` (Claude Desktop); note `mcp run`/`mcp dev` only work with FastMCP servers, not the low-level `mcp.server.lowlevel.Server`. Testing is in-memory: `from mcp.shared.memory import create_connected_server_and_client_session` — its current v1.x signature accepts `Server[Any] | FastMCP` directly (older SDKs required passing `mcp._mcp_server`; the docs admit the name is slated for improvement in v2). The documented pytest pattern uses anyio (`@pytest.mark.anyio` with an `anyio_backend` fixture returning "asyncio"), a `client_session` async fixture wrapping `create_connected_server_and_client_session(app, raise_exceptions=True)`, and inline-snapshot assertions against `CallToolResult(content=[TextContent(...)], structuredContent={...})`.

Packaging/registration: official servers use hatchling with a `[project.scripts]` console entry point (e.g. `mcp-server-git = "mcp_server_git:main"` where main() calls mcp.run()), which is exactly what `uvx <package-name>` executes. Claude Code registration: `claude mcp add [options] <name> -- <command> [args...]` for stdio (everything after `--` is the server command), `claude mcp add --transport http <name> <url>` for remote; `--scope local` (default, stored in ~/.claude.json), `--scope project` (writes the shareable `.mcp.json` at the project root), `--scope user`. Project `.mcp.json` format: `{"mcpServers": {"<name>": {"command": "...", "args": [], "env": {}}}}`; HTTP entries use `{"type": "http", "url": ...}` and `"streamable-http"` is accepted as an alias for `"http"`; `${VAR}` / `${VAR:-default}` expansion is supported; Claude Code prompts to approve project-scope servers (`claude mcp reset-project-choices` resets). 2025-2026 spec features in the SDK: ToolAnnotations hints (`from mcp.types import ToolAnnotations` — title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint, all advisory), ResourceLink (`types.ResourceLink`, type="resource_link") returnable in tool results, EmbeddedResource results, CallToolResult `_meta`, Icons (`from mcp.server.fastmcp import Icon` on server/tools/resources/prompts), form+URL elicitation (incl. `UrlElicitationRequiredError` -> -32042 and `ctx.session.send_elicit_complete(id)`), completions with context_arguments, resource subscriptions (low-level `@server.subscribe_resource()`), `ToolExecution.taskSupport` for task-augmented execution, and ToolError (`from mcp.server.fastmcp.exceptions import ToolError`) for isError responses.

## Key facts
- Current stable: mcp 1.28.1 on PyPI (released 2026-06-26), requires Python >=3.10; install with `uv add "mcp[cli]"` or `pip install "mcp[cli]"`; `pip install mcp` still resolves to 1.x
- v2 is pre-release only: v2.0.0a1..a3 (June 2026) -> v2.0.0b1 (June 30) -> v2.0.0b2 (2026-07-14); stable v2.0.0 targeted ~2026-07-27/28 alongside the MCP 2026-07-28 spec; v2 renames FastMCP to MCPServer (`from mcp.server import MCPServer`) and adds `from mcp import Client`; v1 lives on the `v1.x` branch
- v1 FastMCP import (still current): `from mcp.server.fastmcp import FastMCP` (re-exported as `from mcp.server import FastMCP`); decorators `@mcp.tool()`, `@mcp.resource("uri://{param}")`, `@mcp.prompt()`
- @mcp.tool() signature (v1.x source): tool(name=None, title=None, description=None, annotations: ToolAnnotations | None = None, icons: list[Icon] | None = None, meta: dict | None = None, structured_output: bool | None = None)
- Structured output auto-generates output schemas from return annotations: Pydantic BaseModel, TypedDict, dataclasses/classes with type hints, dict[str, T]; primitives and generics wrapped as {"result": value}; results validated against the schema; disable with structured_output=False; classes without type hints fall back to unstructured
- Context injection: annotate a parameter `ctx: Context[ServerSession, AppContextType]` (imports: `from mcp.server.fastmcp import Context, FastMCP`; `from mcp.server.session import ServerSession`); methods: await ctx.info/debug/warning/error(msg), await ctx.report_progress(progress, total=None, message=None), await ctx.read_resource(uri), await ctx.elicit(message, schema), await ctx.elicit_url(...); ctx.request_context.lifespan_context holds typed lifespan state
- Lifespan: @asynccontextmanager async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]: yield AppContext(db=...); pass as FastMCP("My App", lifespan=app_lifespan)
- Transports: mcp.run() = stdio (default); mcp.run(transport="streamable-http") serves at /mcp (port 8000 default); production recommendation: FastMCP(name, stateless_http=True, json_response=True); ASGI mounting via mcp.streamable_http_app() + `async with mcp.session_manager.run()` in Starlette lifespan; SSE superseded; WebSocket transport and experimental tasks API deprecated in 1.28
- Testing: `from mcp.shared.memory import create_connected_server_and_client_session`; v1.x signature accepts `Server[Any] | FastMCP` directly (no more mcp._mcp_server needed), kwargs include raise_exceptions, sampling_callback, elicitation_callback; pytest pattern uses @pytest.mark.anyio + anyio_backend fixture returning "asyncio" + inline-snapshot; assert against CallToolResult(content=[TextContent(type="text", text="3")], structuredContent={"result": 3})
- CLI (with mcp[cli] extra): `uv run mcp dev server.py` (Inspector, --with / --with-editable flags), `uv run mcp run server.py`, `uv run mcp install server.py` (Claude Desktop, -v KEY=val / -f .env); mcp run/dev only support FastMCP, not low-level Server
- uvx packaging convention (official servers repo): hatchling build backend + [project.scripts] entry point, e.g. `mcp-server-git = "mcp_server_git:main"`, so `uvx mcp-server-git` runs main() which calls mcp.run(); dependency pin `mcp>=1.0.0`
- claude mcp add: `claude mcp add [options] <name> -- <command> [args...]` (stdio; -- separates Claude flags from the server command), `claude mcp add --transport http <name> <url>`; scopes: local (default, ~/.claude.json), project (.mcp.json in repo root, team-shared, requires approval), user (~/.claude.json all projects); precedence local > project > user
- .mcp.json project format: {"mcpServers": {"<name>": {"command": "/path/to/server", "args": [], "env": {}}}}; HTTP: {"type": "http", "url": "..."} with "streamable-http" accepted as alias for "http"; supports ${VAR} and ${VAR:-default} expansion; per-server "timeout" (ms) field supported
- Tool annotations: `from mcp.types import ToolAnnotations` with fields title, readOnlyHint (default false), destructiveHint (default true), idempotentHint (default false), openWorldHint (default true) — all advisory hints; passed via @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
- 2025-2026 spec features in v1.x SDK: form-mode elicitation (ctx.elicit with Pydantic schema, ElicitationResult.action in accept/decline/cancel), URL-mode elicitation (ctx.elicit_url, UrlElicitationRequiredError -> -32042, ctx.session.send_elicit_complete), ResourceLink (type="resource_link") in tool results, EmbeddedResource results, CallToolResult _meta for client-only data, Icon support, sampling via ctx.session.create_message, completions with context_arguments, list-changed notifications (send_tool_list_changed etc.), resource subscriptions, ToolExecution.taskSupport
- Error handling: raise `ToolError` (from mcp.server.fastmcp.exceptions) for expected errors; unhandled exceptions auto-convert to isError=True responses; return CallToolResult(isError=True) for full control
- Streamable HTTP POST bodies capped at 4 MiB by default; raise via FastMCP(name, max_request_body_size=8*1024*1024)

## Example commands
    # Minimal server (docs/testing.md, v1.x, verbatim) — server.py
    from mcp.server import FastMCP
    
    app = FastMCP("Calculator")
    
    @app.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
    # In-memory pytest test (docs/testing.md, verbatim) — test_server.py
    from collections.abc import AsyncGenerator
    
    import pytest
    from inline_snapshot import snapshot
    from mcp.client.session import ClientSession
    from mcp.shared.memory import create_connected_server_and_client_session
    from mcp.types import CallToolResult, TextContent
    
    from server import app
    
    
    @pytest.fixture
    def anyio_backend():
        return "asyncio"
    
    
    @pytest.fixture
    async def client_session() -> AsyncGenerator[ClientSession]:
        async with create_connected_server_and_client_session(app, raise_exceptions=True) as _session:
            yield _session
    
    
    @pytest.mark.anyio
    async def test_call_add_tool(client_session: ClientSession):
        result = await client_session.call_tool("add", {"a": 1, "b": 2})
        assert result == snapshot(
            CallToolResult(
                content=[TextContent(type="text", text="3")],
                structuredContent={"result": 3},
            )
        )
    # Structured output (docs/server.md, excerpt verbatim)
    from typing import TypedDict
    from pydantic import BaseModel, Field
    from mcp.server.fastmcp import FastMCP
    
    mcp = FastMCP("Structured Output Example")
    
    class WeatherData(BaseModel):
        temperature: float = Field(description="Temperature in Celsius")
        humidity: float = Field(description="Humidity percentage")
        condition: str
        wind_speed: float
    
    @mcp.tool()
    def get_weather(city: str) -> WeatherData:
        """Get weather for a city - returns structured data."""
        return WeatherData(temperature=22.5, humidity=45.0, condition="sunny", wind_speed=5.2)
    
    class LocationInfo(TypedDict):
        latitude: float
        longitude: float
        name: str
    
    @mcp.tool()
    def get_location(address: str) -> LocationInfo:
        """Get location coordinates"""
        return LocationInfo(latitude=51.5074, longitude=-0.1278, name="London, UK")
    # Context + progress (docs/server.md, verbatim)
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession
    
    mcp = FastMCP(name="Progress Example")
    
    @mcp.tool()
    async def long_running_task(task_name: str, ctx: Context[ServerSession, None], steps: int = 5) -> str:
        """Execute a task with progress updates."""
        await ctx.info(f"Starting: {task_name}")
        for i in range(steps):
            progress = (i + 1) / steps
            await ctx.report_progress(progress=progress, total=1.0, message=f"Step {i + 1}/{steps}")
            await ctx.debug(f"Completed step {i + 1}")
        return f"Task '{task_name}' completed"
    # Lifespan (docs/server.md, excerpt verbatim)
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from dataclasses import dataclass
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.session import ServerSession
    
    @dataclass
    class AppContext:
        db: Database
    
    @asynccontextmanager
    async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
        db = await Database.connect()
        try:
            yield AppContext(db=db)
        finally:
            await db.disconnect()
    
    mcp = FastMCP("My App", lifespan=app_lifespan)
    
    @mcp.tool()
    def query_db(ctx: Context[ServerSession, AppContext]) -> str:
        """Tool that uses initialized resources."""
        db = ctx.request_context.lifespan_context.db
        return db.query()
    # Transports
    mcp.run()                                # stdio (default)
    mcp.run(transport="streamable-http")     # serves http://127.0.0.1:8000/mcp
    # production config:
    mcp = FastMCP("StatelessServer", stateless_http=True, json_response=True)
    # Dev / run / install CLI
    uv run mcp dev server.py
    uv run mcp dev server.py --with pandas --with-editable .
    uv run mcp run server.py
    uv run mcp install server.py -v API_KEY=abc123
    # pyproject.toml for a uvx-runnable server (pattern from official mcp-server-git)
    [project.scripts]
    mcp-server-git = "mcp_server_git:main"
    
    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"
    # then: uvx mcp-server-git
    # Claude Code registration
    claude mcp add --transport stdio myserver -- uvx mcp-server-git
    claude mcp add --scope project --transport stdio vtune -- uv run python -m vtune_mcp
    claude mcp add --transport http notion https://mcp.notion.com/mcp
    claude mcp reset-project-choices
    # .mcp.json (project scope, verbatim format from Claude Code docs)
    {
      "mcpServers": {
        "shared-server": {
          "command": "/path/to/server",
          "args": [],
          "env": {}
        }
      }
    }
    # Tool annotations + elicitation imports
    from mcp.types import ToolAnnotations
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def list_things() -> list[str]: ...
    
    # form-mode elicitation inside a tool
    result = await ctx.elicit(message="Try another date?", schema=BookingPreferences)
    if result.action == "accept" and result.data: ...

## Caveats
- v2 is imminent: stable v2.0.0 is targeted ~2026-07-27/28 (days after today) and renames FastMCP -> MCPServer with a new mcp.Client and reworked internals. Pin `mcp>=1.28,<2` in any project you build now, and expect a migration later; `pip install mcp` currently still gives 1.x but that may flip when v2 ships.
- v1 documentation and examples moved to the `v1.x` git branch; the `main` branch README now shows v2 (MCPServer) code. Do not copy main-branch examples into a v1 project.
- create_connected_server_and_client_session accepts a FastMCP instance directly only in recent v1.x versions (it unwraps the private _mcp_server internally); older SDK versions required passing `mcp_instance._mcp_server`. The SDK maintainers say the function will be renamed/replaced in v2 (a proper in-memory Client).
- The pytest pattern relies on anyio, not pytest-asyncio: you need the `anyio_backend` fixture and `@pytest.mark.anyio`. inline-snapshot is recommended but optional.
- CallToolResult uses camelCase field names (structuredContent, isError) even though the Python API is otherwise snake_case; CallToolResult return annotations must be bare (no Optional/Union) and empty results are CallToolResult(content=[]).
- WebSocket transport and the experimental tasks API received deprecation warnings in v1.28; SSE transport is superseded by streamable HTTP (kept for backward compat).
- URL-mode elicitation (ctx.elicit_url, UrlElicitationRequiredError) is a 2025-11-25 spec feature; older clients may not support it. Elicitation enum dropdowns must use json_schema_extra={"enum": [...]} on a str field, not typing.Literal.
- Claude Code scope naming changed over time: current 'local' scope was formerly called 'project', and 'user' was 'global' — older blog posts/tutorials use the old names. Project-scoped .mcp.json servers require interactive approval in a trusted workspace before they connect.
- Some release dates reported by page-summarization were ambiguous (showing 2025); PyPI authoritatively lists 1.28.1 as released 2026-06-26. Version numbers were cross-checked against PyPI and the GitHub releases page.
- Do not confuse the official SDK's mcp.server.fastmcp.FastMCP with the third-party 'fastmcp' package (jlowin/fastmcp, now v3.x with Providers/Transforms architecture) — different API, different package.