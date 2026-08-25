# Command Reference

All commands below are run from the project root: `/Users/macbook/raunak/nameai_mcp`.

## 1. Project setup (uv)

| Command | Purpose |
|---|---|
| `uv init` | Initialize the project — creates `pyproject.toml` (with `uv_build` backend) and `.python-version`. |
| `uv add "mcp[cli]"` | Add the official Python MCP SDK (with the `mcp` CLI / Inspector extras) as a dependency. Creates `.venv/` and `uv.lock` on first run. |
| `uv add fastapi uvicorn` | Add FastAPI and Uvicorn, used to serve the MCP server over HTTP alongside regular REST routes. |
| `uv sync` | Install/update dependencies into `.venv` to match `uv.lock`, without running anything. |
| `uv run <command>` | Run a command inside the project's `.venv`, auto-syncing dependencies first. Used for everything below (`uv run mcp ...`, `uv run uvicorn ...`, etc). |
| `uv venv` | Manually create a `.venv`. **Not needed normally** — `uv add`/`uv run`/`uv sync` create it automatically. Only use `uv venv --clear` if you deliberately want to wipe and rebuild the environment. |

## 2. Running the server

| Command | Purpose |
|---|---|
| `uv run nameai-mcp` | Run the project's own entry point (`main()` in `src/nameai_mcp/__init__.py`) — starts the FastAPI app via Uvicorn on `http://127.0.0.1:8000`. MCP is mounted at `/mcp-server/mcp`, health check at `/health`. |
| `uv run uvicorn nameai_mcp.app:app --host 127.0.0.1 --port 8000` | Equivalent explicit form of the above, useful for overriding host/port without editing code. |
| `uv run mcp run src/nameai_mcp/server.py:mcp --transport stdio` | Run the raw MCP server (no FastAPI) directly over stdio. Default transport if `--transport` is omitted. |
| `uv run mcp run src/nameai_mcp/server.py:mcp --transport streamable-http` | Run the raw MCP server directly over Streamable HTTP. Serves at `http://127.0.0.1:8000/mcp`. |

## 3. MCP Inspector (debugging tools/resources/prompts)

| Command | Purpose |
|---|---|
| `uv run mcp dev src/nameai_mcp/server.py:mcp --with-editable .` | Launch the MCP Inspector with an ad-hoc **stdio** connection to the server (auto-spawns `npx @modelcontextprotocol/inspector` under the hood). This server entry is **read-only** in the Inspector UI — transport can't be changed here. |
| `npx @modelcontextprotocol/inspector` | Launch the Inspector standalone, with a **writable** server catalog. Use this when you need to add a server manually (e.g. to point at a running Streamable HTTP server via **+ Add Server**). |

### Typical HTTP debugging flow
1. `uv run mcp run src/nameai_mcp/server.py:mcp --transport streamable-http` (starts serving at `http://127.0.0.1:8000/mcp`)
2. `npx @modelcontextprotocol/inspector` (opens the writable Inspector UI)
3. In the UI: **+ Add Server** → transport **Streamable HTTP** → URL `http://127.0.0.1:8000/mcp` → Connect

## 4. Misc

| Command | Purpose |
|---|---|
| `uv run mcp --help` | List all `mcp` CLI subcommands (`version`, `dev`, `run`, `install`). |
| `uv run mcp install <file>` | Install the MCP server into the Claude Desktop app config. |
| `uv run mcp version` | Print the installed MCP SDK version. |
