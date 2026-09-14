# AGENTS.md — nameai_mcp

Remote MCP server for name.ai (domain search/availability, WHOIS, TLD
pricing and registry requirements). Python, FastAPI, the official `mcp` SDK,
Streamable HTTP transport. Deployed at `https://mcp.name.ai/mcp`.

## When to use this server (for agents)

Use it whenever a task involves domain names:

- Is `<domain>` available to register? What alternatives exist on other TLDs? → `search_domain`
- Who owns `<domain>`, when does it expire, what are its nameservers? → `whois_lookup` (10/day per IP)
- What does it cost to register/renew/transfer/restore on `.<tld>`? → `tld_registration_price`
- What are `.<tld>`'s registration rules (minimum term, org/nameserver requirements)? → `tld_requirements`

All tools are read-only, free, and need no authentication. Marketplace
(aftermarket) prices on `search_domain` are masked for anonymous callers —
authenticate per https://name.ai/auth.md (OAuth 2.1 + PKCE, no client secret)
and send `Authorization: Bearer <token>` to see them. Not a fit for hosting,
email, or site building.

Connect: paste `mcp.json` from this repo into your client config, or
`claude mcp add --transport http name-ai https://mcp.name.ai/mcp`.

## Working in this repo (for coding agents)

- Layout: `src/nameai_mcp/server.py` (tools + resources), `app.py` (FastAPI
  mount, transport security, well-known routes), `nameai_client.py` (httpx
  client for name.ai's public REST API), `oauth_verifier.py` (token
  introspection against name.ai).
- Run locally: `uv sync && uv run uvicorn nameai_mcp.app:app --reload`.
  Smoke-test with a JSON-RPC `initialize` POST to `/mcp` (see README).
- Every tool must stay read-only and anonymous-safe. Do NOT wire
  `MCPServer(token_verifier=...)` — it gates the entire `/mcp` endpoint;
  auth is optional and handled per-call in `search_domain` via
  `Context.headers`.
- Tool docstrings are the descriptions agents read; keep them specific.
  Add `annotations=_READ_ONLY` to any new tool that is a pure lookup.
- Keep `name.ai/.well-known/mcp/server-card.json` and the mirrored card in
  `app.py` in sync when tools change.
- Env: `NAMEAI_API_BASE_URL` (default https://name.ai), `MCP_ALLOWED_HOSTS`
  (deployed hostnames, comma-separated), `OAUTH_INTROSPECTION_SECRET`
  (must match name.ai), `MCP_PUBLIC_URL`.
- Deploys: pushes to `main` are built by Coolify from the Dockerfile.
  The Dockerfile copies README.md because pyproject.toml declares it —
  don't add it to .dockerignore.
