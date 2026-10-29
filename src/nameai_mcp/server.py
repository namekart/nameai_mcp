from __future__ import annotations

from typing import Literal

import os

import httpx
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from nameai_mcp.nameai_client import NameAIAPIError, get_json, post_json, post_ndjson_rows
from nameai_mcp.oauth_verifier import NameAITokenVerifier
from nameai_mcp.quota import bearer_token, charge, upstream_headers
from nameai_mcp.search_app_html import SEARCH_APP_HTML, SEARCH_APP_URI

# Login required (owner decision 2026-10-16): auth + token_verifier make the
# SDK wrap the whole /mcp route in RequireAuthMiddleware. No token → 401 with
# WWW-Authenticate resource_metadata=<MCP>/.well-known/oauth-protected-resource
# (served by app.py), so MCP clients run the OAuth flow against name.ai, where
# the user signs in with X. Per-user quotas are then charged in quota.py.
_NAMEAI_API_BASE_URL = os.environ.get("NAMEAI_API_BASE_URL", "https://name.ai").rstrip("/")
_MCP_PUBLIC_URL = os.environ.get("MCP_PUBLIC_URL", "https://mcp.name.ai").rstrip("/")
# Every tool is a read-only lookup against name.ai / public registries -
# annotate so agents know calls are safe to make and repeat.
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

# MCP Apps (io.modelcontextprotocol/ui): search_domain carries
# _meta.ui.resourceUri pointing at a ui:// HTML view the host can render
# inline (availability cards). Hosts that didn't negotiate Apps still get
# the same structured/JSON result - the view is additive. The extension's
# tools and resources are consumed when MCPServer is constructed, so this
# block has to precede it.
apps = Apps()
apps.add_html_resource(
    SEARCH_APP_URI,
    SEARCH_APP_HTML,
    name="search-results",
    title="Domain availability results",
    description="Renders search_domain results as availability cards with pricing.",
    # Mirrors the <meta http-equiv="Content-Security-Policy"> inside the view:
    # inline CSS/JS only, images from name.ai, connections only to the MCP
    # server and name.ai, nothing framed.
    csp=ResourceCsp(
        connect_domains=["https://mcp.name.ai", "https://nameai-mcp.h.namekart.com", "https://name.ai"],
        resource_domains=["https://name.ai"],
        frame_domains=[],
    ),
    prefers_border=True,
)


@apps.tool(resource_uri=SEARCH_APP_URI, annotations=_READ_ONLY)
async def search_domain(domain: str, include_alternates: bool = True, ctx: Context = None) -> dict:
    """Check whether a domain is available and, for the same label, whether its
    common alternate TLDs are too (e.g. querying "acme.com" also returns
    "acme.ai", "acme.io", ...).

    Backed by POST /api/domain/search.

    Counts against the search quota (4/day after Login with X, 100/month
    once the name.ai profile is complete). Real marketplace (buy-now)
    prices are included for the signed-in user.

    Args:
        domain: A domain name to check, e.g. "example.ai".
        include_alternates: When true (default), also return sibling TLDs for
            the same label. When false, only the exact domain is returned.
    """
    quota = await charge("search_domain", ctx)
    extra_headers = upstream_headers() or {}
    # Already verified by RequireAuthMiddleware; forwarding it unmasks
    # marketplace prices upstream.
    token = bearer_token(ctx)
    if token:
        extra_headers["authorization"] = f"Bearer {token}"

    rows = await post_ndjson_rows("/api/domain/search", {"q": domain}, extra_headers=extra_headers or None)
    if not include_alternates and rows:
        primary = rows[0]["domain"]
        rows = [r for r in rows if r["domain"] == primary]
    return {"query": domain, "results": rows, "quota": quota}


