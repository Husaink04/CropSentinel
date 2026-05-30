# ── Stage 1: Install dependencies ─────────────────────────────────────────────
FROM python:3.11-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p /app/reports /app/static

# Run as non-root user for security
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8000
ENV BACKEND_WORKERS=3

CMD ["sh", "-c", "uvicorn main:app --host ${BACKEND_HOST} --port ${BACKEND_PORT} --workers ${BACKEND_WORKERS}"]
