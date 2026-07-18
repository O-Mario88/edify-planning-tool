"""
JWT issuance + verification — parity with NestJS @nestjs/jwt.

The access JWT carries `{sub: userId, activeRole}` and is signed with JWT_SECRET,
short-lived (15m). A rotating, revocable refresh token (7d, SHA-256 hashed) is
persisted alongside it. Logout revokes the refresh token.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from apps.core.cuid import cuid
from apps.core.exceptions import Unauthorized
from apps.core.security import generate_token, hash_token, expiry_from_now_days

from .models import RefreshToken, User


# ── Token issuance ───────────────────────────────────────────────────────────
def _secret() -> str:
    return settings.JWT_SECRET


def _algo() -> str:
    return getattr(settings, "JWT_ALGORITHM", "HS256")


def _access_ttl_minutes() -> int:
    return getattr(settings, "ACCESS_TOKEN_TTL_MINUTES", 15)


def issue_access_token(user_id: str, active_role: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "activeRole": active_role,
        "iat": now,
        "exp": now + timedelta(minutes=_access_ttl_minutes()),
    }
    return pyjwt.encode(payload, _secret(), algorithm=_algo())


def issue_token_pair(
    user_id: str,
    active_role: str,
    *,
    family_id: str | None = None,
    parent_id: str | None = None,
) -> dict[str, str]:
    """Mint an access JWT (15m) + a persisted, hashed refresh token (7d).

    A fresh login starts a NEW token family (family_id=None here). Rotating
    an existing session (apps.accounts.auth_services.refresh) passes that
    session's family_id and the just-consumed token's id as parent, so the
    whole lineage can be revoked together if a consumed token is ever
    replayed (SEC-03 reuse detection).
    """
    access_token = issue_access_token(user_id, active_role)
    raw_refresh = generate_token()
    RefreshToken.objects.create(
        user_id=user_id,
        token_hash=hash_token(raw_refresh),
        family_id=family_id or cuid(),
        parent_id=parent_id,
        expires_at=expiry_from_now_days(getattr(settings, "REFRESH_TOKEN_TTL_DAYS", 7)),
    )
    return {"accessToken": access_token, "refreshToken": raw_refresh}


def verify_access_token(token: str) -> dict[str, Any]:
    """Decode + verify an access JWT. Raises Unauthorized on any failure."""
    try:
        return pyjwt.decode(token, _secret(), algorithms=[_algo()])
    except pyjwt.ExpiredSignatureError:
        raise Unauthorized("Your session has expired. Please sign in again.")
    except pyjwt.PyJWTError:
        raise Unauthorized("Invalid authentication token.")


# ── DRF authentication ───────────────────────────────────────────────────────
class JwtAuthentication(BaseAuthentication):
    """Bearer-token auth. Mirrors the NestJS JwtStrategy: extracts the token,
    loads the User (must be active + not soft-deleted), resolves the active
    role (payload role must be in user.roles, else fall back to user.active_role),
    and attaches the AuthUser-style principal to `request.user`."""

    keyword = "Bearer"

    def authenticate(self, request: Request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(f"{self.keyword} "):
            return None
        token = header[len(self.keyword) + 1 :].strip()  # noqa: E203
        if not token:
            return None
        payload = verify_access_token(token)
        user = (
            User.objects.filter(
                id=payload.get("sub"), is_active=True, deleted_at__isnull=True
            )
            .select_related("staff_profile")
            .first()
        )
        if not user:
            raise Unauthorized("User not found or inactive")

        # Resolve the active role: payload role must be one of the user's roles.
        payload_role = payload.get("activeRole")
        if payload_role in (user.roles or []):
            active_role = payload_role
        else:
            active_role = user.active_role

        # Safely read the optional staff profile id (reverse OneToOne raises
        # RelatedObjectDoesNotExist when absent).
        staff_profile_id = None
        try:
            sp = user.staff_profile
            if sp:
                staff_profile_id = sp.id
        except Exception:  # noqa: BLE001
            pass

        # Attach an AuthUser-style principal so views read it like NestJS.
        principal = AuthPrincipal(
            user=user,
            user_id=user.id,
            email=user.email,
            name=user.name,
            roles=list(user.roles or []),
            active_role=active_role,
            staff_profile_id=staff_profile_id,
        )
        return (principal, None)

    def authenticate_header(self, request: Request) -> str:
        return self.keyword


class AuthPrincipal:
    """The authenticated principal — equivalent to the NestJS `AuthUser`
    attached to `req.user`. Also satisfies `request.user` for DRF permission
    checks (is_authenticated) and holds the underlying User model instance."""

    def __init__(
        self,
        user: User,
        user_id: str,
        email: str,
        name: str,
        roles: list[str],
        active_role: str,
        staff_profile_id: str | None = None,
    ):
        self._user = user
        self.user_id = user_id
        self.id = user_id  # convenience for DRF internals that read .id
        self.email = email
        self.name = name
        self.roles = roles
        self.active_role = active_role
        self.activeRole = active_role  # camelCase alias for NestJS-style code
        self.staff_profile_id = staff_profile_id
        self.staffProfileId = staff_profile_id

    # DRF permission compatibility
    @property
    def is_authenticated(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"AuthPrincipal({self.email} as {self.active_role})"


__all__ = [
    "issue_access_token",
    "issue_token_pair",
    "verify_access_token",
    "JwtAuthentication",
    "AuthPrincipal",
]
