from typing import Any
from urllib.parse import urlparse

from app.core.constants import MAX_UPLOAD_VIDEO_DURATION_SECONDS


def is_bilibili_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    return host.endswith("bilibili.com") or host.endswith("b23.tv")


def extract_summary_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text.strip())
        return "\n".join(texts).strip()
    return ""


def should_skip_upload_by_duration(duration: float | None) -> bool:
    if duration is None:
        return False
    return float(duration) > MAX_UPLOAD_VIDEO_DURATION_SECONDS


def long_video_skip_message(duration: float | None) -> str:
    if duration is None:
        return "视频时长超过10分钟，已跳过上传。请提供10分钟以内的视频后重试。"
    return (
        f"视频时长约 {float(duration):.1f} 秒，超过 600 秒（10 分钟）限制，"
        "已跳过上传。请提供10分钟以内的视频后重试。"
    )

