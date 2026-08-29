# ── edify-api (Django + DRF) ─────────────────────────────────────────────────
# Multi-stage: install deps, run a lean runtime image.

FROM python:3.13-slim AS build
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
# Build deps for psycopg (compiles against libpq) + Pillow.
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements/ ./requirements/
RUN pip install --prefix=/install -r requirements/prod.txt \
    && pip install --prefix=/install --upgrade "setuptools>=78.1.1"

FROM python:3.13-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    PORT=4000
# Runtime deps: libpq (psycopg), libexpat (ASGI), and headless LibreOffice for
# the evidence DOCX→PDF rendition pipeline (optional; skipped if absent).
#
# The three OpenSSL packages are named explicitly, and not because anything
# here links against them directly — the base image already carries them. They
# are listed so `apt-get install` takes the newest version the archive has
# rather than whatever the base image tag happened to freeze.
#
# DEP-08 is why. CVE-2026-14456 (OpenSSL denial of service through unbounded
# memory growth in the QUIC server path, rated High) landed in the scanner's
# database while `python:3.13-slim` still shipped 3.5.6-1~deb13u2, and Debian
# had already published the fix as 3.5.7-1~deb13u2. Nothing in this repository
# had changed; the image simply carried a vulnerability that a rebuild could
# clear. Without this line a rebuild would keep shipping it, because the
# earlier `apt-get install` list gave apt no reason to touch them.
#
# This is deliberately narrow rather than `apt-get upgrade`: upgrading
# everything in the runtime image changes more than the finding asks for, on a
# production image nobody can re-test between build and deploy.
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    libpq5 libexpat1 curl \
    libssl3t64 openssl openssl-provider-legacy \
    libreoffice --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# Site-packages from the build stage.
COPY --from=build /install /usr/local
# Remove pip from the RUNTIME image. Two reasons, and the security one is not
# the headline:
#
# 1. Nothing here needs it. Dependencies are installed in the build stage above
#    and copied in; docker-entrypoint.sh runs migrate, optionally seed, the
#    preflight, and then daphne. A container that cannot install packages is a
#    materially worse foothold than one that can.
#
# 2. It is the honest answer to the container scan. Trivy kept reporting
#    setuptools 70.3.0 (CVE-2025-47273) and msgpack 1.1.2
#    (GHSA-6v7p-g79w-8964) against this image, and neither is an application
#    dependency: pip vendors its own copies and declares them in
#    `pip/_vendor/vendor.txt`, which the scanner reads. Upgrading our packages
#    could never clear those lines — the application's own site-packages was
#    already clean and the scan stayed red. The fix is to remove the pip tree
#    that carries them, not to add an ignore rule for a finding that would then
#    go unread.
#
# The application's own setuptools is upgraded first, in case any dependency
# imports it at runtime, and its superseded metadata is pruned — a COPY merges
# directories rather than replacing them, so the old dist-info would otherwise
# survive beside the new one and keep being reported.
#
# The removal is then asserted against the filesystem rather than with
# `command -v pip`: this shell hashed `pip` when it ran the install on the
# first line, so `command -v` keeps returning the old path after the file is
# gone — a check that answers from cache instead of from the image.
RUN pip install --no-cache-dir --upgrade "setuptools>=78.1.1" \
    && find /usr/local/lib/python3.13/site-packages -maxdepth 1 \
        -name 'setuptools-*.dist-info' -type d \
        -not -name "setuptools-$(python -c 'import setuptools; print(setuptools.__version__)').dist-info" \
        -exec rm -rf {} + \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && test ! -e /usr/local/lib/python3.13/site-packages/pip \
    && test ! -e /usr/local/bin/pip \
    && python -c "import setuptools; print('setuptools', setuptools.__version__)"
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
# Apply migrations, optionally seed, then start the ASGI server. Gunicorn owns
# three Uvicorn ASGI workers by default: one process was the measured staging
# throughput ceiling, and two still left the one-vCPU service waiting on
# database round trips under the 12-concurrent-request release gate. Three is
# the measured in-place ceiling for the 2 GiB web instances; each warm worker
# uses roughly 470-490 MiB RSS. ASGI and the shared realtime bus preserve SSE.
# Health probe hits GET /api/health.
# Liveness, not readiness. Docker marks the container unhealthy on failure and
# orchestrators restart it — so pointing this at a probe that checks the
# database means a database blip restarts every instance, which fixes nothing
# and removes the capacity that would have recovered. /api/health/ready is the
# one a load balancer should poll.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS "http://localhost:${PORT:-4000}/api/health/live" || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
# Keep runtime expansion while making Gunicorn PID 1, so rolling-deploy signals
# reach the supervisor directly. WEB_CONCURRENCY remains an explicit escape
# hatch for a differently sized instance; the production-equivalent default is
# the three-process shape verified by the release load gate.
CMD ["sh", "-c", "exec gunicorn --worker-tmp-dir /dev/shm --bind \"0.0.0.0:${PORT:-4000}\" --worker-class uvicorn.workers.UvicornWorker --workers \"${WEB_CONCURRENCY:-3}\" --timeout \"${WEB_TIMEOUT_SECONDS:-60}\" --graceful-timeout \"${WEB_GRACEFUL_TIMEOUT_SECONDS:-30}\" --access-logfile - --error-logfile - config.asgi:application"]
