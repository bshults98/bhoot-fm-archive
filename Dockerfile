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

# App code + production DB.
COPY server.py ./
COPY static ./static
# The production DB is built locally via prepare_production_db.py.
# We copy it in as `archive.db` so the server finds it at the default path.
COPY archive.prod.db ./archive.db

# Non-root for safety.
RUN useradd --uid 10001 --create-home app && chown -R app:app /app
USER app

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
