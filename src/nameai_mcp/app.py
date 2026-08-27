import os

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

from nameai_mcp.server import mcp

# streamable_http_app()'s own default (when neither `host` nor
# `transport_security` is passed) auto-enables DNS-rebinding protection with
# an allow-list of only 127.0.0.1/localhost — correct for local dev, but it
# means every request from a real deployed domain gets rejected with 421
# "Invalid Host header". MCP_ALLOWED_HOSTS lets a deploy add its real
# hostname(s) (comma-separated, e.g. "nameai-mcp.h.namekart.com,mcp.name.ai")
# without a code change; local dev keeps working via the defaults below even
# when it's unset.
_LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
_extra_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]

mcp_app = mcp.streamable_http_app(
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_LOCAL_HOSTS + _extra_hosts,
        allowed_origins=_LOCAL_ORIGINS + [f"https://{h}" for h in _extra_hosts],
    )
)

app = FastAPI(lifespan=mcp_app.router.lifespan_context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# RFC 9728 Protected Resource Metadata — a plain static document, published
# by hand rather than via the SDK's own auto-generated route. The SDK only
# generates this when MCPServer(auth=..., token_verifier=...) is set, and
# token_verifier wraps the entire /mcp endpoint in RequireAuthMiddleware,
# requiring a token for the 3 public tools too — not something we want (see
# server.py). Publishing this document doesn't require any enforcement
# logic, so it's safe to hand-write independent of that constraint.
_NAMEAI_API_BASE_URL = os.environ.get("NAMEAI_API_BASE_URL", "https://name.ai")
_MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://nameai-mcp.h.namekart.com")


@app.get("/.well-known/oauth-protected-resource")
def oauth_protected_resource() -> dict:
    return {
        "resource": _MCP_PUBLIC_URL,
        "authorization_servers": [_NAMEAI_API_BASE_URL],
        "scopes_supported": ["pricing:read"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{_NAMEAI_API_BASE_URL}/auth.md",
    }


# Server card on the MCP host itself. name.ai serves the canonical copy at
# the same path; scanners that take the MCP URL as their subject (rather than
# the brand domain) look for it on this origin, so it's mirrored here.
@app.get("/.well-known/mcp/server-card.json")
async def mcp_server_card() -> dict:
    # tools[] is built from the live registry so the card can never drift
    # from what tools/list returns.
    tools = [
        {
            "name": t.name,
            "description": (t.description or "").strip().split("\n\n")[0],
            "inputSchema": t.input_schema,
            **({"annotations": t.annotations.model_dump(exclude_none=True)} if t.annotations else {}),
        }
        for t in await mcp.list_tools()
    ]
    return {
        "name": "name-ai",
        "displayName": "Name.ai MCP Server",
        "description": (
            "Domain search/availability, WHOIS lookup, TLD registration pricing, and TLD "
            "registration requirements as MCP tools. All tools work without authentication; "
            f"OAuth sign-in (see {_NAMEAI_API_BASE_URL}/auth.md) additionally unlocks real "
            "marketplace prices on domain searches."
        ),
        "version": "1.0.0",
        "serverUrl": f"{_MCP_PUBLIC_URL}/mcp",
        "url": f"{_MCP_PUBLIC_URL}/mcp",
        "transport": "streamable-http",
        "protocolVersion": "2025-06-18",
        "icon": f"{_NAMEAI_API_BASE_URL}/logo.png",
        "iconUrl": f"{_NAMEAI_API_BASE_URL}/logo.png",
        "publisher": {"name": "Name.ai", "url": _NAMEAI_API_BASE_URL},
        "homepage": f"{_NAMEAI_API_BASE_URL}/developers",
        "repository": "https://github.com/namekart/nameai_mcp",
        "registry": {"name": "ai.name/nameai-mcp", "url": "https://registry.modelcontextprotocol.io/v0/servers?search=ai.name/nameai-mcp"},
        "auth": {
            "type": "oauth2.1",
            "optional": True,
            "authorization_server_metadata": f"{_NAMEAI_API_BASE_URL}/.well-known/oauth-authorization-server",
            "protected_resource_metadata": f"{_MCP_PUBLIC_URL}/.well-known/oauth-protected-resource",
            "docs": f"{_NAMEAI_API_BASE_URL}/auth.md",
        },
        "tools": tools,
    }


# streamable_http_app() registers its own endpoint internally at "/mcp", so
# mounting it here at root gives a clean external path (GET /health, POST/GET
# /mcp) instead of a doubled-up "/mcp-server/mcp". /health above is registered
# first and matches exactly, so it isn't swallowed by this catch-all mount.
app.mount("/", mcp_app)
