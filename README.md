# bili-summary-mcp

Minimal FastAPI service for Bilibili video ingest with `yt-dlp`.

## Run

```bash
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### Health

- `GET /health`

### Summarize (download-only for now)

- `POST /summarize`
- Body:

```json
{
  "url": "https://www.bilibili.com/video/BV...",
  "prompt": "optional"
}
```

- Response currently contains download metadata and a placeholder summary.
