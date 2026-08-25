"""Thin async client for the public, no-auth-required name.ai JSON API.

Every endpoint called here is reachable without a session cookie today (see
route source for each — linked in docstrings on the call sites in server.py).
Two of them apply name.ai's price-visibility policy server-side: an
unauthenticated caller (which every MCP request is, since we never forward a
session) gets aftermarket/marketplace prices masked to null and only sees
new-registration TLD pricing. That's intentional upstream behavior, not a bug
here — see lib/server/price-visibility.js in the main app.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

API_BASE_URL = os.environ.get("NAMEAI_API_BASE_URL", "https://name.ai").rstrip("/")
_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)
_HEADERS = {"user-agent": "nameai-mcp/0.1 (+https://name.ai)"}


class NameAIAPIError(RuntimeError):
    """Raised when the name.ai API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _error_message(status_code: int, body: bytes) -> str:
    try:
        parsed = json.loads(body)
    except ValueError:
        return f"name.ai API returned HTTP {status_code}"
    err = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(err, dict):
        return err.get("message") or f"name.ai API returned HTTP {status_code}"
    if isinstance(err, str) and err:
        return err
    return f"name.ai API returned HTTP {status_code}"


async def get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=_TIMEOUT, headers=_HEADERS) as client:
        resp = await client.get(path, params=params)
    if resp.is_error:
        raise NameAIAPIError(resp.status_code, _error_message(resp.status_code, resp.content))
    return resp.json()


async def post_json(path: str, json_body: dict[str, Any], timeout: httpx.Timeout | None = None) -> Any:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=timeout or _TIMEOUT, headers=_HEADERS) as client:
        resp = await client.post(path, json=json_body)
    if resp.is_error:
        raise NameAIAPIError(resp.status_code, _error_message(resp.status_code, resp.content))
    return resp.json()


async def post_ndjson_rows(path: str, json_body: dict[str, Any]) -> list[dict[str, Any]]:
    """POST to an NDJSON-streaming endpoint and collect every `row` event."""
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=_TIMEOUT, headers=_HEADERS) as client:
        async with client.stream("POST", path, json=json_body) as resp:
            if resp.is_error:
                body = await resp.aread()
                raise NameAIAPIError(resp.status_code, _error_message(resp.status_code, body))
            async for line in resp.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("kind") == "row":
                    event = dict(event)
                    event.pop("kind", None)
                    rows.append(event)
    return rows
