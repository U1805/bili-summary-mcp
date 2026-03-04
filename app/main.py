from fastapi import FastAPI

from app.core.router import router as core_router
from app.core.settings import get_settings
from app.mcp import get_mcp_http_app, register_mcp_lifecycle

app = FastAPI(title="bili-summary-mcp", version="0.1.0")
app.include_router(core_router)
app.mount("/mcp", get_mcp_http_app())
register_mcp_lifecycle(app)

settings = get_settings()
if settings.qwen.enabled:
    from app.qwen import register_qwen_lifecycle, router as qwen_router

    app.include_router(qwen_router)
    register_qwen_lifecycle(app)


def run() -> None:
    import uvicorn

    cfg = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=cfg.server.port)


if __name__ == "__main__":
    run()
