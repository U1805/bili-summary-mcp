import hashlib
import time
from datetime import datetime
from typing import Any

from app.qwen.schemas import ChatMessage


def now_seconds() -> int:
    return int(time.time())


def now_milliseconds() -> int:
    return int(time.time() * 1000)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def timezone_header_value() -> str:
    return datetime.now().astimezone().strftime("%a %b %d %Y %H:%M:%S GMT%z")


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(part for part in chunks if part).strip()
    return ""


def compose_qwen_prompt(messages: list[ChatMessage]) -> str:
    role_map = {
        "system": "System",
        "developer": "System",
        "user": "User",
        "assistant": "Assistant",
    }
    blocks: list[str] = []
    for message in messages:
        content = _extract_text_content(message.content).strip()
        if not content:
            continue
        role = role_map.get(message.role.lower(), message.role.title())
        blocks.append(f"[{role}]\n{content}")
    return "\n\n---\n".join(blocks)


def extract_video_urls(messages: list[ChatMessage]) -> list[str]:
    urls: list[str] = []
    for message in messages:
        if message.role.lower() != "user":
            continue
        content = message.content
        if isinstance(content, dict):
            content = [content]
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "video_url":
                continue
            payload = item.get("video_url")
            if not isinstance(payload, dict):
                continue
            url = payload.get("url")
            if isinstance(url, str) and url.strip():
                urls.append(url.strip())
    return urls


def openai_usage_from_qwen(qwen_usage: dict[str, Any] | None) -> dict[str, int]:
    usage = qwen_usage or {}
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }
