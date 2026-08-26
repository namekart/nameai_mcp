from __future__ import annotations

from typing import Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

from nameai_mcp.nameai_client import NameAIAPIError, get_json, post_json, post_ndjson_rows
from nameai_mcp.oauth_verifier import verify_bearer_token

# Deliberately NOT passing auth=AuthSettings(...) here. The lowlevel Server's
# streamable_http_app() would happily publish RFC 9728 discovery metadata
# from `auth` alone — but MCPServer.__init__ itself raises unless `auth` is
# paired with token_verifier or auth_server_provider, and setting
# token_verifier activates RequireAuthMiddleware on the entire /mcp route
# (confirmed by reading mcp/server/lowlevel/server.py), which would require a
# valid bearer token for the 3 public tools too. Not achievable through this
# SDK class without breaking that contract. OAuth discoverability instead
# comes from .well-known/mcp.json's custom "auth" field and AUTH.md.
mcp = MCPServer(
    name="nameai-mcp",
    version="1.0.0",
    instructions=(
        "Name.ai domain tools: check domain availability (search_domain), look up "
        "WHOIS records (whois_lookup), and get TLD registration pricing "
        "(tld_registration_price) and registry requirements (tld_requirements). "
        "All tools are read-only and work without authentication. Marketplace "
        "prices on search_domain are masked for anonymous callers - pass an OAuth "
        "Bearer token (see https://name.ai/auth.md) to see them. whois_lookup is "
        "rate limited to 10/day per caller IP; cache TLD pricing/requirements, "
        "they change rarely."
    ),
)

# Every tool is a read-only lookup against name.ai / public registries -
# annotate so agents know calls are safe to make and repeat.
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

# RDAP can retry against multiple registries before falling back to DomainIQ
# (see app/api/tools/whois/route.js) — needs more headroom than other calls.
_WHOIS_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)


@mcp.tool(annotations=_READ_ONLY)
async def search_domain(domain: str, include_alternates: bool = True, ctx: Context = None) -> dict:
    """Check whether a domain is available and, for the same label, whether its
    common alternate TLDs are too (e.g. querying "acme.com" also returns
    "acme.ai", "acme.io", ...).

    Backed by POST /api/domain/search — public, no auth required.

    Buy-now (aftermarket/marketplace) prices are hidden unless you're
    authenticated (see AUTH.md at name.ai for how to get a token) — an
    unauthenticated call only sees new-registration pricing for a domain
    that's simply unregistered. Pass a valid OAuth access token as this
    call's Authorization header and it's forwarded automatically.

    Args:
        domain: A domain name to check, e.g. "example.ai".
        include_alternates: When true (default), also return sibling TLDs for
            the same label. When false, only the exact domain is returned.
    """
    extra_headers = None
    auth_header = (ctx.headers or {}).get("authorization") if ctx else None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[len("bearer ") :].strip()
        if await verify_bearer_token(token):
            extra_headers = {"authorization": auth_header}

    rows = await post_ndjson_rows("/api/domain/search", {"q": domain}, extra_headers=extra_headers)
    if not include_alternates and rows:
        primary = rows[0]["domain"]
        rows = [r for r in rows if r["domain"] == primary]
    return {"query": domain, "results": rows}


@mcp.tool(annotations=_READ_ONLY)
async def whois_lookup(domain: str) -> dict:
    """Look up WHOIS/RDAP registration details for a domain: registrar,
    registrant, creation/expiration dates, nameservers.

    Backed by POST /api/tools/whois — public, no auth required, but rate
    limited by name.ai to 10 lookups per day per caller IP. Since every MCP
    call shares this server's egress IP, that quota is pooled across all of
    this MCP server's callers, not per end user.

    Args:
        domain: A domain name to look up, e.g. "example.com".
    """
    data = await post_json("/api/tools/whois", {"domain": domain}, timeout=_WHOIS_TIMEOUT)
    lookup = data.get("lookup") or {}
    return {
        "domain": lookup.get("domain", domain),
        "whois": lookup.get("result"),
        "quota_used": data.get("used"),
        "quota_cap": data.get("cap"),
        "quota_remaining": data.get("remaining"),
    }


@mcp.tool(annotations=_READ_ONLY)
async def tld_registration_price(
    tld: str,
    operation: Literal["register", "transfer", "renew", "restore"] = "register",
) -> dict:
    """Get the current USD price for a domain-lifecycle operation on a TLD
    (new registration, transfer-in, renewal, or restore from redemption).

    Backed by GET /api/pricing/tld — public, no auth required. This is
    name.ai's own registration pricing, not an aftermarket/marketplace price,
    so it is never gated by sign-in status.

    Args:
        tld: The TLD without a leading dot, e.g. "ai" or "com".
        operation: One of "register", "transfer", "renew", "restore".
    """
    data = await get_json("/api/pricing/tld", {"tld": tld, "op": operation})
    price_cents = data.get("priceCents")
    return {
        "tld": data.get("tld", tld),
        "operation": data.get("op", operation),
        "price_usd": price_cents / 100 if isinstance(price_cents, (int, float)) else None,
    }


@mcp.tool(annotations=_READ_ONLY)
async def tld_requirements(tld: str) -> dict:
    """Get registration requirements for a TLD: allowed registration period
    range, whether an organization is required, allowed registrant
    countries, nameserver rules, and similar registry policy.

    Backed by GET /api/tlds/{tld}/metadata — public, no auth required.

    Args:
        tld: The TLD without a leading dot, e.g. "ai" or "io".
    """
    try:
        return await get_json(f"/api/tlds/{tld}/metadata")
    except NameAIAPIError as err:
        if err.status_code == 404:
            return {"tld": tld, "found": False, "message": str(err)}
        raise


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
        "- `whois_lookup` — WHOIS/RDAP record for a domain (10/day per IP).\n"
        "- `tld_registration_price` — USD price to register/transfer/renew/restore on a TLD.\n"
        "- `tld_requirements` — registry policy for a TLD (periods, org/nameserver rules).\n\n"
        "All tools are read-only and free, no authentication required. Marketplace\n"
        "prices on `search_domain` are masked for anonymous callers — authenticate per\n"
        "nameai://docs/auth (or https://name.ai/auth.md) to see them.\n\n"
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
        "Optional — every tool works anonymously. A token only unmasks marketplace\n"
        "prices on `search_domain`.\n\n"
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
