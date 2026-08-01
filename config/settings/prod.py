"""
Production settings — fail closed.

Ports the NestJS env.validation.ts production safety rails: boot refuses to
start unless mock data, dev endpoints, and shadow authorization are all off,
the JWT secret is strong, and private uploads use durable object storage.
"""

import os
import re
import sys
from urllib.parse import urlsplit

from botocore.config import Config

from .base import *  # noqa: F401,F403
from .base import _as_int, _truthy
from apps.core.crypto import load_field_encryption_key

IS_PRODUCTION = True
NODE_ENV = "production"
DEBUG = False
# Under prod settings the process identity IS production — never trust the
# env var to say otherwise (a missing ENVIRONMENT must not weaken the stamp
# guard on a production host).
ENVIRONMENT = "production"

# ── Private DigitalOcean Spaces storage ─────────────────────────────────────
USE_SPACES_STORAGE = True
SPACES_BUCKET_NAME = os.environ.get("SPACES_BUCKET_NAME", "").strip()
SPACES_REGION = os.environ.get("SPACES_REGION", "").strip().lower()
SPACES_ACCESS_KEY_ID = os.environ.get("SPACES_ACCESS_KEY_ID", "").strip()
SPACES_SECRET_ACCESS_KEY = os.environ.get("SPACES_SECRET_ACCESS_KEY", "").strip()
SPACES_ENDPOINT_URL = os.environ.get("SPACES_ENDPOINT_URL", "").strip() or (
    f"https://{SPACES_REGION}.digitaloceanspaces.com" if SPACES_REGION else ""
)
SPACES_PREFIX = os.environ.get("SPACES_PREFIX", "edify").strip().strip("/")
SPACES_CONNECT_TIMEOUT_SECONDS = _as_int(
    os.environ.get("SPACES_CONNECT_TIMEOUT_SECONDS"), 5
)
SPACES_READ_TIMEOUT_SECONDS = _as_int(os.environ.get("SPACES_READ_TIMEOUT_SECONDS"), 30)
SPACES_MAX_ATTEMPTS = _as_int(os.environ.get("SPACES_MAX_ATTEMPTS"), 3)
SPACES_MAX_POOL_CONNECTIONS = _as_int(os.environ.get("SPACES_MAX_POOL_CONNECTIONS"), 20)

# ── Production safety gates (collect ALL violations, then fail) ──────────────
# Mirrors NestJS: "Production environment is not safe:\n<issues>".
_issues: list[str] = []

if ENABLE_MOCK_DATA:
    _issues.append("ENABLE_MOCK_DATA must be false in production.")
if ENABLE_DEV_ENDPOINTS:
    _issues.append("ENABLE_DEV_ENDPOINTS must be false in production.")
if ENABLE_DEV_SEED:
    _issues.append("ENABLE_DEV_SEED must be false in production (no demo seeding).")
if ENABLE_DEV_IMPORTS:
    _issues.append(
        "ENABLE_DEV_IMPORTS must be false in production (no local test imports)."
    )
if PARTNER_ROLE_BRIDGE:
    _issues.append(
        "PARTNER_ROLE_BRIDGE must be false in production (real Partner.userId links required)."
    )
# The documented contract (.env.example, DEPLOY.md) is 50+ characters, which
# `openssl rand -hex 32` satisfies at 64. SECRET_KEY signs sessions and CSRF
# tokens; JWT_SECRET signs auth tokens. They are the same value unless BOTH env
# vars are set, so check every distinct secret actually in use — checking only
# JWT_SECRET let a weak SECRET_KEY through whenever the two were configured
# separately.
_MIN_SECRET_LENGTH = 50
_PLACEHOLDER_MARKERS = ("change-me", "dev-only")
if JWT_SECRET == SECRET_KEY:
    _secrets_in_use = (("SECRET_KEY/JWT_SECRET", SECRET_KEY),)
else:
    _secrets_in_use = (("SECRET_KEY", SECRET_KEY), ("JWT_SECRET", JWT_SECRET))
for _name, _secret in _secrets_in_use:
    if any(marker in _secret for marker in _PLACEHOLDER_MARKERS):
        _issues.append(
            f"{_name} must not contain a development placeholder "
            '("change-me" / "dev-only").'
        )
    elif len(_secret) < _MIN_SECRET_LENGTH:
        _issues.append(
            f"{_name} must be at least {_MIN_SECRET_LENGTH} characters "
            f"(got {len(_secret)}); generate one with: openssl rand -hex 32"
        )
