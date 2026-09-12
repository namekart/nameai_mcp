import json
import os

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
        "resource_documentation": f"{_NAMEAI_API_BASE_URL}/auth.md",
    }


# The MCP manifest, mirrored onto this origin.
#
# name.ai serves the canonical copy at both these paths, and the server card
# next to them was already mirrored here for a reason that applies just as
# much to the manifest: a client handed the MCP URL — rather than the brand
# domain — looks for the manifest on the origin it was given. Ours answered
# 404 there, so anything checking "is there a standard manifest endpoint for
# this server" concluded there wasn't one, while name.ai's own copies read
# fine. Two paths because the extensionless form is what the discovery
# convention names and the .json form is what most clients try first.
_MCP_DESCRIPTION = (
    "Domain search/availability, WHOIS lookup, TLD registration pricing, and TLD "
    "registration requirements for name.ai. All tools work without authentication; "
    "signing in via OAuth (see auth section below) additionally unlocks real marketplace "
    "prices on domain searches."
)


def _mcp_manifest() -> dict:
    """Kept byte-compatible with name.ai/.well-known/mcp.json — same keys, same
    order, same values. Two copies of one document is already one too many; a
    third shape would be worse."""
    endpoint = f"{_MCP_PUBLIC_URL}/mcp"
    return {
        "mcpUrl": endpoint,
        "servers": [
            {
                "name": "name.ai",
                "url": endpoint,
                "transport": "streamable-http",
                "description": _MCP_DESCRIPTION,
            }
        ],
        "mcpServers": {
            "name-ai": {"type": "http", "url": endpoint, "description": _MCP_DESCRIPTION}
        },
        "openapi": f"{_NAMEAI_API_BASE_URL}/openapi.json",
        "auth": {
            "type": "oauth2.1",
            "authorization_server_metadata": (
                f"{_NAMEAI_API_BASE_URL}/.well-known/oauth-authorization-server"
            ),
            "docs": f"{_NAMEAI_API_BASE_URL}/AUTH.md",
            "optional": True,
        },
    }


@app.get("/.well-known/mcp")
def mcp_manifest() -> dict:
    return _mcp_manifest()


@app.get("/.well-known/mcp.json")
def mcp_manifest_json() -> dict:
    return _mcp_manifest()


# Server card on the MCP host itself. name.ai serves the canonical copy at
# the same path; scanners that take the MCP URL as their subject (rather than
# the brand domain) look for it on this origin, so it's mirrored here.
@app.get("/.well-known/mcp/server-card.json")
async def mcp_server_card() -> dict:
    # tools[] is built from the live registry so the card can never drift
    # from what tools/list returns.
    tools = [
        {
            "name": t.name,
            "description": (t.description or "").strip().split("\n\n")[0],
            "inputSchema": t.input_schema,
            **({"annotations": t.annotations.model_dump(exclude_none=True)} if t.annotations else {}),
        }
        for t in await mcp.list_tools()
    ]
    return {
        "name": "name-ai",
        "displayName": "Name.ai MCP Server",
        "description": (
            "Domain search/availability, WHOIS lookup, TLD registration pricing, and TLD "
            "registration requirements as MCP tools. All tools work without authentication; "
            f"OAuth sign-in (see {_NAMEAI_API_BASE_URL}/auth.md) additionally unlocks real "
            "marketplace prices on domain searches."
        ),
        "version": "1.0.0",
        "serverUrl": f"{_MCP_PUBLIC_URL}/mcp",
        "url": f"{_MCP_PUBLIC_URL}/mcp",
        "transport": "streamable-http",
        "protocolVersion": "2025-06-18",
        "icon": f"{_NAMEAI_API_BASE_URL}/logo.png",
        "iconUrl": f"{_NAMEAI_API_BASE_URL}/logo.png",
        "publisher": {"name": "Name.ai", "url": _NAMEAI_API_BASE_URL},
        "homepage": f"{_NAMEAI_API_BASE_URL}/developers",
        "repository": "https://github.com/namekart/nameai_mcp",
        "registry": {"name": "ai.name/nameai-mcp", "url": "https://registry.modelcontextprotocol.io/v0/servers?search=ai.name/nameai-mcp"},
        "auth": {
            "type": "oauth2.1",
            "optional": True,
            "authorization_server_metadata": f"{_NAMEAI_API_BASE_URL}/.well-known/oauth-authorization-server",
            "protected_resource_metadata": f"{_MCP_PUBLIC_URL}/.well-known/oauth-protected-resource",
            "docs": f"{_NAMEAI_API_BASE_URL}/auth.md",
        },
        "tools": tools,
    }


