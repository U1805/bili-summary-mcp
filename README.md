# bili-summary-mcp

FastAPI service for Bilibili video ingest with `yt-dlp` and multimodal summary via OpenAI-compatible API.

## Run

```bash
uv sync
uv run python -m app.main
```

## Docker Compose

1. Create config file:

```bash
cp app/config.toml.example app/config.toml
```

2. Start service:

```bash
docker compose up -d
```

3. Check health:

```bash
curl http://127.0.0.1:8000/health
```

## Model Config

Create `app/config.toml` (you can copy from `app/config.toml.example`).

Top-level runtime config:

```toml
port = 8000

# MCP tool timeout in seconds.
# When timeout is reached, the server cancels the in-flight LLM request.
timeout_seconds = 300

model_name = "gpt-4.1-mini"
```

Mode 1: external OpenAI-compatible API

```toml
[openai]
base_url = "https://api.openai.com/v1" # optional
api_key = "YOUR_API_KEY"
```

Mode 2: local Qwen gateway reuse

```toml
[qwen]
email = "YOUR_QWEN_EMAIL"
password = "YOUR_QWEN_PASSWORD"

[qwen.localapi] # optional
base_url = "http://127.0.0.1:8000/v1"
api_key = "local-qwen"
```

When `[qwen].email` and `[qwen].password` are set:
- App mounts local OpenAI-compatible interface `/v1/models` and `/v1/chat/completions`.
- Mode 2 automatically overrides Mode 1 (`[openai]`) effective runtime config.

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