if AUTHZ_MODE != "enforce":
    _issues.append(
        'AUTHZ_MODE must be "enforce" in production '
        "(object-level authorization cannot run in shadow)."
    )
for _name, _value in (
    ("SPACES_BUCKET_NAME", SPACES_BUCKET_NAME),
    ("SPACES_REGION", SPACES_REGION),
    ("SPACES_ACCESS_KEY_ID", SPACES_ACCESS_KEY_ID),
    ("SPACES_SECRET_ACCESS_KEY", SPACES_SECRET_ACCESS_KEY),
    ("SPACES_ENDPOINT_URL", SPACES_ENDPOINT_URL),
):
    if not _value:
        _issues.append(f"{_name} is required for durable private uploads.")
if SPACES_REGION and not re.fullmatch(r"[a-z0-9-]+", SPACES_REGION):
    _issues.append("SPACES_REGION contains invalid characters.")
if (
    not SPACES_PREFIX
    or SPACES_PREFIX in {".", ".."}
    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", SPACES_PREFIX)
):
    _issues.append(
        "SPACES_PREFIX must be one safe path segment (letters, numbers, dot, dash, underscore)."
    )
if SPACES_ENDPOINT_URL:
    _spaces_endpoint = urlsplit(SPACES_ENDPOINT_URL)
    if (
        _spaces_endpoint.scheme != "https"
        or not _spaces_endpoint.hostname
        or _spaces_endpoint.path not in ("", "/")
        or _spaces_endpoint.query
        or _spaces_endpoint.fragment
    ):
        _issues.append(
            "SPACES_ENDPOINT_URL must be an HTTPS origin without a path or query."
        )
    elif SPACES_REGION and _spaces_endpoint.hostname != (
        f"{SPACES_REGION}.digitaloceanspaces.com"
    ):
        _issues.append(
            "SPACES_ENDPOINT_URL hostname must match SPACES_REGION "
            f"({SPACES_REGION}.digitaloceanspaces.com)."
        )
for _name, _value, _minimum, _maximum in (
    ("SPACES_CONNECT_TIMEOUT_SECONDS", SPACES_CONNECT_TIMEOUT_SECONDS, 1, 60),
    ("SPACES_READ_TIMEOUT_SECONDS", SPACES_READ_TIMEOUT_SECONDS, 1, 300),
    ("SPACES_MAX_ATTEMPTS", SPACES_MAX_ATTEMPTS, 1, 10),
    ("SPACES_MAX_POOL_CONNECTIONS", SPACES_MAX_POOL_CONNECTIONS, 1, 100),
):
    if not _minimum <= _value <= _maximum:
        _issues.append(f"{_name} must be between {_minimum} and {_maximum}.")
if not SUPER_ADMIN_PASSWORD:
    _issues.append("SUPER_ADMIN_PASSWORD must be set (super-admin login).")
try:
    load_field_encryption_key(FIELD_ENCRYPTION_KEY)
except RuntimeError as exc:
    _issues.append(f"FIELD_ENCRYPTION_KEY is required and must be valid: {exc}")

if _issues:
    sys.stderr.write(
        "Production environment is not safe:\n" + "\n".join(_issues) + "\n"
    )
    raise SystemExit(1)

# ── Hardened security posture ────────────────────────────────────────────────
if "*" in ALLOWED_HOSTS:
    ALLOWED_HOSTS = []


def _platform_hostname(value: str | None) -> str:
    """Return a hostname from either ``host`` or ``https://host/path``."""

    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    return parsed.hostname or ""


# App Platform's APP_DOMAIN bindable value is assigned to
# DIGITALOCEAN_APP_DOMAIN in the service configuration. Railway support
# remains for existing deployments, while explicit ALLOWED_HOSTS is accepted
# for custom domains on either platform.
_platform_domains = {
    _platform_hostname(
        os.environ.get("DIGITALOCEAN_APP_DOMAIN") or os.environ.get("APP_DOMAIN")
    ),
    _platform_hostname(os.environ.get("RAILWAY_PUBLIC_DOMAIN")),
}
for _platform_domain in sorted(_platform_domains - {""}):
    if _platform_domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_platform_domain)

# Refuse to boot with no real host configured. This check must run BEFORE
# the loopback hosts are appended below — with them already in the list, an
# unset ALLOWED_HOSTS would boot "healthy" (localhost health probes pass)
# while every real request 400s with DisallowedHost.
if not ALLOWED_HOSTS:
    _issues.append(
        "ALLOWED_HOSTS must be set to explicit hosts in production "
        "(or DIGITALOCEAN_APP_DOMAIN/RAILWAY_PUBLIC_DOMAIN must be present)."
    )
    sys.stderr.write(
        "Production environment is not safe:\n" + "\n".join(_issues) + "\n"
    )
    raise SystemExit(1)