mcp = MCPServer(
    name="nameai-mcp",
    version="1.0.0",
    instructions=(
        "Name.ai domain tools: check domain availability (search_domain), look up "
        "WHOIS records (whois_lookup), and get TLD registration pricing "
        "(tld_registration_price) and registry requirements (tld_requirements). "
        "All tools are read-only and need the user signed in to name.ai (Login with X, "
        "via your client's Authorize/Connect flow). Free: 3 WHOIS lookups and 4 searches "
        "per day (price and requirements lookups count as searches). After completing "
        "the name.ai profile at https://name.ai/mcp/onboard: 20 WHOIS and 100 searches "
        "per month. When a limit is hit, pass the tool's message on to the user. Cache "
        "TLD pricing/requirements, they change rarely."
    ),
    extensions=[apps],
    auth=AuthSettings(issuer_url=_NAMEAI_API_BASE_URL, resource_server_url=_MCP_PUBLIC_URL),
    token_verifier=NameAITokenVerifier(),
)

# RDAP can retry against multiple registries before falling back to DomainIQ
# (see app/api/tools/whois/route.js) — needs more headroom than other calls.
_WHOIS_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)




@mcp.tool(annotations=_READ_ONLY)
async def whois_lookup(domain: str, ctx: Context = None) -> dict:
    """Look up WHOIS/RDAP registration details for a domain: registrar,
    registrant, creation/expiration dates, nameservers.

    Backed by POST /api/tools/whois. Metered per user: 3 lookups/day after
    Login with X, 20/month once the name.ai profile is complete.

    Args:
        domain: A domain name to look up, e.g. "example.com".
    """
    quota = await charge("whois_lookup", ctx)
    data = await post_json(
        "/api/tools/whois", {"domain": domain}, timeout=_WHOIS_TIMEOUT, extra_headers=upstream_headers()
    )
    lookup = data.get("lookup") or {}
    return {
        "domain": lookup.get("domain", domain),
        "whois": lookup.get("result"),
        "quota_used": quota["used"],
        "quota_cap": quota["cap"],
        "quota_remaining": quota["remaining"],
        "quota": quota,
    }


@mcp.tool(annotations=_READ_ONLY)
async def tld_registration_price(
    tld: str,
    operation: Literal["register", "transfer", "renew", "restore"] = "register",
    ctx: Context = None,
) -> dict:
    """Get the current USD price for a domain-lifecycle operation on a TLD
    (new registration, transfer-in, renewal, or restore from redemption).

    Backed by GET /api/pricing/tld. This is
    name.ai's own registration pricing, not an aftermarket/marketplace price,
    so it is never gated by sign-in status. Counts against the search quota.

    Args:
        tld: The TLD without a leading dot, e.g. "ai" or "com".
        operation: One of "register", "transfer", "renew", "restore".
    """
    quota = await charge("tld_registration_price", ctx)
    data = await get_json("/api/pricing/tld", {"tld": tld, "op": operation}, extra_headers=upstream_headers())
    price_cents = data.get("priceCents")
    return {
        "tld": data.get("tld", tld),
        "operation": data.get("op", operation),
        "price_usd": price_cents / 100 if isinstance(price_cents, (int, float)) else None,
        "quota": quota,
    }


@mcp.tool(annotations=_READ_ONLY)
async def tld_requirements(tld: str, ctx: Context = None) -> dict:
    """Get registration requirements for a TLD: allowed registration period
    range, whether an organization is required, allowed registrant
    countries, nameserver rules, and similar registry policy.

    Backed by GET /api/tlds/{tld}/metadata. Counts against the search quota.

    Args:
        tld: The TLD without a leading dot, e.g. "ai" or "io".
    """
    quota = await charge("tld_requirements", ctx)
    try:
        data = await get_json(f"/api/tlds/{tld}/metadata", extra_headers=upstream_headers())
    except NameAIAPIError as err:
        if err.status_code == 404:
            return {"tld": tld, "found": False, "message": str(err), "quota": quota}
        raise
    return {**data, "quota": quota} if isinstance(data, dict) else {"data": data, "quota": quota}


