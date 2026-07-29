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
# Collect static (DRF spectacular + admin assets). Fail the build if static
# collection errors — a silent failure here means broken CSS/JS in production.
# config/settings/prod.py fails closed at import unless its whole required set
# is present — none of it exists at build time (.env is dockerignored) — so
# pass build-only placeholders for this one command. They satisfy the gate,
# never reach the image's runtime env, and collectstatic itself touches no
# database and reads no secrets.
#
# FIELD_ENCRYPTION_KEY is generated here rather than written as a literal. It
# must be a valid 32-byte key, and the list of required settings has grown
# since this line was written — that drift is what made the image unbuildable
# until CI started building it. A generated key cannot go stale, and a random
# one that exists only inside this layer's shell cannot be mistaken for a real
# one or leak into the image.
RUN JWT_SECRET=build-time-collectstatic-placeholder-0123456789 \
    AUTHZ_MODE=enforce \
    SUPER_ADMIN_PASSWORD=build-time-placeholder \
    ALLOWED_HOSTS=build-placeholder.invalid \
    FIELD_ENCRYPTION_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
    python manage.py collectstatic --noinput

# Run as a non-root user. Nothing this process does needs root, and a
# container that starts as root turns any remote-code path into host-adjacent
# access instead of an application-level one. Created after collectstatic so
# the collected tree is owned by whoever will serve it, and the writable
# directories (evidence uploads, media, generated reports) are handed over
# explicitly — the rest of /app stays read-only to the runtime user.
RUN useradd --system --create-home --uid 10001 edify \
    && mkdir -p /app/uploads /app/media \
    && chown -R edify:edify /app/staticfiles /app/uploads /app/media
USER edify

# Railway injects $PORT at runtime. Default to 4000 for local/docker-compose.
ENV PORT=4000
EXPOSE 4000
# Apply migrations, optionally seed, then start the ASGI server (daphne for
# realtime SSE + the scheduler). Health probe hits GET /api/health.
# Liveness, not readiness. Docker marks the container unhealthy on failure and
# orchestrators restart it — so pointing this at a probe that checks the
# database means a database blip restarts every instance, which fixes nothing
# and removes the capacity that would have recovered. /api/health/ready is the
# one a load balancer should poll.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://localhost:${PORT:-4000}/api/health/live" || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
# Keep runtime PORT expansion while making the final process Daphne itself, so
# SIGTERM/SIGINT reach it directly during rolling deploys and shutdowns.
CMD ["sh", "-c", "exec daphne -b 0.0.0.0 -p \"${PORT:-4000}\" config.asgi:application"]
