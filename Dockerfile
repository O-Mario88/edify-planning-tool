# ── edify-api (Django + DRF) ─────────────────────────────────────────────────
# Multi-stage: install deps, run a lean runtime image.

FROM python:3.13-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
# Build deps for psycopg (compiles against libpq) + Pillow.
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements/ ./requirements/
RUN pip install --prefix=/install -r requirements/prod.txt

FROM python:3.13-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=4000
# Runtime deps: libpq (psycopg), libexpat (ASGI), and headless LibreOffice for
# the evidence DOCX→PDF rendition pipeline (optional; skipped if absent).
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    libpq5 libexpat1 curl \
    libreoffice --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# Site-packages from the build stage.
COPY --from=build /install /usr/local
# Application source.
COPY . .
# Collect static (DRF spectacular + admin assets).
RUN python manage.py collectstatic --noinput || true

EXPOSE 4000
# Apply migrations, optionally seed, then start the ASGI server (daphne for
# realtime SSE + the scheduler). Health probe hits GET /api/health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://localhost:${PORT:-4000}/api/health" || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "4000", "config.asgi:application"]
