"""
DRF permission classes — the RequirePermissions gate.

A faithful port of the NestJS PermissionsGuard: views set `required_permissions`
(a list of permission keys). A request passes only if the authenticated user's
activeRole grants at least one of them. The role→permission mapping comes from
the seeded RolePermission table (source of truth: apps.core.rbac.ROLE_PERMISSIONS).
"""
from __future__ import annotations

from typing import Iterable

from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.jwt import AuthPrincipal
from apps.core.rbac import permissions_for_role


def _user_permissions(principal: AuthPrincipal | object) -> set[str]:
    """Resolve the active-role permissions for a principal. Falls back to the
    canonical matrix so the gate works even before RolePermission is seeded."""
    if isinstance(principal, AuthPrincipal):
        # DB-seeded table is authoritative once present, but reading the matrix
        # is cheap and always correct. We prefer it for determinism.
        return set(permissions_for_role(principal.active_role))
    # Anonymous / unauthenticated
    return set()


class IsAuthenticated(BasePermission):
    """JWT required (mirrors NestJS JwtAuthGuard)."""

    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, "is_authenticated", False))


class RequirePermissions(BasePermission):
    """Permission gate (mirrors PermissionsGuard). The view declares
    `required_permissions = [...]` (any-of semantics, matching the legacy guard).
    Reads/likes may be relaxed per-view via `required_permissions_read`."""

    def has_permission(self, request, view):
        if not bool(request.user and getattr(request.user, "is_authenticated", False)):
            return False
        required: Iterable[str] | None = getattr(view, "required_permissions", None)
        if not required:
            return True  # no permission gate on this view
        perms = _user_permissions(request.user)
        return any(p in perms for p in required)


class AllowAny(BasePermission):
    """Public endpoint (login, health, invite-validate)."""

    def has_permission(self, request, view):
        return True


# Common role gating helpers used by services for object-level checks.
def has_permission(principal: AuthPrincipal, permission: str) -> bool:
    return permission in _user_permissions(principal)


def is_admin(principal: AuthPrincipal) -> bool:
    from apps.core.rbac import EdifyRole

    return principal.active_role == EdifyRole.ADMIN.value


__all__ = [
    "IsAuthenticated",
    "RequirePermissions",
    "AllowAny",
    "has_permission",
    "is_admin",
]
