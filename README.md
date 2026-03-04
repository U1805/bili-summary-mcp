# bili-summary-mcp

FastAPI service for Bilibili video ingest with `yt-dlp` and multimodal summary via OpenAI-compatible API.

## Run

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Model Config

Create `.env` in project root:

```env
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=YOUR_API_KEY
OPENAI_MODEL_NAME=gpt-4.1-mini
```

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
