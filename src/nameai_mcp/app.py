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
    }


# streamable_http_app() registers its own endpoint internally at "/mcp", so
# mounting it here at root gives a clean external path (GET /health, POST/GET
# /mcp) instead of a doubled-up "/mcp-server/mcp". /health above is registered
# first and matches exactly, so it isn't swallowed by this catch-all mount.
app.mount("/", mcp_app)
