from __future__ import annotations

import json
from typing import Literal, TypedDict

import httpx
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from nameai_mcp.nameai_client import API_BASE_URL, NameAIAPIError, get_json, mcp_key_headers, post_json, post_ndjson_rows
from nameai_mcp.oauth_verifier import verify_bearer_token
from nameai_mcp import limits
from nameai_mcp.market_app_html import MARKET_APP_HTML, MARKET_APP_URI
from nameai_mcp.search_app_html import SEARCH_APP_HTML, SEARCH_APP_URI

# Deliberately NOT passing auth=AuthSettings(...) here. The lowlevel Server's
# streamable_http_app() would happily publish RFC 9728 discovery metadata
# from `auth` alone — but MCPServer.__init__ itself raises unless `auth` is
# paired with token_verifier or auth_server_provider, and setting
# token_verifier activates RequireAuthMiddleware on the entire /mcp route
# (confirmed by reading mcp/server/lowlevel/server.py), which would require a
# valid bearer token for the 3 public tools too. Not achievable through this
# SDK class without breaking that contract. OAuth discoverability instead
# comes from .well-known/mcp.json's custom "auth" field and AUTH.md.
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

    Backed by POST /api/domain/search — public, no auth required.

    Buy-now (aftermarket/marketplace) prices are hidden unless you're
    authenticated (see AUTH.md at name.ai for how to get a token) — an
    unauthenticated call only sees new-registration pricing for a domain
    that's simply unregistered. To get the buy-now price of a name that is
    for sale without signing in, use search_marketplace with that name as
    keyword and tld="". Pass a valid OAuth access token as this
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


_MARKET_MAX = 25
_SITE = API_BASE_URL  # listing links follow the API host, so stage links stay on stage


class MarketListing(TypedDict):
    domain: str
    price_usd: float | None
    url: str


class MarketResults(TypedDict):
    query: dict[str, str | int]
    results: list[MarketListing]
    total: int | None
    has_more: bool
    browse_url: str


def _listing_row(item: dict) -> MarketListing:
    domain = str(item.get("domain") or "")
    price = (item.get("price") or {}).get("bin")
    return {
        # Seller's casing ("QuietHarbor.ai") for display; the URL uses the lowercase name.
        "domain": item.get("display_name") or domain,
        "price_usd": price if isinstance(price, (int, float)) else None,
        "url": f"{_SITE}/{domain}?utm_source=mcp&utm_medium=connector",
    }


apps.add_html_resource(
    MARKET_APP_URI,
    MARKET_APP_HTML,
    name="market-results",
    title="Premium domains for sale",
    description="Renders search_marketplace results as a price list linking to name.ai listings.",
    # The view makes no network calls; links open through the host.
    csp=ResourceCsp(connect_domains=[], resource_domains=["https://name.ai"], frame_domains=[]),
    prefers_border=True,
)


@apps.tool(resource_uri=MARKET_APP_URI, annotations=_READ_ONLY)
async def search_marketplace(
    keyword: str = "",
    tld: str = "ai",
    min_price: int | None = None,
    max_price: int | None = None,
    sort: Literal["newest", "price_asc", "price_desc"] = "newest",
    limit: int = 10,
    ctx: Context = None,
) -> MarketResults:
    """Find premium domain names currently for sale on name.ai, with buy-now
    prices (USD) and a link to each listing, where the purchase happens.

    Use when the user wants a name for a startup, product or brand, or wants
    to browse domains to buy, optionally within a budget.

    `keyword` matches text inside the domain name, so pass ONE short word
    ("legal", "pay", "health"), not a sentence. For a business idea, call
    this several times with different related words, or leave keyword empty
    to browse the newest premium names. To check whether one specific domain
    is free to register, use search_domain instead.

    Backed by GET /api/market/listings (public). Read-only: nothing is bought.

    Args:
        keyword: One short word the domain name should contain. Empty = browse.
        tld: TLD without the dot, e.g. "ai" (default) or "com". Empty = any.
        min_price: Lowest buy-now price in USD.
        max_price: Highest buy-now price in USD.
        sort: "newest" (default), "price_asc" or "price_desc".
        limit: Number of results, 1 to 25 (default 10).
    """
    params: dict[str, str | int] = {"limit": max(1, min(_MARKET_MAX, limit))}
    if keyword.strip():
        params["q"] = keyword.strip().lower()
    if tld.strip().lstrip("."):
        params["tld"] = tld.strip().lstrip(".").lower()
    if min_price is not None:
        params["min"] = max(0, min_price)
    if max_price is not None:
        params["max"] = max(0, max_price)
    if sort != "newest":
        params["sort"] = sort

    cache_key = json.dumps(params, sort_keys=True)
    data = limits.cache_get(cache_key)
    if data is None:
        session_id = (ctx.headers or {}).get("mcp-session-id") if ctx else None
        if not limits.allow(session_id):
            raise ToolError("Too many marketplace searches right now. Try again in a minute.")
        try:
            data = await get_json("/api/market/listings", params, extra_headers=mcp_key_headers())
        except NameAIAPIError as err:
            if err.status_code == 429:
                raise ToolError("name.ai marketplace search is busy. Try again in a minute.") from err
            raise ToolError(f"name.ai marketplace search failed: {err}") from err
        limits.cache_put(cache_key, data)
    page = data.get("page") or {}
    results = [_listing_row(i) for i in data.get("items") or [] if i and i.get("domain")]
    return {
        "query": {k: v for k, v in params.items() if k != "limit"},
        "results": results,
        "total": page.get("total"),
        "has_more": bool(page.get("has_more")),
        "browse_url": f"{_SITE}/market",
    }


mcp = MCPServer(
    name="nameai-mcp",
    version="1.0.0",
    instructions=(
        "Name.ai domain tools: find premium domains for sale with prices "
        "(search_marketplace), check domain availability (search_domain), look up "
        "WHOIS records (whois_lookup), and get TLD registration pricing "
        "(tld_registration_price) and registry requirements (tld_requirements). "
        "All tools are read-only and work without authentication. search_marketplace "
        "returns buy-now prices without sign-in; for the price of one for-sale name, "
        "call it with that name as keyword and tld=\"\". Marketplace prices on "
        "search_domain are masked for anonymous callers - pass an OAuth Bearer token "
        "(see https://name.ai/auth.md) to see them there. whois_lookup is "
        "rate limited to 10/day per caller IP; cache TLD pricing/requirements, "
        "they change rarely."
    ),
    extensions=[apps],
)

# RDAP can retry against multiple registries before falling back to DomainIQ
# (see app/api/tools/whois/route.js) — needs more headroom than other calls.
_WHOIS_TIMEOUT = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)




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
        "- `search_marketplace` — premium domains for sale on name.ai, with buy-now prices and links.\n"
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
