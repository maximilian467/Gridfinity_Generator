# Gridfinity-Einlagen-Generator: ein Container mit Backend (FastAPI) und gebautem Frontend.

# ---- Frontend bauen ------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Python-Abhängigkeiten -----------------------------------------------------------
FROM python:3.11-slim-bookworm AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
# PyTorch (für SAM) in der CPU-Variante: spart mehrere GB CUDA-Bibliotheken
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req-all.txt \
 && grep -viE '^(nvidia-|triton|cuda-)' /tmp/req-all.txt > /tmp/req.txt \
 && uv venv /opt/venv --python 3.11 \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache torch torchvision --index-url https://download.pytorch.org/whl/cpu \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache -r /tmp/req.txt --extra-index-url https://download.pytorch.org/whl/cpu \
      --index-strategy unsafe-best-match

# ---- Laufzeit ------------------------------------------------------------------------
FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 libx11-6 libgomp1 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app
COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
COPY backend/ /app/backend/
COPY --from=web /web/dist /app/frontend/dist
RUN mkdir -p /app/data && chown -R app:app /app/data
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 APP_ENV=prod \
    YOLO_CONFIG_DIR=/app/data/.ultralytics MPLCONFIGDIR=/tmp/mpl
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fs http://127.0.0.1:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "5"]
