# Single image for both the FastAPI app and the Arq worker.
# Compose decides which entrypoint to run.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/root/.local/bin:$PATH

# uv (pinned-ish — easy to bump)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache deps separately from source.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen 2>/dev/null || uv sync

COPY . .

# Default = API; compose overrides with `command:` for the worker.
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
