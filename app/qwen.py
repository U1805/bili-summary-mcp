import asyncio
import base64
import hashlib
import json
import mimetypes
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

import httpx
import oss2
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

router = APIRouter(tags=["qwen-openai-compatible"])

QWEN_BASE_URL = "https://chat.qwen.ai"
QWEN_SOURCE = "web"
QWEN_VERSION = "0.2.9"
QWEN_TIMEOUT = 120.0
QWEN_EMAIL_ENV = "QWEN_EMAIL"
QWEN_PASSWORD_ENV = "QWEN_PASSWORD"
OPENAI_MODEL_NAME_ENV = "OPENAI_MODEL_NAME"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "qwen"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelCard]


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatCompletionsRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None
    stream: bool = False
    max_tokens: int | None = None


def _now_seconds() -> int:
    return int(time.time())


def _now_milliseconds() -> int:
    return int(time.time() * 1000)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timezone_header_value() -> str:
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


def _compose_qwen_prompt(messages: list[ChatMessage]) -> str:
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


def _extract_video_urls(messages: list[ChatMessage]) -> list[str]:
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


class QwenSession:
    def __init__(self) -> None:
        # trust_env=False: ignore system proxy env to avoid proxy interference.
        self._client = httpx.AsyncClient(
            base_url=QWEN_BASE_URL,
            timeout=QWEN_TIMEOUT,
            follow_redirects=True,
            trust_env=False,
            headers={
                "user-agent": DEFAULT_UA,
                "source": QWEN_SOURCE,
                "version": QWEN_VERSION,
            },
        )
        self._lock = asyncio.Lock()
        self._logged_in = False
        self._expires_at = 0
        self._user_id = ""

    @property
    def user_id(self) -> str:
        return self._user_id

    def _headers(
        self,
        *,
        accept: str = "application/json, text/plain, */*",
        referer: str | None = None,
    ) -> dict[str, str]:
        return {
            "x-request-id": str(uuid.uuid4()),
            "timezone": _timezone_header_value(),
            "accept": accept,
            "source": QWEN_SOURCE,
            "version": QWEN_VERSION,
            "origin": QWEN_BASE_URL,
            "referer": referer or f"{QWEN_BASE_URL}/",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        }

    def _auth_expired(self) -> bool:
        if not self._logged_in:
            return True
        if self._expires_at <= 0:
            return False
        return _now_seconds() >= (self._expires_at - 60)

    async def ensure_login(self, force: bool = False) -> None:
        if not force and not self._auth_expired():
            return
        async with self._lock:
            if not force and not self._auth_expired():
                return
            await self._login()

    async def _login(self) -> None:
        email = os.getenv(QWEN_EMAIL_ENV, "").strip()
        password = os.getenv(QWEN_PASSWORD_ENV, "")
        if not email or not password:
            raise HTTPException(
                status_code=500,
                detail=f"Missing env vars: {QWEN_EMAIL_ENV}, {QWEN_PASSWORD_ENV}",
            )

        payload = {"email": email, "password": _sha256_hex(password)}
        response = await self._client.post(
            "/api/v2/auths/signin",
            headers={**self._headers(referer=f"{QWEN_BASE_URL}/auth"), "content-type": "application/json"},
            json=payload,
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Qwen signin failed: {response.status_code} {response.text}",
            )
        try:
            data = response.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Qwen signin returned non-JSON body: {response.text[:300]}",
            ) from exc

        if not data.get("success"):
            raise HTTPException(status_code=502, detail=f"Qwen signin failed: {data}")

        auth = data.get("data", {})
        self._user_id = str(auth.get("id", ""))
        self._expires_at = int(auth.get("expires_at") or 0)
        self._logged_in = True

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        referer: str | None = None,
    ) -> Any:
        for attempt in range(2):
            await self.ensure_login()
            response = await self._client.request(
                method=method,
                url=path,
                headers={
                    **self._headers(referer=referer),
                    **({"content-type": "application/json"} if json_payload is not None else {}),
                },
                json=json_payload,
            )
            if response.status_code in (401, 403) and attempt == 0:
                await self.ensure_login(force=True)
                continue
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Qwen API error: {response.status_code} {response.text}",
                )
            try:
                data = response.json()
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Qwen API returned non-JSON body: {response.text[:300]}",
                ) from exc
            if isinstance(data, dict) and data.get("success") is False:
                code = str((data.get("data") or {}).get("code", "")).lower()
                if attempt == 0 and code in {"unauthorized", "forbidden", "auth_error"}:
                    await self.ensure_login(force=True)
                    continue
                raise HTTPException(status_code=502, detail=f"Qwen API error: {data}")
            return data
        raise HTTPException(status_code=502, detail="Qwen API authorization failed")

    @staticmethod
    def _upload_via_oss_sdk(
        *,
        access_key_id: str,
        access_key_secret: str,
        security_token: str,
        bucket_name: str,
        endpoint: str,
        region: str,
        object_path: str,
        content_type: str,
        file_bytes: bytes,
    ) -> int:
        sdk_session = oss2.Session()
        # Disable env proxy inheritance to keep behavior aligned with httpx(trust_env=False).
        sdk_session.session.trust_env = False
        sdk_auth = oss2.StsAuth(
            access_key_id,
            access_key_secret,
            security_token,
            auth_version=oss2.AUTH_VERSION_4,
        )
        normalized_endpoint = endpoint.strip()
        if not normalized_endpoint.startswith(("http://", "https://")):
            normalized_endpoint = f"https://{normalized_endpoint}"
        sign_region = region.replace("oss-", "", 1) if region.startswith("oss-") else region
        bucket = oss2.Bucket(
            sdk_auth,
            normalized_endpoint,
            bucket_name,
            session=sdk_session,
            region=sign_region,
            proxies={},
        )
        result = bucket.put_object(
            object_path,
            file_bytes,
            headers={"Content-Type": content_type},
        )
        return int(getattr(result, "status", 0) or 0)

    async def _load_video_input(
        self,
        *,
        video_url: str,
        index: int,
    ) -> tuple[bytes, str, str]:
        url = video_url.strip()
        if not url:
            raise HTTPException(status_code=400, detail="Empty video_url is not allowed")

        if url.startswith("data:"):
            try:
                header, b64_data = url.split(",", 1)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid data URL for video input") from exc
            if ";base64" not in header:
                raise HTTPException(status_code=400, detail="Only base64 data URL is supported for video input")
            mime_type = header[5:].split(";")[0] or "video/mp4"
            try:
                file_bytes = base64.b64decode(b64_data, validate=True)
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid base64 payload in video_url") from exc
            ext = mimetypes.guess_extension(mime_type) or ".mp4"
            filename = f"video_{index}{ext}"
            return file_bytes, filename, mime_type

        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"}:
            response = await self._client.get(url, headers={"accept": "*/*"})
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to download video_url: {response.status_code} {response.text[:200]}",
                )
            file_bytes = response.content
            filename = Path(parsed.path).name or f"video_{index}.mp4"
            content_type = str(response.headers.get("content-type") or "")
            content_type = content_type.split(";")[0].strip() or mimetypes.guess_type(filename)[0] or "video/mp4"
            return file_bytes, filename, content_type

        local_path = Path(url)
        if not local_path.is_absolute():
            local_path = Path.cwd() / local_path
        if not local_path.exists() or not local_path.is_file():
            raise HTTPException(status_code=400, detail=f"Unsupported video_url input: {video_url}")

        file_bytes = local_path.read_bytes()
        filename = local_path.name
        content_type = mimetypes.guess_type(filename)[0] or "video/mp4"
        return file_bytes, filename, content_type

    async def upload_video_file(
        self,
        *,
        chat_id: str,
        video_url: str,
        index: int,
    ) -> dict[str, Any]:
        file_bytes, filename, content_type = await self._load_video_input(video_url=video_url, index=index)
        get_sts_payload = {
            "filename": filename,
            "filesize": len(file_bytes),
            "filetype": "video",
        }
        data = await self._request_json(
            "POST",
            "/api/v2/files/getstsToken",
            json_payload=get_sts_payload,
            referer=f"{QWEN_BASE_URL}/c/{chat_id}",
        )
        sts_data = data.get("data", {}) if isinstance(data, dict) else {}

        access_key_id = str(sts_data.get("access_key_id") or "")
        access_key_secret = str(sts_data.get("access_key_secret") or "")
        security_token = str(sts_data.get("security_token") or "")
        bucket_name = str(sts_data.get("bucketname") or "")
        endpoint = str(sts_data.get("endpoint") or "")
        file_path = str(sts_data.get("file_path") or "")
        region = str(sts_data.get("region") or "")
        file_id = str(sts_data.get("file_id") or "")
        file_url = str(sts_data.get("file_url") or "")
        if not (
            access_key_id
            and access_key_secret
            and security_token
            and bucket_name
            and endpoint
            and file_path
            and file_id
            and file_url
        ):
            raise HTTPException(status_code=502, detail=f"Invalid getstsToken response: {data}")

        upload_status = await asyncio.to_thread(
            self._upload_via_oss_sdk,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token,
            bucket_name=bucket_name,
            endpoint=endpoint,
            region=region,
            object_path=file_path,
            content_type=content_type,
            file_bytes=file_bytes,
        )
        if upload_status != 200:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Qwen video upload failed via oss sdk: "
                    f"status={upload_status}"
                ),
            )

        created_at = _now_milliseconds()
        return {
            "type": "video",
            "file": {
                "created_at": created_at,
                "data": {},
                "filename": filename,
                "hash": None,
                "id": file_id,
                "user_id": self.user_id,
                "meta": {
                    "name": filename,
                    "size": len(file_bytes),
                    "content_type": content_type,
                },
                "update_at": created_at,
            },
            "id": file_id,
            "url": file_url,
            "name": filename,
            "collection_name": "",
            "progress": 0,
            "status": "uploaded",
            "greenNet": "greening",
            "size": len(file_bytes),
            "error": "",
            "itemId": str(uuid.uuid4()),
            "file_type": content_type,
            "showType": "video",
            "file_class": "video",
            "uploadTaskId": str(uuid.uuid4()),
        }

    async def get_models(self) -> list[dict[str, Any]]:
        data = await self._request_json("GET", "/api/models", referer=f"{QWEN_BASE_URL}/")
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data, list):
            return data
        raise HTTPException(status_code=502, detail=f"Unexpected models response: {data}")

    async def create_chat(self, model: str) -> str:
        payload = {
            "title": "New Chat",
            "models": [model],
            "chat_mode": "normal",
            "chat_type": "t2t",
            "timestamp": _now_milliseconds(),
            "project_id": "",
        }
        data = await self._request_json(
            "POST",
            "/api/v2/chats/new",
            json_payload=payload,
            referer=f"{QWEN_BASE_URL}/c/new-chat",
        )
        chat_id = data.get("data", {}).get("id") if isinstance(data, dict) else None
        if not chat_id:
            raise HTTPException(status_code=502, detail=f"Unexpected create chat response: {data}")
        return str(chat_id)

    async def stream_completion(
        self,
        *,
        chat_id: str,
        model: str,
        content: str,
        files: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str, None]:
        message_id = str(uuid.uuid4())
        message_payload: dict[str, Any] = {
            "fid": message_id,
            "parentId": None,
            "childrenIds": [],
            "role": "user",
            "content": content,
            "user_action": "chat",
            "timestamp": _now_seconds(),
            "models": [model],
            "chat_type": "t2t",
            "feature_config": {
                "thinking_enabled": True,
                "output_schema": "phase",
                "research_mode": "normal",
                "auto_thinking": True,
                "thinking_format": "summary",
                "auto_search": True,
            },
            "extra": {"meta": {"subChatType": "t2t"}},
            "sub_chat_type": "t2t",
            "parent_id": None,
        }
        if files:
            message_payload["files"] = files

        payload = {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": None,
            "messages": [message_payload],
            "timestamp": _now_seconds(),
        }

        url = f"/api/v2/chat/completions?chat_id={chat_id}"
        for attempt in range(2):
            await self.ensure_login()
            async with self._client.stream(
                "POST",
                url,
                headers={
                    **self._headers(accept="application/json", referer=f"{QWEN_BASE_URL}/c/{chat_id}"),
                    "content-type": "application/json",
                },
                json=payload,
            ) as response:
                if response.status_code in (401, 403) and attempt == 0:
                    await self.ensure_login(force=True)
                    continue
                if response.status_code >= 400:
                    error_text = (await response.aread()).decode("utf-8", errors="ignore")
                    raise HTTPException(
                        status_code=502,
                        detail=f"Qwen completion failed: {response.status_code} {error_text}",
                    )

                content_type = (response.headers.get("content-type") or "").lower()
                if "text/event-stream" not in content_type:
                    body = (await response.aread()).decode("utf-8", errors="ignore")
                    raise HTTPException(
                        status_code=502,
                        detail=f"Qwen completion non-stream response: {body[:500]}",
                    )

                async for line in response.aiter_lines():
                    if line:
                        yield line
                return
        raise HTTPException(status_code=502, detail="Qwen completion authorization failed")

    async def aclose(self) -> None:
        await self._client.aclose()


