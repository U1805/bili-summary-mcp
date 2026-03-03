from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import yt_dlp

app = FastAPI(title="bili-summary-mcp", version="0.1.0")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class SummarizeRequest(BaseModel):
    url: str = Field(..., description="Bilibili video URL")
    prompt: Optional[str] = Field(default=None, description="Optional custom prompt")


class SummarizeResponse(BaseModel):
    summary: str
    title: str
    duration: Optional[float] = None
    filepath: str
    prompt: Optional[str] = None


def _is_bilibili_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    return host.endswith("bilibili.com") or host.endswith("b23.tv")


def download_video(url: str) -> tuple[str, str, Optional[float]]:
    ydl_opts = {
        "format": "worstvideo[ext=mp4]/worstvideo/worst",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"yt-dlp download failed: {exc}") from exc

    title = info.get("title") or "unknown"
    duration = info.get("duration")
    return filepath, title, duration


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest) -> SummarizeResponse:
    if not _is_bilibili_url(req.url):
        raise HTTPException(status_code=400, detail="Only Bilibili URLs are supported")

    filepath, title, duration = download_video(req.url)

    # Placeholder: video summarization pipeline will be implemented in later stages.
    summary = "Video downloaded successfully. Summarization model is not integrated yet."

    return SummarizeResponse(
        summary=summary,
        title=title,
        duration=duration,
        filepath=filepath,
        prompt=req.prompt,
    )