# Allow local loopback addresses for container health probes
# nosec B104 - this is the ALLOWED_HOSTS Host-header allowlist, not a
# socket bind address. The bind address is set by the process manager.
for host in ["localhost", "127.0.0.1", "0.0.0.0"]:  # nosec B104
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

SECURE_SSL_REDIRECT = _truthy(os.environ.get("SECURE_SSL_REDIRECT"), fallback=True)
# The platform's health probe reaches the container over plain HTTP, with no
# X-Forwarded-Proto for SECURE_PROXY_SSL_HEADER to read. Redirecting it to
# https answers 301, which is not a 2xx, so the instance never becomes ready.
# Exempting the probe paths costs nothing: DigitalOcean's router already
# terminates TLS for every route a user can reach, and these two return a JSON
# literal and a SELECT 1. Pairs with HealthProbeHostMiddleware, which handles
# the other half — the pod-IP Host header.
SECURE_REDIRECT_EXEMPT = [r"^api/health(/|$)"]
SESSION_COOKIE_SECURE = _truthy(os.environ.get("SESSION_COOKIE_SECURE"), fallback=True)
CSRF_COOKIE_SECURE = _truthy(os.environ.get("CSRF_COOKIE_SECURE"), fallback=True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"

# Django requires trusted origins (including scheme) for unsafe HTTPS
# requests. The App Platform hostname is trusted automatically; custom domains
# can be supplied as a comma-separated CSRF_TRUSTED_ORIGINS environment value.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
_digitalocean_domain = _platform_hostname(
    os.environ.get("DIGITALOCEAN_APP_DOMAIN") or os.environ.get("APP_DOMAIN")
)
if _digitalocean_domain:
    _digitalocean_origin = f"https://{_digitalocean_domain}"
    if _digitalocean_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_digitalocean_origin)
    if APP_BASE_URL == "http://localhost:3000":
        APP_BASE_URL = _digitalocean_origin

# Defense in depth: force all local-test/mock flags off in production regardless
# of env. Production starts with reference data only; real operational data
# arrives through backend upload/admin workflows after deployment.
ENABLE_MOCK_DATA = False
ENABLE_DEV_ENDPOINTS = False
ENABLE_DEV_SEED = False
ENABLE_DEV_IMPORTS = False
ALLOW_LOCAL_TEST_UPLOADS = False
PARTNER_ROLE_BRIDGE = False

_spaces_client_config = Config(
    signature_version="s3v4",
    connect_timeout=SPACES_CONNECT_TIMEOUT_SECONDS,
    read_timeout=SPACES_READ_TIMEOUT_SECONDS,
    max_pool_connections=SPACES_MAX_POOL_CONNECTIONS,
    retries={
        "mode": "standard",
        "total_max_attempts": SPACES_MAX_ATTEMPTS,
    },
    s3={"addressing_style": "virtual"},
)


def _spaces_options(location: str) -> dict:
    prefix = "/".join(part for part in (SPACES_PREFIX, location) if part)
    return {
        "access_key": SPACES_ACCESS_KEY_ID,
        "secret_key": SPACES_SECRET_ACCESS_KEY,
        "bucket_name": SPACES_BUCKET_NAME,
        "endpoint_url": SPACES_ENDPOINT_URL,
        "region_name": SPACES_REGION,
        "location": prefix,
        "default_acl": "private",
        "file_overwrite": False,
        "querystring_auth": True,
        "querystring_expire": 300,
        # django-storages otherwise keeps the whole remote object in memory
        # while FileResponse reads it. Spill after 5 MiB to bounded temp disk.
        "max_memory_size": 5 * 1024 * 1024,
        "object_parameters": {"CacheControl": "private, no-store"},
        "client_config": _spaces_client_config,
    }


STORAGES = {
    # Django FileFields (leave and message attachments) are private too.
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": _spaces_options("media"),
    },
    # Evidence/documents/PD use this alias and are never exposed as URLs.
    "private_uploads": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": _spaces_options("private"),
    },
    "staticfiles": {
        # Shared with config.settings.collectstatic, which is what actually
        # builds the manifest during the Docker build.
        "BACKEND": STATICFILES_STORAGE_BACKEND,
    },
}
