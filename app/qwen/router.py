from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.core.settings import get_settings
from app.qwen.adapter import collect_qwen_answer, stream_openai_chunks
from app.qwen.helpers import compose_qwen_prompt, extract_video_urls, now_seconds
from app.qwen.schemas import ChatCompletionsRequest, ModelCard, ModelsResponse
from app.qwen.session import qwen_session

router = APIRouter(tags=["qwen-openai-compatible"])


@router.get("/v1/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    models = await qwen_session.get_models()
    return ModelsResponse(
        data=[
            ModelCard(
                id=str(model.get("id", "")),
                owned_by=str(model.get("owned_by", "qwen")),
            )
            for model in models
            if model.get("id")
        ]
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionsRequest) -> Any:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages is required")

    qwen = get_settings().qwen
    if not qwen.enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Qwen local OpenAI-compatible gateway is disabled. "
                "Set [qwen].email, [qwen].password and [qwen].model_name in config.toml."
            ),
        )

    model = request.model or qwen.video_model
    composed_prompt = compose_qwen_prompt(request.messages)
    video_urls = extract_video_urls(request.messages)
    if not composed_prompt and not video_urls:
        raise HTTPException(status_code=400, detail="messages content is empty after normalization")
    if not composed_prompt and video_urls:
        composed_prompt = "请基于我上传的视频内容进行分析并回答。"

    chat_id = await qwen_session.create_chat(model)
    uploaded_files: list[dict[str, Any]] = []
    for idx, video_url in enumerate(video_urls):
        uploaded_files.append(
            await qwen_session.upload_video_file(
                chat_id=chat_id,
                video_url=video_url,
                index=idx,
            )
        )

    if request.stream:
        return StreamingResponse(
            stream_openai_chunks(
                chat_id=chat_id,
                model=model,
                prompt=composed_prompt,
                files=uploaded_files or None,
            ),
            media_type="text/event-stream",
        )

    answer, usage, response_id = await collect_qwen_answer(
        chat_id=chat_id,
        model=model,
        prompt=composed_prompt,
        files=uploaded_files or None,
    )
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": now_seconds(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


def register_qwen_lifecycle(app: FastAPI) -> None:
    if not get_settings().qwen.enabled:
        return

    if getattr(app.state, "_qwen_lifespan_registered", False):
        return

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def _qwen_lifespan(app_instance: FastAPI):
        await qwen_session.ensure_login(force=True)
        try:
            async with previous_lifespan(app_instance) as maybe_state:
                yield maybe_state
        finally:
            await qwen_session.aclose()

    app.router.lifespan_context = _qwen_lifespan
    app.state._qwen_lifespan_registered = True
