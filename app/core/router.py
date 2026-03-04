from fastapi import APIRouter, HTTPException

from app.core.schemas import SummarizeRequest, SummarizeResponse
from app.services.summary import summarize_video
from app.services.video import download_video
from app.core.utils import is_bilibili_url

router = APIRouter(tags=["summary"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest) -> SummarizeResponse:
    if not is_bilibili_url(req.url):
        raise HTTPException(status_code=400, detail="Only Bilibili URLs are supported")

    filepath, title, duration = download_video(req.url)
    summary = summarize_video(filepath=filepath, prompt=req.prompt)

    return SummarizeResponse(
        summary=summary,
        title=title,
        duration=duration,
        filepath=filepath,
        prompt=req.prompt,
    )
