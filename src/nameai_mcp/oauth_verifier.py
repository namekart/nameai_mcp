"""Verifies OAuth bearer tokens against name.ai's introspection endpoint.

This is deliberately NOT wired into MCPServer(token_verifier=...) — that SDK
hook wraps the entire /mcp endpoint in RequireAuthMiddleware, making every
tool call require a token, which would break the 3 public tools. Instead,
search_domain calls verify_bearer_token() manually and forwards the token to
name.ai only when it's actually valid — auth stays optional and additive.
See AUTH.md on name.ai for the full flow this token came from.
"""

from __future__ import annotations

import os

import httpx

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
