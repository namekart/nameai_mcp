from fastapi import FastAPI

from nameai_mcp.server import mcp

mcp_app = mcp.streamable_http_app()

app = FastAPI(lifespan=mcp_app.router.lifespan_context)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# streamable_http_app() registers its own endpoint internally at "/mcp", so
# mounting it here at root gives a clean external path (GET /health, POST/GET
# /mcp) instead of a doubled-up "/mcp-server/mcp". /health above is registered
# first and matches exactly, so it isn't swallowed by this catch-all mount.
app.mount("/", mcp_app)
