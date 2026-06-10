FROM python:3.12-slim

# System deps required by :
# - Playwright/Chromium headless
# - RAG legacy .doc extraction (antiword)
# - python-magic / neonize (libmagic1) for WhatsApp Web media type detection
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    fonts-liberation wget ca-certificates \
    antiword \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies (no editable install in production)
RUN uv sync --frozen --no-dev --no-editable

# ── Post-sync bump for WhatsApp Web (neonize) ─────────────────────────
# WhatsApp rejects older protocol versions with `err-client-outdated` (405).
# neonize >= 0.3.17.post0 is required but pulls protobuf >= 6.32 which
# conflicts with the deprecated `google-generativeai` package (still in
# our deps for Imagen/Vision). We force-install neonize on top of the
# locked env — protobuf 7 remains wire-compatible with existing Gemini
# calls, so this is runtime-safe.
# TODO: migrate image_tool.py / vision_skill.py / image_skill.py to the
# new `google-genai` SDK, then this override can be removed.
RUN uv pip install --force-reinstall "neonize>=0.3.17.post0" "protobuf>=6.32.1"

# ── Couche 2 PII NER — install opt-in (PII_NER_ENABLED) ───────────────
# Le package gliner tire torch (~800 Mo installés) : on ne l'embarque QUE
# si le build est lancé avec PII_NER_INSTALL=1 (via .env, cf. docker-compose
# build args). Installé hors lockfile comme neonize — gliner pousse
# transformers/torch que le projet ne veut pas dans ses deps par défaut.
# Le modèle ONNX int8 lui-même n'est PAS dans l'image : il est exporté sur
# l'hôte (scripts/export_gliner_onnx.py) vers ./data/pii_ner, monté en volume.
ARG PII_NER_INSTALL=0
RUN if [ "$PII_NER_INSTALL" = "1" ]; then \
        uv pip install "gliner>=0.2.26"; \
    fi

# Config files (hosts, providers) mounted via volume at runtime
# but we create the dir so the app doesn't fail if not mounted
RUN mkdir -p /config /app/uploads

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# Keep uv cache inside /app so the non-root user has write access
ENV UV_CACHE_DIR=/app/.cache/uv
# Keep Playwright browsers inside /app so the non-root user has write access
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/playwright
# Persistent cache for fastembed (embeddings model ~90 MB)
ENV FASTEMBED_CACHE_DIR=/app/.cache/fastembed
# Disable HF Xet transfer (it has permission issues with non-root users in containers)
ENV HF_HUB_DISABLE_XET=1

# Run as non-root for container security (SEC-7)
RUN adduser --system --no-create-home --uid 1001 appuser \
    && mkdir -p /app/.cache/uv /app/.cache/playwright /app/.cache/fastembed \
    && chown -R appuser /app /config

# Install Playwright Chromium as appuser (browsers land in PLAYWRIGHT_BROWSERS_PATH).
# `--force` ensures the download is re-done when the Playwright pip version
# changes between builds (otherwise the browser binary on an old cached
# layer won't match the new Playwright's expected path, and every browser_*
# tool silently fails at runtime with "Executable doesn't exist").
USER appuser
RUN uv run --no-sync playwright install --force chromium

# Pre-download fastembed ONNX model (~90 MB) so first embed doesn't need network
# and doesn't hit HF Hub permission edge cases at runtime.
RUN uv pip uninstall hf_xet 2>/dev/null || true
RUN uv run --no-sync python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='sentence-transformers/all-MiniLM-L6-v2', cache_dir='/app/.cache/fastembed')" \
    || echo "WARNING: fastembed pre-download failed, will retry at runtime"

# ── Application code — copied LAST for layer caching ──────────────────
# Everything above (Chromium ~150 MB download, fastembed ~90 MB) is
# independent of the app source: a code-only change must rebuild ONLY the
# COPY layers below, not the heavy RUN layers. `--chown=appuser` because
# the recursive `chown -R appuser /app` above ran before these files
# existed (same ownership the chown used to give them).
COPY --chown=appuser app/ ./app/

# Alembic — ensure_migrations() au boot exige ces deux chemins dans l'image.
# Sans eux il échoue en best-effort (CRITICAL dans les logs, boot continue)
# et la base prod ne reçoit JAMAIS les révisions post-baseline — vécu en
# v1.17.0 : missions.spec_yaml absente → HTTP 500 sur toute la page Missions.
COPY --chown=appuser alembic.ini ./
COPY --chown=appuser migrations/ ./migrations/

# Copy operational scripts (backfill, admin, migrations…)
# Run from the container with: docker compose exec backend python scripts/<name>.py
COPY --chown=appuser scripts/ ./scripts/

EXPOSE 8000

# `uv run --no-sync` launches uvicorn from the venv without re-resolving
# dependencies. This is critical because the post-sync neonize upgrade
# introduces a protobuf version that `uv run` would want to "fix" by
# reverting to the locked version → breaks WhatsApp.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