qwen_session = QwenSession()


def _openai_usage_from_qwen(qwen_usage: dict[str, Any] | None) -> dict[str, int]:
    usage = qwen_usage or {}
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


async def _collect_qwen_answer(
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

    return "".join(parts).strip(), _openai_usage_from_qwen(usage), response_id


async def _stream_openai_chunks(
    *,
    chat_id: str,
    model: str,
    prompt: str,
    files: list[dict[str, Any]] | None = None,
) -> AsyncGenerator[str, None]:
    created = _now_seconds()
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

    model = request.model or os.getenv(OPENAI_MODEL_NAME_ENV, "qwen3.5-plus")
    composed_prompt = _compose_qwen_prompt(request.messages)
    video_urls = _extract_video_urls(request.messages)
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
            _stream_openai_chunks(
                chat_id=chat_id,
                model=model,
                prompt=composed_prompt,
                files=uploaded_files or None,
            ),
            media_type="text/event-stream",
        )

    answer, usage, response_id = await _collect_qwen_answer(
        chat_id=chat_id,
        model=model,
        prompt=composed_prompt,
        files=uploaded_files or None,
    )
    return {
        "id": response_id,
        "object": "chat.completion",
        "created": _now_seconds(),
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
    @app.on_event("startup")
    async def _startup_qwen_login() -> None:
        await qwen_session.ensure_login(force=True)

    @app.on_event("shutdown")
    async def _shutdown_qwen_client() -> None:
        await qwen_session.aclose()
