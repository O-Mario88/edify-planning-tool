"""
Base settings for the Edify API (Django + DRF).

Shared by dev and prod. Environment is read from os.environ so the same
.env schema the NestJS backend used keeps working (DATABASE_URL, JWT_SECRET,
CORS_ORIGINS, DEMO_LOGIN_PASSWORD, ENABLE_*, etc.). Prod-only gates live in
prod.py; permissive defaults for local dev live here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────────────
# edify-api/ is the project root (manage.py sits next to this package).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

import environ
import dj_database_url

# Load .env file if it exists
environ.Env.read_env(env_file=str(BASE_DIR / ".env"))


# ── Helpers ──────────────────────────────────────────────────────────────────
def _truthy(value: str | None, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


# ── Core Django ──────────────────────────────────────────────────────────────
_development_secret = "dev-only-insecure-secret-change-me"
# DigitalOcean's Django convention uses SECRET_KEY. JWT_SECRET remains a
# supported explicit override for existing deployments; when only SECRET_KEY
# is configured, the JWT layer reuses the same strong secret as before.
SECRET_KEY = (
    os.environ.get("SECRET_KEY")
    or os.environ.get("JWT_SECRET")
    or _development_secret
)

# DEVELOPMENT default; prod.py overrides to False with a hard gate.
DEBUG = _truthy(os.environ.get("DEBUG"), fallback=True)
ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "*").split(",") if h.strip()
]

# The NestJS backend used String @id @default(cuid()) everywhere. We keep the
# same semantics with a CUID generator so seeded IDs and cross-references stay
# compatible. BigAutoField is used only for AuditLog.seq (hash-chain ordering).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The NestJS routes have NO trailing slash (/api/schools, /api/auth/login) and
# the frontend calls them that way. APPEND_SLASH only redirects GETs (POSTs to a
# slash-less URL 500), so disable it and define all URL patterns without slashes.
APPEND_SLASH = False

INSTALLED_APPS = [
    "daphne",  # ASGI server (for streaming SSE) — takes precedence over wsgi
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "django_filters",
    "corsheaders",
    "drf_spectacular",
    "django_apscheduler",
    # Local domain apps — added incrementally as modules land. They must be
    # declared before any app that references them in a FK.
    "apps.core",
    "apps.accounts",
    "apps.geography",
    "apps.schools",
    "apps.clusters",
    "apps.ssa",
    "apps.activity_catalogue",
    "apps.activities",
    "apps.budget",
    "apps.partners",
    "apps.assignment",
    "apps.filters",
    "apps.search",
    "apps.system_health",
    "apps.security",
    "apps.my_plan",
    "apps.hr",
    "apps.debriefs",
    "apps.targets",
    "apps.reports",
    "apps.flags",
    "apps.pl_review",
    "apps.command_center",
    "apps.admin_users",
    "apps.admin_ops",
    "apps.documents",
    "apps.staff_setup",
    "apps.evidence",
    "apps.projects",
    "apps.messaging",
    "apps.notifications",
    "apps.planning",
    "apps.fund_requests",
    "apps.daily_visit_batches",
    "apps.routes",
    "apps.core_schools",
    "apps.monthly_work_plan",
    "apps.professional_development",
    "apps.analytics",
    "apps.leadership",
    "apps.budget_intelligence",
    "apps.audit",
    "apps.realtime",
    "apps.help_center",
    "apps.frontend",
    # ... (registered as each module is built)
]

MIDDLEWARE = [
    # RequestContext first: opens a per-request contextvars scope (ip/ua/
    # correlationId) so the singleton audit logger stamps provenance without
    # threading it through every service. Mirrors NestJS requestContextMiddleware.
    "apps.core.middleware.RequestContextMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # Content-Security-Policy. Sits early so every response carries it,
    # including error pages — the ones most likely to be reached with a
    # crafted URL.
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Directly after SessionMiddleware so its response phase runs directly
    # before it: the session is touched, and SessionMiddleware then saves the
    # row and re-sends the cookie. This is what slides the idle window.
    "apps.core.middleware.SlidingSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Admin Support View: platform-wide visibility, zero business
    # authority. Enforced at the edge so a direct POST, an HTMX request or
    # a hand-edited URL is refused the same way a hidden button is.
    # Detection sits outside the read-only gate so it observes the response
    # that is actually sent -- a 500 raised by a view, and a route that
    # 404s, both reach it.
    "apps.admin_ops.detection.PlatformFailureDetectionMiddleware",
    "apps.admin_ops.middleware.AdminReadOnlyBusinessMiddleware",
    "apps.admin_ops.middleware.AdminSupportViewBannerMiddleware",
    # Mandatory-policy gate. After the admin middleware so an Admin's
    # read-only refusal is decided first, and before the view layer so a
    # direct URL, an HTMX fragment, an API call and an SSE stream are all
    # withheld -- a template redirect would only stop the person who clicked.
    "apps.documents.gate.PolicyGateMiddleware",
    # Generic error envelope — no stack traces / DB errors to clients; mirrors
    # the NestJS AllExceptionsFilter. Business 4xx keep their messages.
    "apps.core.middleware.AllExceptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.sidebar_counts",
                "apps.core.context_processors.sidebar_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ── Database ─────────────────────────────────────────────────────────────────
# Postgres (the NestJS backend ran on Postgres via Prisma). DATABASE_URL is the
# canonical config knob; fall back to discrete POSTGRES_* vars for docker-compose.
_db_url = os.environ.get(
    "DATABASE_URL",
    f"postgresql://{os.environ.get('POSTGRES_USER', 'edify')}:"
    f"{os.environ.get('POSTGRES_PASSWORD', 'edify')}@"
    f"{os.environ.get('DB_HOST', 'localhost')}:"
    f"{os.environ.get('DB_PORT', '5432')}/"
    f"{os.environ.get('POSTGRES_DB', 'edify_pm')}",
)
import sys

_is_testing = "test" in sys.argv or "pytest" in sys.modules
# Exposed as a setting so code outside this module can ask. Used by
# apps.core.blocking_io_guard, which raises under test and only logs in
# production -- a lock-hygiene problem must fail the build, but it must not
# turn a slow provider into a lost sign-in code for a real person.
IS_TESTING = _is_testing

# Platform-failure detection writes a System Incident for every server error,
# broken route, permission drift and SLO breach. The suite deliberately drives
# hundreds of refusals and error paths, so under test the edge is off and the
# detection functions are exercised directly instead. Production and dev keep
# it on.
ADMIN_OPS_DETECTION_ENABLED = not _is_testing

# Parse DigitalOcean/Railway DATABASE_URL values, including managed-Postgres
# query parameters such as sslmode=require. The settings below layer the
# application's bounded connection/query policy onto the parsed URL.
_db_config = dj_database_url.parse(_db_url)

# Clean up options that psycopg/libpq does not support
if "OPTIONS" in _db_config:
    # 'schema' is a Prisma query param; Django uses search_path in psycopg options
    _schema = _db_config["OPTIONS"].pop("schema", None)
    if _schema:
        _db_config["OPTIONS"]["options"] = f"-c search_path={_schema}"

DATABASES = {"default": _db_config}

# Apply default config parameters
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = 0 if _is_testing else 60

# ── Database timeouts ────────────────────────────────────────────────────────
# Postgres defaults all three of these to "wait forever", which is the wrong
# answer for every one of them:
#
#   statement_timeout   A query with a bad plan runs until someone notices.
#                       Meanwhile it holds a connection out of a small pool, so
#                       one runaway query on one page degrades every page.
#
#   lock_timeout        A request waiting on a row someone else has locked
#                       waits indefinitely. Two of those pointing at each other
#                       is a deadlock, which Postgres does detect and break —
#                       but plain contention is not a deadlock, and nothing
#                       breaks it. The request just never answers.
#
#   idle_in_transaction A worker that wedges between two statements holds its
#                       locks and its snapshot until the process dies. Autovacuum
#                       stops being able to clean up behind it, so the cost keeps
#                       growing for as long as it sits there.
#
# The numbers are ceilings on pathology, not budgets for normal work: nothing a
# person waits on should come close. Anything legitimately longer — an import,
# an annual reconciliation, the analytics build — belongs in a background job,
# which raises its own limits per session via DB_STATEMENT_TIMEOUT_MS rather
# than forcing the web tier to accommodate it.
#
# Under test the statement limit is loosened and the idle limit switched off:
# the scale harness builds fifteen thousand schools inside one transaction, and
# `TestCase` holds a transaction open across the whole of a slow test. Neither
# is the condition these are looking for.
_statement_timeout_ms = _as_int(
    os.environ.get("DB_STATEMENT_TIMEOUT_MS"), 300_000 if _is_testing else 30_000
)
_lock_timeout_ms = _as_int(os.environ.get("DB_LOCK_TIMEOUT_MS"), 10_000)
_idle_tx_timeout_ms = _as_int(
    os.environ.get("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS"), 0 if _is_testing else 60_000
)

_pg_options = [
    f"-c statement_timeout={_statement_timeout_ms}",
    f"-c lock_timeout={_lock_timeout_ms}",
    f"-c idle_in_transaction_session_timeout={_idle_tx_timeout_ms}",
]
_existing_options = DATABASES["default"].setdefault("OPTIONS", {}).get("options", "")
# Appended, never assigned: a DATABASE_URL carrying ?schema= already put a
# search_path in here, and overwriting it would silently point the whole
# application at the wrong schema.
DATABASES["default"]["OPTIONS"]["options"] = " ".join(
    filter(None, [_existing_options, *_pg_options])
)

# How long to wait for the TCP connect and startup handshake. Without it libpq
# waits indefinitely, so a database host that accepts the connection but never
# completes the handshake hangs the worker outright — and CONN_HEALTH_CHECKS
# means a reconnect can be attempted at the start of any request, not just at
# boot. The statement and lock timeouts above only bound queries on a
# connection that already exists.
DATABASES["default"]["OPTIONS"].setdefault(
    "connect_timeout", _as_int(os.environ.get("DB_CONNECT_TIMEOUT_S"), 5)
)

# ── Caching (Redis-backed with dynamic fallback to LocMemCache) ──────────────
_redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_use_redis = False
try:
    import redis

    _conn = redis.Redis.from_url(_redis_url, socket_timeout=1)
    _conn.ping()
    _use_redis = True
except Exception:
    _use_redis = False

if _use_redis:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_url,
            # The 1s bound on the probe above only covers the probe. Without
            # these, every cache.get/set afterwards runs with redis-py's
            # defaults — no timeout at all — so a Redis that degrades *after*
            # boot blocks the worker on a cache read indefinitely.
            "OPTIONS": {
                "socket_connect_timeout": 2,
                "socket_timeout": 2,
            },
        }
    }
else:
    # Not interchangeable with Redis: LocMemCache is per-process, so each
    # worker gets a private cache and anything written for another worker to
    # read is simply lost. Worth a loud line in the log — a deploy that took
    # this branch because Redis happened to be unreachable for one second at
    # boot otherwise looks completely healthy.
    if not _is_testing:
        logging.getLogger("edify.settings").warning(
            "Redis unreachable at %s — falling back to per-process LocMemCache. "
            "Cache state is NOT shared between workers until this is fixed.",
            _redis_url,
        )
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "edify-pm-locmem-cache",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ── Auth (Django built-in user model overridden by apps.accounts) ────────────
AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    # The NestJS backend hashed with bcryptjs (cost 12). Django can verify
    # bcrypt hashes natively; we prefer bcrypt for parity / migration.
    "django.contrib.auth.hashers.BCryptPasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Custom auth: our JWT (access + rotating refresh) for the DRF API, Django
# session login for the web app -- both, plus Django's own /admin/login/,
# go through this ONE backend so AuthenticationLockoutService's policy is
# enforced identically everywhere (Issue 3 of the audit).
AUTHENTICATION_BACKENDS = [
    "apps.accounts.auth_backend.LockoutEnforcingModelBackend",
]


# ── Internationalisation ─────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"  # the program operates in Uganda
USE_I18N = True
USE_TZ = True


# ── Static / media ───────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# The staticfiles backend that serves production traffic. Named here, rather
# than written as a literal in prod.py, because the Docker image collects static
# at build time under config.settings.collectstatic — and a manifest built by a
# different backend than the one serving requests produces 500s on every asset.
# One constant, two importers, no way for them to drift apart.
STATICFILES_STORAGE_BACKEND = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# All restricted uploads use the named private backend.  Keeping it distinct
# from ``default`` prevents a future public-media change from exposing
# evidence, organisational documents, or professional-development records.
USE_SPACES_STORAGE = False
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": MEDIA_ROOT, "base_url": MEDIA_URL},
    },
    "private_uploads": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {
            "location": BASE_DIR / "uploads",
            "base_url": None,
        },
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


# ── Edify domain settings (ported from NestJS env.validation.ts) ─────────────
IS_PRODUCTION = False  # overridden in prod.py

# Environment identity for the database stamp guard (apps.system_health.
# environment_guard): which environment THIS PROCESS believes it is. The
# database carries its own stamp; a mismatch (prod server on a local dump,
# or a local shell pointed at the production DATABASE_URL) refuses to run.
ENVIRONMENT = os.environ.get("ENVIRONMENT", "local").strip().lower()
NODE_ENV = os.environ.get("NODE_ENV", "development")
PORT = _as_int(os.environ.get("PORT"), 4000)

# Country Directors can open row-level school/cluster/activity records (the
# role spec gives CD the school and cluster directories + detail views).
# Set env ALLOW_CD_OPERATIONAL_PLANNING=false to restrict CD to aggregates.
ALLOW_CD_OPERATIONAL_PLANNING = _truthy(
    os.environ.get("ALLOW_CD_OPERATIONAL_PLANNING"), fallback=True
)

# Validation leniency: the NestJS ValidationPipe used whitelist:true WITHOUT
# forbidNonWhitelisted — extra JSON fields are silently dropped, never 400. We
# replicate that with serializers that ignore unknown input (see core/serializers).
ENABLE_MOCK_DATA = _truthy(os.environ.get("ENABLE_MOCK_DATA"), fallback=False)
ENABLE_DEV_ENDPOINTS = _truthy(os.environ.get("ENABLE_DEV_ENDPOINTS"), fallback=False)
ENABLE_SALESFORCE_INTEGRATION = _truthy(
    os.environ.get("ENABLE_SALESFORCE_INTEGRATION"), fallback=False
)
ENABLE_BACKGROUND_JOBS = _truthy(
    os.environ.get("ENABLE_BACKGROUND_JOBS"), fallback=False
)

# Local-development data import flags. Both default OFF; a developer must opt in
# to seed demo data or run the import_*_local commands. Hard-blocked in prod.py.
ENABLE_DEV_SEED = _truthy(os.environ.get("ENABLE_DEV_SEED"), fallback=False)
ENABLE_DEV_IMPORTS = _truthy(os.environ.get("ENABLE_DEV_IMPORTS"), fallback=False)
ALLOW_LOCAL_TEST_UPLOADS = _truthy(
    os.environ.get("ALLOW_LOCAL_TEST_UPLOADS"), fallback=True
)  # true in dev; forced false in prod
ALLOW_PRODUCTION_IMPORTS = _truthy(
    os.environ.get("ALLOW_PRODUCTION_IMPORTS"), fallback=False
)  # authorized real-data upload only

# Object-level authorization: 'shadow' logs would-be denials; 'enforce' blocks.
# Prod must run 'enforce' (gated in prod.py).
AUTHZ_MODE = os.environ.get("AUTHZ_MODE", "shadow")

# Partner identity bridge: when a partner user has no Partner.userId link, pin
# them to the first active partner (demo convenience). OFF by default — a real
# partner must be linked to a Partner org via Partner.userId. Enable only for
# local dev with the demo seed.
PARTNER_ROLE_BRIDGE = _truthy(os.environ.get("PARTNER_ROLE_BRIDGE"), fallback=False)

REDIS_URL = os.environ.get("REDIS_URL") or None

# Legacy local directory settings remain available to maintenance tooling.
# Runtime upload code uses STORAGES["private_uploads"] instead.
EVIDENCE_STORAGE_DIR = os.environ.get("EVIDENCE_STORAGE_DIR") or str(
    BASE_DIR / "uploads" / "evidence"
)

# Organisational documents live in their own store, not beside activity
# evidence: the two have different retention, different audiences and a
# different size ceiling.
DOCUMENT_STORAGE_DIR = os.environ.get("DOCUMENT_STORAGE_DIR") or str(
    BASE_DIR / "uploads" / "documents"
)

# Evidence malware scanning (apps.evidence.services._scan_upload) — off by
# default (EvidenceRecord.scan_status="skipped") until CLAMAV_HOST is set to
# point at a reachable ClamAV daemon (clamd). Never required for the upload
# pipeline to function; a scan failure/timeout/misconfiguration degrades to
# "skipped", the same as leaving it unset.
CLAMAV_HOST = os.environ.get("CLAMAV_HOST") or None
CLAMAV_PORT = _as_int(os.environ.get("CLAMAV_PORT"), 3310)
CLAMAV_TIMEOUT_SECONDS = _as_int(os.environ.get("CLAMAV_TIMEOUT_SECONDS"), 10)

# JWT / token TTLs (match NestJS defaults).
JWT_SECRET = os.environ.get("JWT_SECRET") or SECRET_KEY
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_TTL_MINUTES = _as_int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES"), 15)
REFRESH_TOKEN_TTL_DAYS = _as_int(os.environ.get("REFRESH_TOKEN_TTL_DAYS"), 7)
PASSWORD_RESET_TOKEN_TTL_MINUTES = _as_int(
    os.environ.get("PASSWORD_RESET_TOKEN_TTL_MINUTES"), 45
)
INVITE_TOKEN_TTL_DAYS = _as_int(os.environ.get("INVITE_TOKEN_TTL_DAYS"), 7)

# ── Brute-force protection (login lockout) — apps.accounts.lockout_service
# .AuthenticationLockoutService is the ONLY place these are read. Every
# login path (web session, DRF API, Django admin) enforces this SAME policy
# via apps.accounts.auth_backend.LockoutEnforcingModelBackend. See
# docs/auth-lockout-policy.md.
AUTH_MAX_FAILED_LOGINS = _as_int(os.environ.get("AUTH_MAX_FAILED_LOGINS"), 10)
# AUTH_LOCK_MINUTES is a deprecated alias for AUTH_LOCKOUT_DURATION_MINUTES —
# kept so any already-configured deployment env var keeps working.
AUTH_LOCK_MINUTES = _as_int(os.environ.get("AUTH_LOCK_MINUTES"), 15)
AUTH_LOCKOUT_DURATION_MINUTES = _as_int(
    os.environ.get("AUTH_LOCKOUT_DURATION_MINUTES"), AUTH_LOCK_MINUTES
)
# How many separate temporary-lockout CYCLES (not failed attempts) within
# the escalation window before the account requires an admin to unlock it,
# instead of auto-expiring again. The "safer enterprise default": nobody is
# ever permanently locked from a single burst of failed attempts, but
# repeated lockout cycles (a sustained attack, or a compromised credential
# being hammered) escalate to a human.
AUTH_LOCKOUT_ESCALATION_COUNT = _as_int(
    os.environ.get("AUTH_LOCKOUT_ESCALATION_COUNT"), 3
)
AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS = _as_int(
    os.environ.get("AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS"), 24
)
AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION = _truthy(
    os.environ.get("AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION"), fallback=True
)
# A failed-attempt streak older than this is stale and doesn't count toward
# the threshold — matches the "successful login resets the counter" spirit
# for someone who simply stopped trying rather than got locked out.
AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES = _as_int(
    os.environ.get("AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES"), 30
)

# Rate limits.
RATE_LIMIT_LOGIN_PER_MIN = _as_int(os.environ.get("RATE_LIMIT_LOGIN_PER_MIN"), 10)
RATE_LIMIT_FORGOT_PER_10MIN = _as_int(os.environ.get("RATE_LIMIT_FORGOT_PER_10MIN"), 4)

# Demo / seed credentials (shared contract with the frontend bridge).
DEMO_LOGIN_PASSWORD = os.environ.get("DEMO_LOGIN_PASSWORD") or "edify"
SUPER_ADMIN_EMAIL = os.environ.get("SUPER_ADMIN_EMAIL", "domario@edify.org")
SUPER_ADMIN_PASSWORD = os.environ.get("SUPER_ADMIN_PASSWORD") or ""

# App URLs (for email links + CORS).
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:3000")
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]

# Field-level encryption (AES-256-GCM) for Restricted/Highly-Restricted values.
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY") or ""

# Email (two-mode mailer: dev console vs prod Resend HTTP API).
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "console")  # console|resend

# Backstop for anything still reaching django.core.mail. EMAIL_BACKEND defaults
# to SMTP on localhost and EMAIL_TIMEOUT defaults to None, which means a mail
# host that accepts the connection and then stops responding blocks the worker
# for as long as the socket stays open. Product email goes through
# apps.core.email.MailerService, which is bounded at 15s; this bounds the rest.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT_SECONDS", "10"))
RESEND_API_KEY = os.environ.get("RESEND_API_KEY") or ""
EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@edify.org")

# Whether the console mailer may log the message body. apps.core.email has read
# this since the log-leak fix but nothing ever defined it, so the opt-in was
# unreachable and a developer had no way to see an invitation link or a sign-in
# code locally. Off by default, and apps.core.email refuses it in production
# regardless — the body carries live tokens, which outlive the email in a log.
EMAIL_LOG_BODIES = _truthy(os.environ.get("EMAIL_LOG_BODIES"), fallback=False)

# SMS (two-mode sender: dev console vs Africa's Talking). One of the two
# channels a two-factor code can arrive on; apps.core.sms reads the environment
# directly so tests can swap the provider, and these are mirrored here so the
# posture report and the enrolment page can see what is configured.
SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "console")  # console|africastalking
SMS_SENDER_ID = os.environ.get("SMS_SENDER_ID", "")
# Whether the dev sender may log the message body. Off by default: the body
# carries a live sign-in code, which outlives the SMS in a log stream.
SMS_LOG_BODIES = _truthy(os.environ.get("SMS_LOG_BODIES"), fallback=False)

# Two-factor authentication. Enrolment is per user (User.mfa_enabled, set from
# the settings page); this turns it on for every account at once, for an
# organisation that wants it mandatory rather than optional.
MFA_REQUIRED_FOR_ALL = _truthy(os.environ.get("MFA_REQUIRED_FOR_ALL"), fallback=False)

# Audit hash-chain seed for the genesis row. Override in deployments for a
# trusted anchor.
AUDIT_GENESIS_HASH = os.environ.get("AUDIT_GENESIS_HASH", "0" * 64)


# ── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    # Our custom pagination emits {data, page, pageSize, total, totalPages} to
    # match the NestJS Paginated<T> envelope consumed by surfaces.ts.
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.EdifyPagination",
    "PAGE_SIZE": 25,
    # Lenient parsing: extra fields dropped, never rejected (mirrors NestJS
    # ValidationPipe whitelist:true / forbidNonWhitelisted:false).
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # JWT bearer for API clients (the primary path). Session auth supports
        # the Django admin + same-origin cookie browser calls after the
        # frontend rework.
        "apps.accounts.jwt.JwtAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    # Throttling is applied PER-VIEW (auth/login, auth/forgot-password) via
    # `throttle_classes`, NOT globally — the rate limiter is only for those
    # brute-force-sensitive endpoints.
    "EXCEPTION_HANDLER": "apps.core.exceptions.edify_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "apps.core.openapi.EdifyAutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Edify Planning & Monitoring API",
    "DESCRIPTION": "School Directory is the source of truth. Salesforce-ready, not yet integrated.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "PREPROCESSING_HOOKS": [
        "apps.core.openapi.normalize_api_prefix_paths",
    ],
}

# django-apscheduler — runs the 4 background jobs in-process (single-process
# parity with the NestJS @Cron workers). Each job early-returns unless
# ENABLE_BACKGROUND_JOBS is true.
APSCHEDULER_DATETIME_FORMAT = "N j, Y, f:s a"
APSCHEDULER_RUN_NOW_TIMEOUT = 25  # seconds


# ── Default primary key for new models ───────────────────────────────────────
# Most tables use CUID string PKs (see apps.core.models). AuditLog uses a
# BigAutoField seq for hash-chain ordering. Models opt in via their Meta.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ── Session lifetime ─────────────────────────────────────────────────────────
# Thirty minutes of INACTIVITY, not thirty minutes total. The window slides
# forward while someone is working and only starts counting down when they
# stop: a user is never signed out mid-task, and a laptop left open in a shared
# office stops being a way in after half an hour.
#
# SESSION_SAVE_EVERY_REQUEST stays False on purpose. It is the obvious way to
# get the sliding window and it costs an UPDATE on one hot session row for
# every authenticated request in the product. apps.core.middleware.
# SlidingSessionMiddleware does the same job on a throttle — see its docstring
# for the bounded precision that buys.
SESSION_COOKIE_AGE = _as_int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS"), 30 * 60)
SESSION_SAVE_EVERY_REQUEST = False

# Sessions ride on the cache when it is Redis, and on the database otherwise.
# `cached_db` rather than plain `cache`: a cache eviction or a Redis restart
# would otherwise sign every user out at once, and the database copy makes that
# a slow read rather than a mass logout.
#
# The condition is _use_redis — whether a Redis connection actually answered —
# and not _redis_url, which has a default and is therefore always truthy. With
# the URL as the test this read `cached_db` even when the cache had fallen back
# to LocMemCache, which is per-process: each worker would have kept its own
# copy of every session, and a session ended or changed on one worker would
# have stayed live in the others' caches until their entries lapsed.
SESSION_ENGINE = (
    "django.contrib.sessions.backends.cached_db"
    if _use_redis
    else "django.contrib.sessions.backends.db"
)


# ── Security defaults (overridden/tightened in prod.py) ──────────────────────
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"

# CORS — allowlist from CORS_ORIGINS; reflective only outside prod.
CORS_ALLOWED_ORIGINS = CORS_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["x-correlation-id"]


# ── Logging ──────────────────────────────────────────────────────────────────
# There was no LOGGING block at all, so the project ran on Django's defaults
# and every logged value went out exactly as supplied. Records here routinely
# carry outside data — a school id, an activity reference, an exception message
# quoting whatever tripped it — and a newline in any of those splits one event
# into two, the second of which can be spelled to look like a genuine entry.
# The filter escapes line breaks once, on the way out, rather than asking
# several hundred call sites to remember.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "single_line": {
            "()": "apps.core.logging_filters.SingleLineFilter",
        },
    },
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["single_line"],
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        # Django's own request logger is noisy at INFO in development and
        # carries the same untrusted path data, so it uses the same handler.
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
