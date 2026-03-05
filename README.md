[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker GHCR](https://github.com/U1805/bili-summary-mcp/actions/workflows/docker-ghcr.yml/badge.svg)](https://github.com/U1805/bili-summary-mcp/actions/workflows/docker-ghcr.yml)

# bili-summary-mcp

> Enable AI assistants to watch Bilibili videos through a MCP interface.

`bili-summary-mcp` is a FastAPI + MCP server that downloads a Bilibili video with `yt-dlp`, sends it to an OpenAI-compatible multimodal model, and returns a structured summary.

## Core Features

- Bilibili video summarize via MCP tool `summarize_video`
- HTTP API for direct integration (`/summarize`)
- Streamable HTTP MCP transport mounted at `/mcp`
- OpenAI-compatible provider mode (`[openai]`)
- Local Qwen gateway mode (`[qwen]`)

## Quick Start

### Local Development

```bash
git clone https://github.com/U1805/bili-summary-mcp.git
cd bili-summary-mcp

uv sync
cp app/config.toml.example app/config.toml
# edit app/config.toml

uv run python -m app.main
```

Service default address:

- HTTP API: `http://127.0.0.1:8000`
- MCP endpoint: `http://127.0.0.1:8000/mcp/`

### Docker Compose

```bash
cp app/config.toml.example app/config.toml
# edit app/config.toml
docker compose up -d
```

## MCP Integration

Add this config to your MCP client:

```json
{
  "mcpServers": {
    "bili-summary-mcp": {
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8000/mcp/"
    }
  }
}
```

## Available Tools

### summarize_video

Download one Bilibili video and return structured summary output.

Input:

- `url` (required): absolute `http(s)` URL from `*.bilibili.com` or `b23.tv`
- `prompt` (optional): custom summarize instruction

Example:

```python
result = await call_tool("summarize_video", {
    "url": "https://www.bilibili.com/video/BV1A9ABzrEQG/",
    "prompt": "Summarize key points and conclusions in Chinese."
})
```

Output shape:

```json
{
  "summary": "...",
  "title": "...",
  "duration": 123.4
}
```

## HTTP API

### Health

- `GET /health`

Example response:

```json
{"status": "ok"}
```

### Summarize

- `POST /summarize`

Request body:

```json
{
  "url": "https://www.bilibili.com/video/BV...",
  "prompt": "optional"
}
```

Response body:

```json
{
  "summary": "...",
  "title": "...",
  "duration": 123.4,
  "filepath": "downloads/xxx.mp4",
  "prompt": "optional"
}
```

### Qwen Local OpenAI-Compatible Endpoints

Available only when `[qwen]` is enabled in config:

- `GET /v1/models`
- `POST /v1/chat/completions`

## Configuration

Main config file: `app/config.toml`

| Key | Purpose | Default |
|---|---|---|
| `port` | HTTP server port | `8000` |
| `timeout_seconds` | MCP summarize timeout (seconds) | `300` |
| `downloader.proxy` | Optional proxy used by `yt-dlp` for Bilibili download (`socks5://...` or `http://...`) | `""` |
| `openai.base_url` | OpenAI-compatible API base URL | `https://api.openai.com/v1` |
| `openai.api_key` | API key for provider mode | `""` |
| `openai.model_name` | Model used for summarization (provider mode) | `""` |
| `qwen.email` | Qwen account email | `""` |
| `qwen.password` | Qwen account password | `""` |
| `qwen.model_name` | Qwen model for local gateway mode | `""` |
| `qwen.localapi.base_url` | Local OpenAI-compatible base URL | `http://127.0.0.1:8000/v1` |
| `qwen.localapi.api_key` | Local OpenAI-compatible API key | `local-qwen` |

### Mode 1: External OpenAI-Compatible Provider

```toml
port = 8000
timeout_seconds = 300

[openai]
base_url = "https://api.openai.com/v1"
api_key = "YOUR_API_KEY"
model_name = "gpt-4.1-mini"
```

### Mode 2: Local Qwen Gateway

When `qwen.email`, `qwen.password`, and `qwen.model_name` are all set, Qwen mode is enabled and overrides `[openai]` runtime config.

```toml
port = 8000
timeout_seconds = 300

[qwen]
email = "YOUR_QWEN_EMAIL"
password = "YOUR_QWEN_PASSWORD"
model_name = "qwen3-omni-flash"

[qwen.localapi]
base_url = "http://127.0.0.1:8000/v1"
api_key = "local-qwen"
```

## Behavior Notes

- Only Bilibili URLs are accepted (`*.bilibili.com`, `b23.tv`).
- Videos longer than 600 seconds are skipped with a limit message.
- Downloaded temp files are cleaned up after request completion.
- `app/config.toml` supports `${ENV_VAR}` placeholder expansion.

## License

Released under the MIT License. See `LICENSE` for details.

## Contributing

- Issues: https://github.com/U1805/bili-summary-mcp/issues
- Pull requests: https://github.com/U1805/bili-summary-mcp/pulls
