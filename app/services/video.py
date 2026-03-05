import logging
from pathlib import Path

from fastapi import HTTPException
import yt_dlp

from app.core.constants import DOWNLOAD_DIR
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def download_video(url: str) -> tuple[str, str, float | None]:
    proxy = get_settings().downloader.proxy
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
    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"yt-dlp download failed: {exc}") from exc

    title = info.get("title") or "unknown"
    duration = info.get("duration")
    return filepath, title, duration


def cleanup_downloaded_video(filepath: str) -> None:
    try:
        Path(filepath).unlink(missing_ok=True)
    except Exception as exc:
        # Cleanup must not break request flow.
        logger.warning("failed to cleanup downloaded video filepath=%s error=%s", filepath, exc)

