import json
import uuid
from typing import Any, AsyncGenerator

from app.qwen.helpers import now_seconds, openai_usage_from_qwen
from app.qwen.session import qwen_session


async def collect_qwen_answer(
    *,
    chat_id: str,
    model: str,
    prompt: str,
    files: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, int], str]:
    parts: list[str] = []
    usage: dict[str, Any] | None = None
    response_id = f"chatcmpl-{uuid.uuid4().hex}"

    async for line in qwen_session.stream_completion(
        chat_id=chat_id,
        model=model,
        content=prompt,
        files=files,
    ):
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if "response.created" in obj and isinstance(obj["response.created"], dict):
            response_id = str(obj["response.created"].get("response_id") or response_id)
            continue

        if isinstance(obj, dict) and obj.get("response_id"):
            response_id = str(obj["response_id"])

        if isinstance(obj, dict) and obj.get("usage"):
            usage = obj["usage"]

        choices = obj.get("choices") if isinstance(obj, dict) else None
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content_piece = delta.get("content")
            if isinstance(content_piece, str) and content_piece:
                parts.append(content_piece)

    return "".join(parts).strip(), openai_usage_from_qwen(usage), response_id


async def stream_openai_chunks(
    *,
    chat_id: str,
    model: str,
    prompt: str,
    files: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
    created = now_seconds()
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    header_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(header_chunk, ensure_ascii=False)}\n\n"

    async for line in qwen_session.stream_completion(
        chat_id=chat_id,
        model=model,
        content=prompt,
        files=files,
    ):
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if "response.created" in obj and isinstance(obj["response.created"], dict):
            completion_id = str(obj["response.created"].get("response_id") or completion_id)
            continue
        if isinstance(obj, dict) and obj.get("response_id"):
            completion_id = str(obj["response_id"])

        choices = obj.get("choices") if isinstance(obj, dict) else None
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content_piece = delta.get("content")
            if not isinstance(content_piece, str) or not content_piece:
                continue
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": content_piece},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    tail_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(tail_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"
