FROM python:3.12-slim

# System deps required by Playwright/Chromium headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    fonts-liberation wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (no editable install in production)
RUN uv sync --frozen --no-dev --no-editable

# Copy application code
COPY app/ ./app/

# Config files (hosts, providers) mounted via volume at runtime
# but we create the dir so the app doesn't fail if not mounted
RUN mkdir -p /config /app/uploads

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Keep uv cache inside /app so the non-root user has write access
ENV UV_CACHE_DIR=/app/.cache/uv
# Keep Playwright browsers inside /app so the non-root user has write access
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/playwright

# Run as non-root for container security (SEC-7)
RUN adduser --system --no-create-home --uid 1001 appuser \
    && mkdir -p /app/.cache/uv /app/.cache/playwright \
    && chown -R appuser /app /config

# Install Playwright Chromium as appuser (browsers land in PLAYWRIGHT_BROWSERS_PATH)
USER appuser
RUN uv run playwright install chromium

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
