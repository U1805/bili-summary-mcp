import asyncio
import base64
import mimetypes
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import oss2
from fastapi import HTTPException

from app.qwen.constants import QWEN_BASE_URL
from app.qwen.helpers import now_milliseconds


class QwenUploader:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        request_json: Callable[..., Awaitable[Any]],
        get_user_id: Callable[[], str],
    ) -> None:
        self._client = client
        self._request_json = request_json
        self._get_user_id = get_user_id

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
        file_id = str(sts_data.get("file_id") or "")
        file_url = str(sts_data.get("file_url") or "")
        region = str(sts_data.get("region") or "")
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

        created_at = now_milliseconds()
        return {
            "type": "video",
            "file": {
                "created_at": created_at,
                "data": {},
                "filename": filename,
                "hash": None,
                "id": file_id,
                "user_id": self._get_user_id(),
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

