import uuid
from typing import Any, AsyncGenerator

import httpx
from fastapi import HTTPException

from app.qwen.auth import QwenAuthService
from app.qwen.constants import DEFAULT_UA, QWEN_BASE_URL, QWEN_SOURCE, QWEN_TIMEOUT, QWEN_VERSION
from app.qwen.helpers import now_milliseconds, now_seconds, timezone_header_value
from app.qwen.upload import QwenUploader


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
        self._auth = QwenAuthService(client=self._client, headers_builder=self._headers)
        self._uploader = QwenUploader(
            client=self._client,
            request_json=self._request_json,
            get_user_id=lambda: self.user_id,
        )

    @property
    def user_id(self) -> str:
        return self._auth.user_id

    def _headers(
        self,
        *,
        accept: str = "application/json, text/plain, */*",
        referer: str | None = None,
    ) -> dict[str, str]:
        return {
            "x-request-id": str(uuid.uuid4()),
            "timezone": timezone_header_value(),
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

    async def ensure_login(self, force: bool = False) -> None:
        await self._auth.ensure_login(force=force)

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

    async def upload_video_file(
        self,
        *,
        chat_id: str,
        video_url: str,
        index: int,
    ) -> dict[str, Any]:
        return await self._uploader.upload_video_file(chat_id=chat_id, video_url=video_url, index=index)

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
            "timestamp": now_milliseconds(),
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
            "timestamp": now_seconds(),
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
            "timestamp": now_seconds(),
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

