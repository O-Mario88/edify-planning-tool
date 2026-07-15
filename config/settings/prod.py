"""
Production settings — fail closed.

Ports the NestJS env.validation.ts production safety rails: boot refuses to
start unless mock data, dev endpoints, and shadow authorization are all off,
the JWT secret is strong, and evidence storage is on a persistent absolute path.
"""

import sys

from .base import *  # noqa: F401,F403
from .base import _truthy

IS_PRODUCTION = True
NODE_ENV = "production"
DEBUG = False

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
if len(JWT_SECRET) < 16 or "change-me" in JWT_SECRET or "dev-only" in JWT_SECRET:
    _issues.append("A strong JWT_SECRET is required in production.")
if AUTHZ_MODE != "enforce":
    _issues.append(
        'AUTHZ_MODE must be "enforce" in production '
        "(object-level authorization cannot run in shadow)."
    )
if not EVIDENCE_STORAGE_DIR or not EVIDENCE_STORAGE_DIR.startswith("/"):
    _issues.append(
        "EVIDENCE_STORAGE_DIR must be set to an absolute, persistent path "
        "(a mounted volume) in production — relative/ephemeral storage loses "
        "evidence on redeploy."
    )
if not SUPER_ADMIN_PASSWORD:
    _issues.append("SUPER_ADMIN_PASSWORD must be set (super-admin login).")

if _issues:
    sys.stderr.write(
        "Production environment is not safe:\n" + "\n".join(_issues) + "\n"
    )
    raise SystemExit(1)

# ── Hardened security posture ────────────────────────────────────────────────
if "*" in ALLOWED_HOSTS:
    ALLOWED_HOSTS = []

# Dynamically resolve Railway public domain if it exists
railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if railway_domain:
    if "://" in railway_domain:
        railway_domain = railway_domain.split("://")[1]
    railway_domain = railway_domain.split("/")[0].split(":")[0]
    if railway_domain not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(railway_domain)

# Refuse to boot with no real host configured. This check must run BEFORE
# the loopback hosts are appended below — with them already in the list, an
# unset ALLOWED_HOSTS would boot "healthy" (localhost health probes pass)
# while every real request 400s with DisallowedHost.
if not ALLOWED_HOSTS:
    _issues.append(
        "ALLOWED_HOSTS must be set to explicit hosts in production "
        "(or RAILWAY_PUBLIC_DOMAIN must be present)."
    )
    sys.stderr.write(
        "Production environment is not safe:\n" + "\n".join(_issues) + "\n"
    )
    raise SystemExit(1)

# Allow local loopback addresses for container health probes
for host in ["localhost", "127.0.0.1", "0.0.0.0"]:
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

SECURE_SSL_REDIRECT = _truthy(os.environ.get("SECURE_SSL_REDIRECT"), fallback=True)
SESSION_COOKIE_SECURE = _truthy(os.environ.get("SESSION_COOKIE_SECURE"), fallback=True)
CSRF_COOKIE_SECURE = _truthy(os.environ.get("CSRF_COOKIE_SECURE"), fallback=True)
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"

# Defense in depth: force all local-test/mock flags off in production regardless
# of env. Production starts with reference data only; real operational data
# arrives through backend upload/admin workflows after deployment.
ENABLE_MOCK_DATA = False
ENABLE_DEV_ENDPOINTS = False
ENABLE_DEV_SEED = False
ENABLE_DEV_IMPORTS = False
ALLOW_LOCAL_TEST_UPLOADS = False
PARTNER_ROLE_BRIDGE = False

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
