import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.core.schemas import SummarizeRequest, SummarizeResponse
from app.services.summary import summarize_video
from app.services.video import download_video
from app.core.utils import is_bilibili_url, long_video_skip_message, should_skip_upload_by_duration

router = APIRouter(tags=["summary"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest) -> SummarizeResponse:
    logger.info("summarize request url=%s", req.url)
    if not is_bilibili_url(req.url):
        raise HTTPException(status_code=400, detail="Only Bilibili URLs are supported")

    filepath, title, duration = await run_in_threadpool(download_video, req.url)
    if should_skip_upload_by_duration(duration):
        summary = long_video_skip_message(duration)
        logger.info("summarize skipped upload url=%s duration=%s", req.url, duration)
    else:
        summary = await summarize_video(filepath=filepath, prompt=req.prompt)
    logger.info("summarize result url=%s summary=%s", req.url, summary)

    return SummarizeResponse(
        summary=summary,
        title=title,
        duration=duration,
        filepath=filepath,
        prompt=req.prompt,
    )
