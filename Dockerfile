# Single image: the frontend is built and then served by the backend.
#
# That mirrors how the app already works — app/main.py mounts frontend/dist at
# / when it exists — so the container has one process, one port, and no CORS.
# Two images behind a proxy would be more "correct" and would also mean nobody
# ever runs this.

# --- build the frontend -----------------------------------------------------
FROM node:20-slim AS frontend

WORKDIR /build
# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim

# curl is here for HEALTHCHECK below; nothing else needs it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY samples/ ./samples/
COPY --from=frontend /build/dist ./frontend/dist

# Pre-download the ~80 MB ONNX MiniLM weights at build time. Otherwise the
# first query after every `docker run` pays for the download, which is exactly
# the "clone and run in five minutes" promise failing at the last step.
RUN python -c "from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()"

# Writable state. Both are regenerable — re-ingesting rebuilds them — so they
# are a volume in compose rather than something to preserve carefully.
ENV CHROMA_PATH=/data/chroma \
    DATABASE_URL=sqlite:////data/glasshouse.db \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data

# Non-root: the container writes only to /data, so there is no reason to run
# the whole thing as root.
RUN useradd --create-home --uid 10001 glasshouse && chown -R glasshouse /data /app
USER glasshouse

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=4 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
