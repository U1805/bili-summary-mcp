from pathlib import Path

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SUMMARY_PROMPT = (
    "请总结这个视频的核心内容，使用中文输出，包含：主题、关键要点、结论。"
)

MAX_UPLOAD_VIDEO_DURATION_SECONDS = 600.0

