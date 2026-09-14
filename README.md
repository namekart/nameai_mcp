# nameai-mcp

A remote MCP server exposing a handful of name.ai's public, no-auth-required
APIs as tools: domain search/availability, WHOIS lookup, TLD registration
pricing, and TLD requirements. See
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

Any host that can run the Docker image works. It is deployed through Coolify
on the Hetzner server and served at **`https://mcp.name.ai/mcp`**
(streamable-http), with Traefik terminating TLS. The original hostname,
`https://nameai-mcp.h.namekart.com/mcp`, still routes to the same container, so
client configs written against it keep working.

`mcp.name.ai` is a DNS-only A record to the Hetzner box. It exists because
scanners and MCP tooling look for a server at `mcp.<domain>` instead of reading
the URL out of a manifest — ora's scanner was watched, in this container's own
access log, never dialling the manifest's `mcpUrl` during a scan. Adding a
hostname needs two things besides DNS: the domain on the Coolify app, and the
host appended to `MCP_ALLOWED_HOSTS`, without which the SDK's DNS-rebinding
guard answers it with 421.

The server calls the public API at `NAMEAI_API_BASE_URL`, default
`https://name.ai`. Since name.ai moved to Hetzner that resolves to the same
host this container runs on, so the calls leave the container, reach the
host's own public IP, and come back in through Traefik. That hairpin works
here and is left in place deliberately: talking to the API exactly the way an
outside client would is the point of this server.

Being reachable isn't the same as being discovered — and that part is done.
`name.ai` advertises this server in four places:

- `https://name.ai/.well-known/mcp.json` — manifest
- `https://name.ai/.well-known/mcp/server-card.json` — server card
- `https://name.ai/llms.txt` — in both the endpoint list and the tool guidance
- the MCP Registry, namespace `ai.name`, domain-verified

All four live in the nameaiv1 repo. If the deployed URL changes, they change
with it — otherwise agents keep being pointed at the old one.
