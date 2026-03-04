import logging

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.core.schemas import SummarizeRequest, SummarizeResponse
from app.services.summary import summarize_video
from app.services.video import download_video
from app.core.utils import is_bilibili_url

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
    summary = await summarize_video(filepath=filepath, prompt=req.prompt)
    logger.info("summarize result url=%s summary=%s", req.url, summary)

    return SummarizeResponse(
        summary=summary,
        title=title,
        duration=duration,
        filepath=filepath,
        prompt=req.prompt,
    )
