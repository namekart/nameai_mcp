# nameai-mcp

A remote MCP server exposing a handful of name.ai's public, no-auth-required
APIs as tools: domain search/availability, WHOIS lookup, TLD registration
pricing, TLD requirements, and marketplace browsing. See
[src/nameai_mcp/server.py](src/nameai_mcp/server.py) for the tool definitions
and [src/nameai_mcp/nameai_client.py](src/nameai_mcp/nameai_client.py) for the
HTTP client that talks to name.ai.

## Endpoints

- `GET /health` — health check.
- `POST /mcp` (and `GET /mcp` for the SSE stream) — the MCP streamable-http
  endpoint. This is the URL an MCP client/host connects to.

## Configuration

- `NAMEAI_API_BASE_URL` — base URL of the name.ai API this server calls.
  Defaults to `https://name.ai`.
- `HOST` / `PORT` — bind address for the server itself. Default `0.0.0.0:8000`.

## Local development

```sh
uv sync
uv run uvicorn nameai_mcp.app:app --reload
```

## Docker

```sh
docker build -t nameai-mcp .
docker run -p 8000:8000 nameai-mcp
```

The image runs `nameai-mcp` (the `main()` entry point in
[src/nameai_mcp/\_\_init\_\_.py](src/nameai_mcp/__init__.py)), which reads
`HOST`/`PORT` from the environment — pass `-e PORT=...` if your platform
injects a different port.

## Deploying

Any host that can run the Docker image works. To make it reachable by AI
agents as `https://mcp.name.ai`, DNS for `name.ai` is on Cloudflare — add an
`A`/`CNAME` record for the `mcp` subdomain pointing at wherever this
container runs, and terminate TLS there (e.g. via Coolify/Traefik if hosted
alongside the rest of nameaiv1).

Being reachable isn't the same as being *discovered* — nothing on
`name.ai` currently points at this server. For an agent (or a scanner like
ora) to find it, name.ai itself needs a pointer to it, e.g. a line in
`/llms.txt` or a `.well-known/mcp.json` manifest. That's a change in the
nameaiv1 repo, not this one.
