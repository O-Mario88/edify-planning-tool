"""
Production settings — fail closed.

Ports the NestJS env.validation.ts production safety rails: boot refuses to
start unless mock data, dev endpoints, and shadow authorization are all off,
the JWT secret is strong, and evidence storage is on a persistent absolute path.
"""
import sys

from .base import *  # noqa: F401,F403

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
if (
    len(JWT_SECRET) < 16
    or "change-me" in JWT_SECRET
    or "dev-only" in JWT_SECRET
):
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
    sys.stderr.write("Production environment is not safe:\n" + "\n".join(_issues) + "\n")
    raise SystemExit(1)

# ── Hardened security posture ────────────────────────────────────────────────
if "*" in ALLOWED_HOSTS:
    ALLOWED_HOSTS = []
if not ALLOWED_HOSTS:
    _issues.append("ALLOWED_HOSTS must be set to explicit hosts in production.")
    sys.stderr.write("Production environment is not safe:\n" + "\n".join(_issues) + "\n")
    raise SystemExit(1)

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_REFERRER_POLICY = "same-origin"
