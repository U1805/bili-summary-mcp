import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from typing import Annotated

from fastapi import HTTPException
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp

from app.core.settings import get_settings
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
logger = logging.getLogger(__name__)


class SummarizeVideoToolOutput(BaseModel):
    summary: str = Field(
        description="Model-generated summary of the video content.",
    )
    title: str = Field(
        description="Video title parsed from metadata after download.",
    )
    duration: float | None = Field(
        default=None,
        description="Video duration in seconds from source metadata.",
    )
    filepath: str = Field(
        description="Local relative path of the downloaded video file.",
        examples=["downloads/BV1A9ABzrEQG.mp4"],
    )
    prompt: str | None = Field(
        default=None,
        description=(
            "The effective summarization prompt. "
            "When null, the server used its default prompt."
        ),
    )


def _format_http_exception(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, (dict, list)):
        detail_text = json.dumps(detail, ensure_ascii=False)
    else:
        detail_text = str(detail)
    return f"HTTP {exc.status_code}: {detail_text}"


@mcp_server.tool(
    name="summarize_video",
    description=(
        "Download one Bilibili video and return a structured summary. "
        "Input must include a full http(s) URL from bilibili.com or b23.tv."
    ),
)
async def summarize_video_tool(
    url: Annotated[
        str,
        Field(
            description=(
                "Bilibili video URL. Must be an absolute http(s) URL with host "
                "`*.bilibili.com` or `b23.tv`."
            ),
            examples=["https://www.bilibili.com/video/BV1A9ABzrEQG/"],
            min_length=1,
        ),
    ],
    prompt: Annotated[
        str | None,
        Field(
            description=(
                "Optional summarization instruction. "
                "If omitted, server default prompt will be used."
            ),
            examples=["Summarize the content of this video."],
        ),
    ] = None,
) -> SummarizeVideoToolOutput:
    """Summarize a Bilibili video with the project's existing workflow.

    Args:
        url: Absolute video URL on bilibili.com or b23.tv.
        prompt: Optional custom instruction for the model.

    Returns:
        Structured summary result including summary text, title, duration, and local file path.
    """
    normalized_url = url.strip()
    logger.info("mcp summarize_video request url=%s", normalized_url)
    if not is_bilibili_url(normalized_url):
        raise ValueError("Only Bilibili URLs are supported")
    normalized_prompt = prompt.strip() if isinstance(prompt, str) else None
    if normalized_prompt == "":
        normalized_prompt = None

    llm_task: asyncio.Task[str] | None = None
    try:
        filepath, title, duration = await run_in_threadpool(download_video, normalized_url)
        timeout_seconds = get_settings().mcp.timeout_seconds
        llm_task = asyncio.create_task(
            summarize_video(
                filepath=filepath,
                prompt=normalized_prompt,
                request_timeout_seconds=timeout_seconds,
            )
        )
        try:
            summary = await asyncio.wait_for(llm_task, timeout=timeout_seconds)
        except TimeoutError as exc:
            llm_task.cancel()
            with suppress(asyncio.CancelledError):
                await llm_task
            logger.error(
                "mcp summarize_video timeout url=%s timeout_seconds=%s",
                normalized_url,
                timeout_seconds,
            )
            raise RuntimeError(
                f"MCP summarize_video timed out after {timeout_seconds:.1f}s; cancelled LLM request"
            ) from exc
    except asyncio.CancelledError:
        if llm_task is not None and not llm_task.done():
            llm_task.cancel()
            with suppress(asyncio.CancelledError):
                await llm_task
        logger.error("mcp summarize_video cancelled url=%s", normalized_url)
        raise
    except HTTPException as exc:
        raise RuntimeError(_format_http_exception(exc)) from exc
    logger.info("mcp summarize_video result url=%s summary=%s", normalized_url, summary)

    return SummarizeVideoToolOutput(
        summary=summary,
        title=title,
        duration=duration,
        filepath=filepath,
        prompt=normalized_prompt,
    )


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
