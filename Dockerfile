FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/ \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./

# Create a default config for first run; mount app/config.toml to override.
RUN if [ ! -f config.toml ]; then cp config.toml.example config.toml; fi \
    && mkdir -p /app/downloads

RUN uv sync --frozen --no-dev --no-install-project

EXPOSE 8000

CMD ["uv", "run", "--frozen", "python", "-m", "app.main"]
