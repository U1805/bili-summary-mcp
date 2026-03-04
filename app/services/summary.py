import base64
import mimetypes
from pathlib import Path

from fastapi import HTTPException
from openai import APIConnectionError, APIStatusError, OpenAI

from app.core.constants import DEFAULT_SUMMARY_PROMPT
from app.core.utils import extract_summary_text
from app.core.settings import get_settings


def summarize_video(filepath: str, prompt: str | None) -> str:
    effective_openai = get_settings().effective_openai
    base_url = effective_openai.base_url
    api_key = effective_openai.api_key
    model_name = effective_openai.model_name

    if not effective_openai.is_configured:
        raise HTTPException(
            status_code=500,
            detail=(
                "Missing model config in config.toml. Use either "
                "([openai].api_key + [openai].model_name, [openai].base_url optional) "
                "or ([qwen].email + [qwen].password + [qwen].model_name)."
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
    summary = extract_summary_text(message.get("content"))
    if not summary:
        raise HTTPException(status_code=502, detail=f"Unexpected model response: {data}")
    return summary

