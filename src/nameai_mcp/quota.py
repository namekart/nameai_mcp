"""Per-caller usage quotas, metered by name.ai.

Every tool calls charge() before doing any work. name.ai decides the tier and
atomically takes one unit (see mcp_usage/ in the main app,
raunak_dev_docs/mcp_usage/01-mcp_usage-design.md):

- signed in (OAuth token from Login with X on name.ai), no phone yet:
  3 whois + 4 search-bucket calls per UTC day;
- profile completed at name.ai/mcp/onboard (full name + phone, billing optional):
  20 whois + 100 search-bucket calls per calendar month (UTC).

RequireAuthMiddleware has already rejected calls without a valid token.

The user's bearer token is passed through to name.ai, which verifies it itself.
Fails closed: if the meter can't be reached, the tool doesn't run.
"""

from __future__ import annotations

import os

import httpx
from mcp.server.mcpserver.exceptions import ToolError

_API_BASE_URL = os.environ.get("NAMEAI_API_BASE_URL", "https://name.ai").rstrip("/")
_CONSUME_URL = f"{_API_BASE_URL}/api/internal/mcp-usage/consume"
_SECRET = os.environ.get("OAUTH_INTROSPECTION_SECRET", "")
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

_QUOTA_FIELDS = ("tier", "bucket", "used", "cap", "remaining", "resets_at")


def _headers(ctx) -> dict:
    return (ctx.headers or {}) if ctx else {}


def bearer_token(ctx) -> str | None:
    auth = _headers(ctx).get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[len("bearer ") :].strip() or None
    return None


def upstream_headers() -> dict[str, str] | None:
    """Marks calls to name.ai as coming from this server, so name.ai's per-IP
    caps (one pool for every MCP caller) are skipped — the quota above already
    gated the call."""
    return {"x-nameai-mcp-key": _SECRET} if _SECRET else None


async def charge(tool: str, ctx) -> dict:
    """Take one unit of `tool`'s bucket for this caller. Returns the quota
    snapshot to attach to the result; raises ToolError when the caller is out
    of quota (message tells them how to get more) or metering is down."""
    payload = {"tool": tool, "token": bearer_token(ctx)}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_CONSUME_URL, headers={"authorization": f"Bearer {_SECRET}"}, json=payload)
        resp.raise_for_status()
        decision = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolError("name.ai usage metering is temporarily unavailable — please try again shortly.") from exc

    if not decision.get("allowed"):
        message = decision.get("message") or "Usage limit reached."
        if decision.get("upgrade"):
            message += f" More: {decision['upgrade']}"
        raise ToolError(message)
    return {k: decision.get(k) for k in _QUOTA_FIELDS}
