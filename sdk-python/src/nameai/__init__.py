"""Official Name.ai SDK — a thin, dependency-free client for the public API.

Docs: https://name.ai/developers/api · Spec: https://name.ai/openapi.json

Every read works without an account. Authentication is optional
(https://name.ai/auth.md) and buys exactly one thing: real marketplace prices
instead of masked ones. Pass ``access_token`` to get them.

    from nameai import NameAI

    nameai = NameAI()
    print(nameai.tld_price("ai", "register"))
    for listing in nameai.list_all_listings(tld="ai"):
        ...
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, List, Optional, Sequence

__all__ = ["NameAI", "NameAIError", "__version__"]

__version__ = "1.1.1"

DEFAULT_BASE_URL = "https://name.ai"
_USER_AGENT = f"nameai-python/{__version__} (+https://name.ai/developers)"


class NameAIError(RuntimeError):
    """A non-2xx response from the Name.ai API.

    Carries the typed error the API returns (see ``components.schemas.Error``
    in the spec) so a caller can branch on ``code`` rather than parse a string.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


class NameAI:
    """Client for the Name.ai public REST API.

    :param base_url: override for testing or a staging host.
    :param access_token: OAuth 2.1 bearer token; optional, unlocks marketplace
        prices. See https://name.ai/auth.md.
    :param timeout: per-request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        access_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout

    # ── transport ──────────────────────────────────────────────────────────

    def _headers(self, **extra: str) -> Dict[str, str]:
        headers = {"accept": "application/json", "user-agent": _USER_AGENT}
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        headers.update(extra)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        url = f"{self.base_url}{path}"
        if params:
            clean = {k: str(v) for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"

        headers = self._headers(**(extra_headers or {}))
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["content-type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # non-2xx
            raw = exc.read().decode("utf-8", errors="replace")
            message, code = f"Name.ai API returned HTTP {exc.code}", None
            try:
                detail = json.loads(raw).get("error") or {}
                message = detail.get("message") or message
                code = detail.get("code")
            except (ValueError, AttributeError):
                pass  # error body was not the typed shape
            retry_after = exc.headers.get("retry-after") if exc.headers else None
            raise NameAIError(
                message,
                status=exc.code,
                code=code,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            ) from None

    def _json(self, *args: Any, **kwargs: Any) -> Any:
        return json.loads(self._request(*args, **kwargs))

    # ── endpoints ──────────────────────────────────────────────────────────

    def search_domain(self, domain: str) -> Dict[str, Any]:
        """Check a domain's availability plus its alternate-TLD siblings.

        The endpoint streams NDJSON so a browser can fill results in as they
        land; there is nothing to stream into here, so the rows are collected.

        :returns: ``{"query": str, "results": [row, ...]}``
        """
        text = self._request("POST", "/api/domain/search", body={"q": domain})
        results: List[Dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") == "row":
                event.pop("kind", None)
                results.append(event)
        return {"query": domain, "results": results}

    def whois_lookup(self, domain: str, *, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """WHOIS/RDAP details: registrar, registrant, dates, nameservers.

        :param idempotency_key: makes a retry replay-safe.
        """
        extra = {"idempotency-key": idempotency_key} if idempotency_key else None
        return self._json("POST", "/api/tools/whois", body={"domain": domain}, extra_headers=extra)

    def tld_price(self, tld: str, operation: str = "register") -> Dict[str, Any]:
        """Price for ``register``, ``renew``, ``transfer`` or ``restore`` on a TLD."""
        return self._json(
            "GET", "/api/pricing/tld", params={"tld": tld.lstrip("."), "op": operation}
        )

    def tld_requirements(self, tld: str) -> Dict[str, Any]:
        """Registry requirements: term range, organization and nameserver rules."""
        return self._json("GET", f"/api/tlds/{urllib.parse.quote(tld.lstrip('.'))}/metadata")

    def market_listings(
        self,
        *,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        cursor: Optional[str] = None,
        q: Optional[str] = None,
        tld: Optional[str] = None,
        max: Optional[float] = None,  # noqa: A002 — matches the query parameter
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """One page of marketplace listings.

        Prefer ``cursor`` (from a previous ``page["next_cursor"]``) over
        incrementing ``offset``: a cursor names the row you stopped at, so a
        listing sold or added mid-walk cannot shift the window under you.
        :meth:`list_all_listings` does that for you.
        """
        return self._json(
            "GET",
            "/api/market/listings",
            params={
                "limit": limit,
                "offset": offset,
                "cursor": cursor,
                "q": q,
                "tld": tld,
                "max": max,
                "sort": sort,
            },
        )

    def list_all_listings(self, **params: Any) -> Iterator[Dict[str, Any]]:
        """Every matching listing, walked by cursor, one page held at a time."""
        params.pop("offset", None)
        params.pop("cursor", None)
        cursor: Optional[str] = None
        while True:
            page = self.market_listings(cursor=cursor, **params)
            for item in page.get("items") or []:
                yield item
            cursor = (page.get("page") or {}).get("next_cursor")
            if not cursor:
                return

    def batch(self, operations: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Several public reads in one request — prefer this over a loop.

        One round trip instead of N, and each operation costs the rate limit
        exactly what the individual call would have.

        :param operations: up to 20 of ``{"id": ..., "op": ..., "params": {...}}``
            where ``op`` is ``search_domain``, ``whois_lookup``,
            ``tld_registration_price`` or ``tld_requirements``.
        :returns: ``{"results": [...], "count": int, "failed": int}`` — one
            result per operation, in order, each with its own ``status``. One
            failure does not fail the batch.
        """
        return self._json("POST", "/api/batch", body={"operations": list(operations)})
