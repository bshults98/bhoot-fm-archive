# Multi-stage build keeps the final image small (~120 MB).
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: only what FastAPI/Uvicorn need.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python deps first (better layer caching).
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code.
COPY server.py ./
COPY static ./static

# Fetch the production DB from its companion HF Dataset repo instead of
# baking it into the Space's git history. Keeps the Space repo tiny and
# avoids LFS-bucket bloat (every redeploy would otherwise add a fresh
# ~190 MB blob to the Space's LFS store, which doesn't auto-GC). The
# dataset is public, so no auth header is needed. Cache-buster query
# forces Docker layer invalidation when DATASET_DB_VERSION changes —
# pass `--build-arg DATASET_DB_VERSION=<sha-or-date>` to force a re-pull
# on a build that would otherwise hit the cached RUN.
ARG DATASET_DB_VERSION=latest
RUN python -c "import sys, urllib.request as u; \
    url = 'https://huggingface.co/datasets/xer2ten/bhoot-fm-archive-db/resolve/main/archive.prod.db'; \
    print(f'Fetching {url} (build tag: ${DATASET_DB_VERSION})', file=sys.stderr); \
    u.urlretrieve(url, 'archive.db')"

# Non-root for safety.
RUN useradd --uid 10001 --create-home app && chown -R app:app /app
USER app

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
