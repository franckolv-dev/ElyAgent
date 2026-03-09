FROM python:3.12-slim

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
RUN mkdir -p /config

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
