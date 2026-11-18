"""In-process rate limit and response cache for search_premium_domains.

name.ai gives this whole server one bucket (600 listings calls/min). Without
a limit here, one anonymous caller could use it up for every Claude user.

Per-session cap only applies to clients that send `mcp-session-id`. Clients on
the stateless protocol (Claude Code, checked 2026-11-18: headers carry
`mcp-method`, no session) get the global cap only. Per-IP is no substitute:
claude.ai calls all come from Anthropic's IPs.

shortcut: in-memory, so limits and cache are per container and reset on
deploy. Fine for one Coolify container; move to Redis if it ever scales out.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

PER_SESSION_PER_MIN = 30
GLOBAL_PER_MIN = 300  # half of name.ai's 600/min MCP bucket
CACHE_TTL_SEC = 300
CACHE_MAX = 512

_windows: dict[str, tuple[int, int]] = {}  # key -> (window start minute, count)
_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def _hit(key: str, limit: int, now: float) -> bool:
    minute = int(now // 60)
    start, count = _windows.get(key, (minute, 0))
    if start != minute:
        start, count = minute, 0
    if count >= limit:
        return False
    _windows[key] = (start, count + 1)
    return True


def allow(session_id: str | None, now: float | None = None) -> bool:
    """True if this call may go to name.ai. Checks the session, then the global cap."""
    now = time.time() if now is None else now
    if len(_windows) > 10_000:  # drop stale session windows
        minute = int(now // 60)
        for k in [k for k, (m, _) in _windows.items() if m != minute]:
            del _windows[k]
    if session_id and not _hit(f"s:{session_id}", PER_SESSION_PER_MIN, now):
        return False
    return _hit("global", GLOBAL_PER_MIN, now)


def cache_get(key: str, now: float | None = None) -> Any | None:
    now = time.time() if now is None else now
    entry = _cache.get(key)
    if not entry or now - entry[0] > CACHE_TTL_SEC:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return entry[1]


def cache_put(key: str, value: Any, now: float | None = None) -> None:
    _cache[key] = (time.time() if now is None else now, value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)


def reset() -> None:
    """Tests only."""
    _windows.clear()
    _cache.clear()
