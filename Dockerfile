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
# The runtime base currently carries an old setuptools distribution. Merely
# copying the pinned replacement from /install would leave the old, differently
# named dist-info directory behind for scanners (and tooling) to discover.
# Remove it first; requirements/base.txt then supplies the patched runtime copy.
RUN python -m pip uninstall -y setuptools
# Site-packages from the build stage.
COPY --from=build /install /usr/local
# Application source.
COPY . .
# Docker preserves permissions from a local build context. Normalize read and
# directory traversal bits so the runtime user can import the application even
# when a developer's working tree has owner-only modes. Capital X preserves
# executability only for directories and files already marked executable.
RUN chmod -R a+rX /app
# Collect static (DRF spectacular + admin assets). Fail the build if static
# collection errors — a silent failure here means broken CSS/JS in production.
#
# This runs under config.settings.collectstatic, NOT config.settings.prod.
# prod.py fails closed at import unless its entire required set of secrets and
# Spaces credentials is present, and none of that exists at build time. The
# previous approach — a hand-maintained list of placeholder env vars on this
# RUN line — fell out of sync with that required set twice and made the image
# unbuildable both times.
#
# collectstatic opens no socket, reads no secret, and touches no database, so
# the production gate was never protecting anything here. See the module
# docstring in config/settings/collectstatic.py. It shares the staticfiles
# backend with prod.py via a single constant in base.py, so the manifest built
# here is the manifest production serves.
RUN DJANGO_SETTINGS_MODULE=config.settings.collectstatic \
    python manage.py collectstatic --noinput

# Provenance for the artifact, written after the manifest exists so the hash
# describes the bundle this image will actually serve. The commit and release
# arguments are optional on purpose: DigitalOcean App Platform builds this
# Dockerfile without forwarding a commit SHA, and a provenance file that
# refused to exist without one would be missing in the only environment whose
# provenance is in question. The manifest hash needs no cooperation from the
# builder and is the fact that settles "is production serving the bundle I
# built?".
ARG GIT_COMMIT=""
ARG RELEASE=""
# App Platform's Dockerfile builder is Kaniko. Use a regular script rather
# than Docker/BuildKit heredoc syntax so the file is created identically by
# local Docker, CI, and DigitalOcean.
RUN python -m scripts.write_build_info

# Run as a non-root user. Nothing this process does needs root, and a
# container that starts as root turns any remote-code path into host-adjacent
# access instead of an application-level one. Created after collectstatic so
# the collected tree is owned by whoever will serve it, and the writable
# directories (evidence uploads, media, generated reports) are handed over
# explicitly — the rest of /app stays read-only to the runtime user.
RUN useradd --system --create-home --uid 10001 edify \
    && mkdir -p /app/uploads /app/media \
    && chown -R edify:edify /app/staticfiles /app/uploads /app/media \
    && chmod 0444 /app/build-info.json
USER edify

# App Platform injects $PORT at runtime. Default to 4000 for local/docker-compose.
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