@mcp.resource(
    "nameai://docs/overview",
    name="overview",
    title="Name.ai MCP server overview",
    description="What this server does, its tools, and how to get more out of it.",
    mime_type="text/markdown",
)
def overview_resource() -> str:
    return (
        "# Name.ai MCP server\n\n"
        "Domain tools backed by name.ai:\n\n"
        "- `search_domain` — availability + alternate-TLD suggestions with registration pricing.\n"
        "- `whois_lookup` — WHOIS/RDAP record for a domain.\n"
        "- `tld_registration_price` — USD price to register/transfer/renew/restore on a TLD.\n"
        "- `tld_requirements` — registry policy for a TLD (periods, org/nameserver rules).\n\n"
        "All tools are read-only and need a name.ai sign-in (Login with X). Free:\n"
        "3 WHOIS + 4 searches per day (price/requirements count as searches). With\n"
        "a completed name.ai profile (https://name.ai/mcp/onboard): 20 WHOIS + 100\n"
        "searches per month. See nameai://docs/auth.\n\n"
        "REST equivalent: https://name.ai/openapi.json · Site overview: https://name.ai/llms.txt\n"
    )


@mcp.resource(
    "nameai://docs/auth",
    name="auth",
    title="Authenticating to Name.ai",
    description="OAuth 2.1 + PKCE flow for unlocking real marketplace prices on search_domain.",
    mime_type="text/markdown",
)
def auth_resource() -> str:
    return (
        "# Authenticating to Name.ai\n\n"
        "Required — every call needs a token. Most clients run this flow for you\n"
        "when the server answers 401 (the user signs in with X on name.ai).\n\n"
        "1. Register a client (RFC 7591, no secret): POST https://name.ai/api/oauth/register\n"
        "   with {\"redirect_uris\": [...], \"client_name\": \"...\"}.\n"
        "2. Send the user to https://name.ai/oauth/authorize?response_type=code&client_id=...\n"
        "   &redirect_uri=...&code_challenge=S256(verifier)&code_challenge_method=S256&state=...\n"
        "3. Exchange the returned code at POST https://name.ai/api/oauth/token\n"
        "   (grant_type=authorization_code + code_verifier). Access token lasts 30 min;\n"
        "   refresh token 30 days, rotating on use.\n"
        "4. Pass `Authorization: Bearer <access_token>` on tool calls.\n\n"
        "Full walkthrough: https://name.ai/auth.md\n"
    )


# ─── Protocol-level errors for invalid calls ─────────────────────────────────
# The SDK turns an unknown tool or a failed argument validation into a
# CallToolResult with is_error=True and a free-text message. The MCP spec
# classifies both as *protocol* errors (JSON-RPC -32602 Invalid params), and
# agents key off a structured code, so route them through MCPError instead.
# Genuine execution failures inside a tool keep the is_error result shape.
from pydantic import ValidationError  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402
from mcp.types import INVALID_PARAMS  # noqa: E402

_sdk_call_tool = mcp.call_tool


async def _call_tool_with_structured_errors(name, arguments, context=None):
    available = sorted(t.name for t in await mcp.list_tools())
    if name not in available:
        raise MCPError(
            INVALID_PARAMS,
            f"Unknown tool: {name}",
            data={"code": "unknown_tool", "tool": name, "available_tools": available},
        )
    try:
        return await _sdk_call_tool(name, arguments, context)
    except ToolError as exc:
        cause = exc.__cause__
        if isinstance(cause, ValidationError):
            fields = sorted({".".join(str(p) for p in e["loc"]) for e in cause.errors()})
            raise MCPError(
                INVALID_PARAMS,
                f"Invalid arguments for {name}: {', '.join(fields) or 'schema mismatch'}",
                data={"code": "invalid_arguments", "tool": name, "fields": fields},
            ) from exc
        raise


mcp.call_tool = _call_tool_with_structured_errors
