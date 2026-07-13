"""
Security helpers — ports of security/auth-tokens.ts + password-rules.ts.

Token rules (spec):
  • tokens are cryptographically random
  • the DB stores ONLY a SHA-256 hash — never the raw token
  • tokens are single-use, expiring, revocable
  • the raw token is returned to the caller ONCE (for the email/link)

This module is the single place that knows how to mint + hash these tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from django.utils import timezone


def generate_token() -> str:
    """Generate a 32-byte (256-bit) random token, hex-encoded (64 chars)."""
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """SHA-256 hash a token for DB storage. The raw token is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def compare_hashes(a: str, b: str) -> bool:
    """Constant-time comparison of two hex-encoded hashes."""
    try:
        a_bytes = bytes.fromhex(a)
        b_bytes = bytes.fromhex(b)
    except ValueError:
        return False
    if len(a_bytes) != len(b_bytes):
        return False
    return hmac.compare_digest(a_bytes, b_bytes)


def expiry_from_now(minutes: int):
    return timezone.now() + timedelta(minutes=minutes)


def expiry_from_now_days(days: int):
    return timezone.now() + timedelta(days=days)


# ── Password policy ──────────────────────────────────────────────────────────
_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")
# Symbol = anything that's not a letter, digit, or whitespace.
_SYMBOL = re.compile(r"[^A-Za-z0-9\s]")


def validate_password(password: str, email: str | None = None) -> list[str]:
    """Return a list of human-readable failure reasons (empty = valid)."""
    violations: list[str] = []

    if not password:
        return ["Password cannot be empty."]
    if len(password) < 8:
        violations.append("Password must be at least 8 characters long.")
    if not _UPPER.search(password):
        violations.append("Password must include at least one uppercase letter.")
    if not _LOWER.search(password):
        violations.append("Password must include at least one lowercase letter.")
    if not _DIGIT.search(password):
        violations.append("Password must include at least one number.")
    if not _SYMBOL.search(password):
        violations.append("Password must include at least one symbol (e.g. !@#$%).")
    # Must not equal the email (case-insensitive).
    if email and password.lower() == email.lower():
        violations.append("Password cannot be the same as your email address.")
    return violations


def is_valid_password(password: str, email: str | None = None) -> bool:
    return len(validate_password(password, email)) == 0


__all__ = [
    "generate_token",
    "hash_token",
    "compare_hashes",
    "expiry_from_now",
    "expiry_from_now_days",
    "validate_password",
    "is_valid_password",
]