class AcceptJsonOnlyMiddleware:
    """Let a client that only speaks JSON talk to the Streamable HTTP endpoint.

    The transport spec says a POST to /mcp must accept BOTH application/json
    and text/event-stream, and the SDK enforces it with a 406. Strictly that is
    correct. In practice a great many clients — scanners, curl one-liners, any
    HTTP library whose default is `Accept: application/json` — send only the
    one, and a 406 on the very first handshake is indistinguishable from "this
    server does not exist". We were failing exactly that way: every check that
    needed a live session reported no MCP server at all, while the manifests
    pointing at it read fine.

    So a JSON-only client gets served rather than refused. Inbound, the Accept
    header is widened so the SDK proceeds. Outbound, if the reply came back as
    a single SSE frame, it is unwrapped to the JSON body inside it, because a
    client that asked for JSON cannot parse `event:`/`data:` framing.

    Clients that do send both headers are untouched: they keep the streaming
    behaviour, and anything genuinely multi-frame is passed through as SSE
    rather than mangled into a JSON body it does not fit.
    """

    _SSE = "text/event-stream"
    _JSON = "application/json"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        accept = headers.get("accept", "")
        json_only = self._JSON in accept and self._SSE not in accept
        if not json_only:
            await self.app(scope, receive, send)
            return

        # Widen Accept so the SDK's own check passes.
        patched = MutableHeaders(scope=scope)
        patched["accept"] = f"{self._JSON}, {self._SSE}"

        start: Message | None = None
        body = bytearray()

        async def capture(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if message.get("more_body"):
                    return
                await self._finish(start, bytes(body), send)

        await self.app(scope, receive, capture)

    async def _finish(self, start: Message | None, body: bytes, send: Send) -> None:
        if start is None:
            return
        content_type = Headers(raw=start["headers"]).get("content-type", "")
        payload = self._unwrap_sse(body) if self._SSE in content_type else None
        if payload is None:
            # Not a single-frame SSE reply — pass it through untouched.
            await send(start)
            await send({"type": "http.response.body", "body": body})
            return
        response = Response(
            content=payload,
            status_code=start["status"],
            media_type=self._JSON,
        )
        # Session id and the rest of the transport's headers must survive.
        for key, value in Headers(raw=start["headers"]).items():
            if key.lower() not in {"content-type", "content-length"}:
                response.headers[key] = value
        await response(  # type: ignore[call-arg]
            {"type": "http"},
            self._empty_receive,
            send,
        )

    @staticmethod
    def _unwrap_sse(body: bytes) -> bytes | None:
        """The JSON inside a single-frame SSE reply, or None if it isn't one."""
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if len(data) != 1:
            return None
        try:
            json.loads(data[0])
        except ValueError:
            return None
        return data[0].encode("utf-8")

    @staticmethod
    async def _empty_receive() -> Message:
        return {"type": "http.disconnect"}


# streamable_http_app() registers its own endpoint internally at "/mcp", so
# mounting it here at root gives a clean external path (GET /health, POST/GET
# /mcp) instead of a doubled-up "/mcp-server/mcp". /health above is registered
# first and matches exactly, so it isn't swallowed by this catch-all mount.
app.mount("/", AcceptJsonOnlyMiddleware(mcp_app))
