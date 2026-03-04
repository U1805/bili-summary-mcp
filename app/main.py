import base64
import mimetypes
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel, Field
import yt_dlp

load_dotenv()

app = FastAPI(title="bili-summary-mcp", version="0.1.0")
DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_SUMMARY_PROMPT = (
    "请总结这个视频的核心内容，使用中文输出，包含：主题、关键要点、结论。"
)
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_NAME_ENV = "OPENAI_MODEL_NAME"


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


def _extract_summary_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        return "\n".join(texts).strip()
    return ""


def download_video(url: str) -> tuple[str, str, Optional[float]]:
    ydl_opts = {
        "format": "worstvideo[ext=mp4]+worstaudio[ext=m4a]/worstvideo+worstaudio/worst",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "overwrites": True,
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


def summarize_video(filepath: str, prompt: Optional[str]) -> str:
    base_url = os.getenv(OPENAI_BASE_URL_ENV)
    api_key = os.getenv(OPENAI_API_KEY_ENV)
    model_name = os.getenv(OPENAI_MODEL_NAME_ENV)

    if not base_url or not api_key or not model_name:
        raise HTTPException(
            status_code=500,
            detail=(
                "Missing model config in .env. Required keys: "
                "OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL_NAME"
            ),
        )

    path = Path(filepath)
    if not path.exists():
        raise HTTPException(status_code=500, detail=f"Downloaded file not found: {filepath}")

    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "video/mp4"

    video_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    final_prompt = prompt or DEFAULT_SUMMARY_PROMPT
    client = OpenAI(base_url=base_url, api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的视频分析助手，请根据视频内容做准确总结。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": final_prompt},
                        {
                            "type": "video_url",
                            "video_url": {"url": f"data:{mime_type};base64,{video_base64}"},
                        },
                    ],
                },
            ],
            temperature=0.2,
            timeout=300.0,
        )
    except APIStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model API error: {exc.status_code} {exc.response.text}",
        ) from exc
    except APIConnectionError as exc:
        raise HTTPException(status_code=502, detail=f"Model API request failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Model SDK unexpected error: {exc}") from exc

    data = response.model_dump()
    message = data.get("choices", [{}])[0].get("message", {})
    summary = _extract_summary_text(message.get("content"))
    if not summary:
        raise HTTPException(status_code=502, detail=f"Unexpected model response: {data}")
    return summary


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/summarize", response_model=SummarizeResponse)
def summarize(req: SummarizeRequest) -> SummarizeResponse:
    if not _is_bilibili_url(req.url):
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
