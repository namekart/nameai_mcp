def main() -> None:
    import os

    import uvicorn

    # Local dev: `uv run uvicorn nameai_mcp.app:app --reload` gives you autoreload.
    # This entry point is what deploys actually run, so it stays reload-off and
    # binds 0.0.0.0 — HOST/PORT are overridable for whatever the host platform
    # injects (Coolify, Render, etc. commonly set PORT).
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("nameai_mcp.app:app", host=host, port=port)
