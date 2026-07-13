"""
Base settings for the Edify API (Django + DRF).

Shared by dev and prod. Environment is read from os.environ so the same
.env schema the NestJS backend used keeps working (DATABASE_URL, JWT_SECRET,
CORS_ORIGINS, DEMO_LOGIN_PASSWORD, ENABLE_*, etc.). Prod-only gates live in
prod.py; permissive defaults for local dev live here.
"""

from __future__ import annotations

import os
from pathlib import Path


# ── Paths ────────────────────────────────────────────────────────────────────
# edify-api/ is the project root (manage.py sits next to this package).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

import environ

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
SECRET_KEY = os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me")

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
    "corsheaders.middleware.CorsMiddleware",  # before CommonMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

# Parse database URL including query parameters (like sslmode=require) using django-environ
_db_config = environ.Env.db_url_config(_db_url)

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
        }
    }
else:
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

# Custom auth: our JWT (access + rotating refresh). Not Django session login.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
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


# ── Edify domain settings (ported from NestJS env.validation.ts) ─────────────
IS_PRODUCTION = False  # overridden in prod.py
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

# Evidence storage — absolute, persistent path in production. Relative dev
# default is ephemeral (files lost on redeploy), which is fine locally.
EVIDENCE_STORAGE_DIR = os.environ.get("EVIDENCE_STORAGE_DIR") or str(
    BASE_DIR / "uploads" / "evidence"
)

# JWT / token TTLs (match NestJS defaults).
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_TTL_MINUTES = _as_int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES"), 15)
REFRESH_TOKEN_TTL_DAYS = _as_int(os.environ.get("REFRESH_TOKEN_TTL_DAYS"), 7)
PASSWORD_RESET_TOKEN_TTL_MINUTES = _as_int(
    os.environ.get("PASSWORD_RESET_TOKEN_TTL_MINUTES"), 45
)
INVITE_TOKEN_TTL_DAYS = _as_int(os.environ.get("INVITE_TOKEN_TTL_DAYS"), 7)

# Brute-force protection (login lockout).
AUTH_MAX_FAILED_LOGINS = _as_int(os.environ.get("AUTH_MAX_FAILED_LOGINS"), 10)
AUTH_LOCK_MINUTES = _as_int(os.environ.get("AUTH_LOCK_MINUTES"), 15)

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
RESEND_API_KEY = os.environ.get("RESEND_API_KEY") or ""
EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@edify.org")

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
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Edify Planning & Monitoring API",
    "DESCRIPTION": "School Directory is the source of truth. Salesforce-ready, not yet integrated.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
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
