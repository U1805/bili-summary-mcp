import asyncio
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.settings import get_settings
from app.qwen.constants import QWEN_BASE_URL
from app.qwen.helpers import now_seconds, sha256_hex


class QwenAuthService:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        headers_builder: Callable[..., dict[str, str]],
    ) -> None:
        self._client = client
        self._headers_builder = headers_builder
        self._lock = asyncio.Lock()
        self._logged_in = False
        self._expires_at = 0
        self._user_id = ""

    @property
    def user_id(self) -> str:
        return self._user_id

    def _auth_expired(self) -> bool:
        if not self._logged_in:
            return True
        if self._expires_at <= 0:
            return False
        return now_seconds() >= (self._expires_at - 60)

    async def ensure_login(self, force: bool = False) -> None:
        if not force and not self._auth_expired():
            return
        async with self._lock:
            if not force and not self._auth_expired():
                return
            await self._login()

    async def _login(self) -> None:
        qwen = get_settings().qwen
        email = qwen.email.strip()
        password = qwen.password
        if not (email and password and qwen.video_model):
            raise HTTPException(
                status_code=500,
                detail=(
                    "Missing Qwen config in config.toml. "
                    "Required keys: [qwen].email, [qwen].password, [qwen].model_name"
                ),
            )

        payload = {"email": email, "password": sha256_hex(password)}
        response = await self._client.post(
            "/api/v2/auths/signin",
            headers={**self._headers_builder(referer=f"{QWEN_BASE_URL}/auth"), "content-type": "application/json"},
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

        auth = data.get("data", {}) if isinstance(data, dict) else {}
        self._user_id = str(auth.get("id", ""))
        self._expires_at = int(auth.get("expires_at") or 0)
        self._logged_in = True
