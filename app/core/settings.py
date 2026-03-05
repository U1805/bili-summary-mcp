from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Mapping, Optional
import tomllib
from dotenv.variables import parse_variables

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_SERVER_PORT = 8000
DEFAULT_LOCAL_OPENAI_API_KEY = "local-qwen"
DEFAULT_MCP_TIMEOUT_SECONDS = 300.0
CONFIG_FILE_PATH = Path(__file__).resolve().parents[1] / "config.toml"


@dataclass(frozen=True)
class OpenAIConfig:
    base_url: str = DEFAULT_OPENAI_BASE_URL
    api_key: str = ""
    video_model: str = ""
    audio_model: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.video_model)


@dataclass(frozen=True)
class QwenConfig:
    email: str = ""
    password: str = ""
    video_model: str = ""
    audio_model: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.email and self.password and self.video_model)


@dataclass(frozen=True)
class ServerConfig:
    port: int = DEFAULT_SERVER_PORT


@dataclass(frozen=True)
class MCPConfig:
    timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class AppConfig:
    openai: OpenAIConfig
    qwen: QwenConfig
    server: ServerConfig
    mcp: MCPConfig
    local_openai_base_url: str
    local_openai_api_key: str = DEFAULT_LOCAL_OPENAI_API_KEY

    @property
    def effective_openai(self) -> OpenAIConfig:
        if self.qwen.enabled:
            return OpenAIConfig(
                base_url=self.local_openai_base_url,
                api_key=self.local_openai_api_key,
                video_model=self.qwen.video_model,
                audio_model=self.qwen.audio_model,
            )
        return self.openai


def _read_str(data: dict[str, Any], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _read_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _read_int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_float(data: dict[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _expand_env_placeholders(text: str, env: Mapping[str, Optional[str]]) -> str:
    return "".join(atom.resolve(env) for atom in parse_variables(text))


def _expand_env_in_data(value: Any, env: Mapping[str, Optional[str]]) -> Any:
    if isinstance(value, str):
        return _expand_env_placeholders(value, env)
    if isinstance(value, list):
        return [_expand_env_in_data(item, env) for item in value]
    if isinstance(value, dict):
        return {k: _expand_env_in_data(v, env) for k, v in value.items()}
    return value


def _load_raw_config() -> dict[str, Any]:
    if not CONFIG_FILE_PATH.exists():
        return {}
    with CONFIG_FILE_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    data = _expand_env_in_data(data, os.environ)
    if not isinstance(data, dict):
        return {}
    return data


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    raw = _load_raw_config()
    openai_raw = _read_table(raw, "openai")
    qwen_raw = _read_table(raw, "qwen")
    qwen_localapi_raw = _read_table(qwen_raw, "localapi")
    openai_model_name = _read_str(openai_raw, "model_name")
    qwen_model_name = _read_str(qwen_raw, "model_name")

    openai = OpenAIConfig(
        base_url=_read_str(openai_raw, "base_url", DEFAULT_OPENAI_BASE_URL) or DEFAULT_OPENAI_BASE_URL,
        api_key=_read_str(openai_raw, "api_key"),
        video_model=openai_model_name,
        audio_model=openai_model_name,
    )
    qwen = QwenConfig(
        email=_read_str(qwen_raw, "email"),
        password=_read_str(qwen_raw, "password"),
        video_model=qwen_model_name,
        audio_model=qwen_model_name,
    )
    parsed_port = _read_int(raw, "port", DEFAULT_SERVER_PORT)
    port = parsed_port if 1 <= parsed_port <= 65535 else DEFAULT_SERVER_PORT
    server = ServerConfig(port=port)
    parsed_mcp_timeout = _read_float(raw, "timeout_seconds", DEFAULT_MCP_TIMEOUT_SECONDS)
    mcp = MCPConfig(
        timeout_seconds=parsed_mcp_timeout if parsed_mcp_timeout > 0 else DEFAULT_MCP_TIMEOUT_SECONDS
    )
    default_local_openai_base_url = f"http://127.0.0.1:{server.port}/v1"
    local_base_url = _read_str(qwen_localapi_raw, "base_url", default_local_openai_base_url)
    local_api_key = _read_str(qwen_localapi_raw, "api_key", DEFAULT_LOCAL_OPENAI_API_KEY)
    return AppConfig(
        openai=openai,
        qwen=qwen,
        server=server,
        mcp=mcp,
        local_openai_base_url=local_base_url or default_local_openai_base_url,
        local_openai_api_key=local_api_key or DEFAULT_LOCAL_OPENAI_API_KEY,
    )
