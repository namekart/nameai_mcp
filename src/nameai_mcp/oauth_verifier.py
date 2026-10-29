"""Verifies OAuth bearer tokens against name.ai's introspection endpoint.

Wired into MCPServer(token_verifier=NameAITokenVerifier()), so the SDK wraps
/mcp in RequireAuthMiddleware: every call needs a name.ai token (Login with X
on name.ai). A missing/invalid token gets 401 + WWW-Authenticate
resource_metadata, which is what makes Grok/Cursor/Claude show their
Authorize card. See AUTH.md on name.ai for the flow the token comes from.
"""

from __future__ import annotations

import hashlib
import os
import time

import httpx
from mcp.server.auth.provider import AccessToken

INTROSPECTION_URL = os.environ.get(
    "NAMEAI_OAUTH_INTROSPECTION_URL",
    f"{os.environ.get('NAMEAI_API_BASE_URL', 'https://name.ai').rstrip('/')}/api/oauth/introspect",
)
_INTROSPECTION_SECRET = os.environ.get("OAUTH_INTROSPECTION_SECRET", "")
_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


async def verify_bearer_token(token: str) -> dict | None:
    """Check a bearer token with name.ai. Returns the introspection payload
    ({active: true, sub, scope, ...}) when valid, or None for anything
    invalid/expired/misconfigured — never raises, since an unverifiable
    token should just fall back to anonymous behavior, not break the call.
    """
    if not token or not _INTROSPECTION_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                INTROSPECTION_URL,
                headers={"authorization": f"Bearer {_INTROSPECTION_SECRET}"},
                data={"token": token},
            )
        if resp.is_error:
            return None
        data = resp.json()
        return data if data.get("active") else None
    except (httpx.HTTPError, ValueError):
        return None


# Every JSON-RPC POST (initialize, tools/list, each tools/call) is verified, so
# cache good answers briefly. Short TTL: a revoked token stops working within
# a minute; tokens expire after 30 min anyway.
_CACHE_TTL_SEC = 60
_cache: dict[str, tuple[float, AccessToken]] = {}


class NameAITokenVerifier:
    """SDK TokenVerifier backed by name.ai's /api/oauth/introspect."""

    async def verify_token(self, token: str) -> AccessToken | None:
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = _cache.get(key)
        now = time.time()
        if hit and hit[0] > now:
            return hit[1]
        data = await verify_bearer_token(token)
        if not data:
            _cache.pop(key, None)
            return None
        access = AccessToken(
            token=token,
            client_id=str(data.get("client_id") or ""),
            scopes=str(data.get("scope") or "").split(),
            expires_at=data.get("exp"),
            subject=data.get("sub"),
        )
        expiry = min(now + _CACHE_TTL_SEC, float(data.get("exp") or now + _CACHE_TTL_SEC))
        if len(_cache) > 10_000:
            _cache.clear()
        _cache[key] = (expiry, access)
        return access
