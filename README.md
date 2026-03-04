# bili-summary-mcp

FastAPI service for Bilibili video ingest with `yt-dlp` and multimodal summary via OpenAI-compatible API.

## Run

```bash
uv sync
uv run python -m app.main
```

## Model Config (TOML)

Create `app/config.toml` (you can copy from `app/config.toml.example`).

Server port:

```toml
[server]
port = 8000
```

Mode 1: external OpenAI-compatible API

```toml
[openai]
base_url = "https://api.openai.com/v1" # optional
api_key = "YOUR_API_KEY"
model_name = "gpt-4.1-mini"
```

Mode 2: local Qwen gateway reuse

```toml
[qwen]
email = "YOUR_QWEN_EMAIL"
password = "YOUR_QWEN_PASSWORD"
model_name = "qwen3.5-plus"

[qwen.localapi] # optional
base_url = "http://127.0.0.1:8000/v1"
api_key = "local-qwen"
```

When all `[qwen]` values are set:
- App mounts local `/v1/models` and `/v1/chat/completions`.
- `main.py` automatically reuses this local OpenAI-compatible interface.
- Mode 2 automatically overrides Mode 1 (`[openai]`) effective runtime config.
- Effective `openai.base_url` and `openai.api_key` come from `[qwen.localapi]` (or defaults).
- Effective `openai.model_name` is `qwen.model_name`.

## API

### Health

- `GET /health`

### Summarize

- `POST /summarize`
- Body:

```json
{
  "url": "https://www.bilibili.com/video/BV...",
  "prompt": "optional"
}
```

- Response returns model-generated summary from multimodal API.

### MCP Config

Before configuring an agent, start this service first:

```bash
uv run python -m app.main
```

Use this MCP endpoint:

- `http://127.0.0.1:8000/mcp/`

Common MCP config examples:

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

If your `app/config.toml` sets a custom `[server].port`, replace `8000` accordingly.
