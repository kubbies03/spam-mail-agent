# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-docker.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="spam-mail-agent" \
      org.opencontainers.image.description="Hybrid ML + LangGraph email spam/phishing classifier" \
      org.opencontainers.image.source="https://github.com/kubbies03/spam-mail-agent"

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

COPY src/    ./src/
COPY app/    ./app/
COPY models/ ./models/
COPY main.py ./main.py

RUN addgroup --system --gid 1001 appgroup && \
    adduser  --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    mkdir -p /app/data /app/logs && \
    chown -R appuser:appgroup /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=prod \
    LOG_LEVEL=INFO \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]
