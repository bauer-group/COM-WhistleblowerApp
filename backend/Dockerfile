# ============================================================
# Backend API – Python 3.14 / FastAPI
# Multi-stage Dockerfile (development + production)
# ============================================================

# ── Base stage ──────────────────────────────────────────────
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by asyncpg and cryptography
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
        gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Development stage ───────────────────────────────────────
FROM base AS development

# Volume-mounted at /app in docker-compose.override.yml
# uvicorn --reload enabled via UVICORN_RELOAD env var
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Production stage ────────────────────────────────────────
FROM base AS production

COPY . .

RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser
USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
