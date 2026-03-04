import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp

from app.core.utils import is_bilibili_url
from app.services.summary import summarize_video
from app.services.video import download_video

mcp_server = FastMCP(
    name="bili-summary-mcp",
    instructions="Summarize Bilibili videos with the existing project workflow.",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)
_mcp_http_app = mcp_server.streamable_http_app()
_mcp_session_manager = mcp_server.session_manager


def _format_http_exception(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, (dict, list)):
        detail_text = json.dumps(detail, ensure_ascii=False)
    else:
        detail_text = str(detail)
    return f"HTTP {exc.status_code}: {detail_text}"


@mcp_server.tool(name="health", description="Return service health status.")
def health() -> dict[str, str]:
    return {"status": "ok"}


@mcp_server.tool(
    name="summarize_video",
    description="Download a Bilibili video and summarize it with the configured model.",
)
async def summarize_video_tool(url: str, prompt: str | None = None) -> dict[str, Any]:
    normalized_url = url.strip()
    if not is_bilibili_url(normalized_url):
        raise ValueError("Only Bilibili URLs are supported")

    try:
        filepath, title, duration = await run_in_threadpool(download_video, normalized_url)
        summary = await run_in_threadpool(summarize_video, filepath, prompt)
    except HTTPException as exc:
        raise RuntimeError(_format_http_exception(exc)) from exc

    return {
        "summary": summary,
        "title": title,
        "duration": duration,
        "filepath": filepath,
        "prompt": prompt,
    }


def get_mcp_http_app() -> ASGIApp:
    return _mcp_http_app


def register_mcp_lifecycle(app: FastAPI) -> None:
    if getattr(app.state, "_mcp_lifespan_registered", False):
        return

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _mcp_lifespan(app_instance: FastAPI):
        async with _mcp_session_manager.run():
            async with previous_lifespan(app_instance) as maybe_state:
                yield maybe_state

    app.router.lifespan_context = _mcp_lifespan
    app.state._mcp_lifespan_registered = True
