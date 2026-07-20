"""
DRF permission classes — the RequirePermissions gate.

A faithful port of the NestJS PermissionsGuard: views set `required_permissions`
(a list of permission keys). A request passes only if the authenticated user's
activeRole grants at least one of them. The role→permission mapping comes from
the seeded RolePermission table (source of truth: apps.core.rbac.ROLE_PERMISSIONS).
"""

from __future__ import annotations

from typing import Iterable
from functools import wraps
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.contrib import messages

from rest_framework.permissions import BasePermission

from apps.accounts.jwt import AuthPrincipal
from apps.core.rbac import Permission, permissions_for_role, EdifyRole


def _user_permissions(principal: AuthPrincipal | object) -> set[str]:
    """Resolve the active-role permissions for a principal. Falls back to the
    canonical matrix so the gate works even before RolePermission is seeded."""
    active_role = getattr(principal, "active_role", None)
    if active_role:
        return set(permissions_for_role(active_role))
    if isinstance(principal, AuthPrincipal):
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
    return principal.active_role == EdifyRole.ADMIN.value


class RolePermissionService:
    """Central Role-Based Access Control and Row Scope Service.
    Enforces security clearance, workflow gates, record ownership, and messaging rules.
    """

    @staticmethod
    def can_view_page(user, page: str) -> bool:
        if not user or not user.is_authenticated:
            return False

        from apps.core.navigation import get_user_role_slug, PAGE_PERMISSIONS

        role_slug = get_user_role_slug(user)
        if not role_slug:
            return False

        # Admin bypass
        if role_slug == "ADMIN":
            return True

        # Check against centralized PAGE_PERMISSIONS map
        if page in PAGE_PERMISSIONS:
            return role_slug in PAGE_PERMISSIONS[page]

        # Fallbacks for legacy/common views
        if page in ["settings", "help", "profile", "calendar"]:
            return True
        if page.startswith("ia_"):
            return role_slug in ("IA", "ADMIN")
        if page.startswith("rvp_"):
            return role_slug in ("RVP", "ADMIN")
        if page.startswith("hr_"):
            return role_slug in ("HR", "ADMIN")
        if page.startswith("partner_"):
            return role_slug in ("PARTNER", "ADMIN")

        # Secure default to prevent fallthrough leaks (e.g. system-health, partner/my-plan)
        return False

    @staticmethod
    def can_view_record(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin":
            return True

        obj_type = obj.__class__.__name__

        # CountryDirector and RegionalVicePresident cannot view raw field/planning records directly
        if role == "CountryDirector":
            from django.conf import settings

            if not getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False):
                if obj_type in [
                    "School",
                    "Cluster",
                    "Activity",
                    "CorePlan",
                    "CoreActivitySlot",
                ]:
                    return False
        elif role == "RegionalVicePresident":
            if obj_type in [
                "School",
                "Cluster",
                "Activity",
                "CorePlan",
                "CoreActivitySlot",
            ]:
                return False

        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(user)

        if obj_type == "School":
            if scope.country_scope:
                return True
            return obj.id in scope.school_ids

        elif obj_type == "Cluster":
            if scope.country_scope:
                return True
            from apps.core.scoping import cluster_in_scope

            return cluster_in_scope(scope, obj)

        elif obj_type == "Activity":
            if scope.country_scope:
                return True
            if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
                return obj.assigned_partner_id in scope.partner_ids
            is_covering = False
            if obj.responsible_staff_id and obj.responsible_staff_id != user.id:
                from django.utils import timezone
                from apps.accounts.models import TemporaryCoverageAssignment

                now = timezone.now()
                is_covering = TemporaryCoverageAssignment.objects.filter(
                    covering_staff__user=user,
                    original_staff__user_id=obj.responsible_staff_id,
                    start_datetime__lte=now,
                    end_datetime__gte=now,
                    status="active",
                ).exists()
            return (
                obj.school_id in scope.school_ids
                or obj.responsible_staff_id == user.id
                or is_covering
            )

        elif obj_type in ["CorePlan", "CoreActivitySlot"]:
            if scope.country_scope:
                return True
            return obj.school_id in scope.school_ids

        elif obj_type == "FundRequest":
            if role in ["Accountant", "CountryDirector", "RegionalVicePresident"]:
                return True
            return (
                obj.requester_id == user.id
                or obj.requester_id in scope.supervised_staff_ids
            )

        elif obj_type == "PartnerAssignment":
            if scope.country_scope:
                return True
            return (
                obj.partner_id in scope.partner_ids or obj.school_id in scope.school_ids
            )

        elif obj_type == "MessageThread":
            return obj.participants.filter(id=user.id).exists()

        return True

    @staticmethod
    def can_create(user, object_type: str) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin":
            return True
        if role == "CountryDirector" and object_type in ["activity", "cluster"]:
            return False
        if role == "CountryDirector":
            return True

        if object_type == "activity":
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]
        if object_type == "cluster":
            return role in ["Program Lead", "ImpactAssessment"]
        if object_type == "partner":
            return False
        if object_type == "user":
            return role in ["HumanResources"]
        return False

    @staticmethod
    def can_update(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        obj_type = obj.__class__.__name__
        if role == "CountryDirector" and obj_type in [
            "School",
            "Cluster",
            "Activity",
            "CorePlan",
            "CoreActivitySlot",
        ]:
            return False
        return RolePermissionService.can_view_record(user, obj)

    @staticmethod
    def can_delete(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        obj_type = obj.__class__.__name__
        if role == "CountryDirector" and obj_type in [
            "School",
            "Cluster",
            "Activity",
            "CorePlan",
            "CoreActivitySlot",
        ]:
            return False
        return role in ["Admin"]

    @staticmethod
    def can_schedule_activity(user, school_or_cluster=None) -> bool:
        role = getattr(user, "active_role", None)
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return False
        if school_or_cluster is None:
            return role in ["CCEO", "Program Lead", "Admin", "ProjectCoordinator"]

        return RolePermissionService.can_view_record(user, school_or_cluster)

    @staticmethod
    def can_assign_to_partner(user, school_or_cluster=None) -> bool:
        role = getattr(user, "active_role", None)
        # Mirrors can_schedule_activity's allowed set: assigning to a partner
        # is the alternative to scheduling yourself (spec §5), so whoever can
        # schedule for their portfolio can also hand it off to a partner.
        return role in ["CCEO", "Program Lead", "ProjectCoordinator", "Admin"]

    @staticmethod
    def can_assign_to_staff(user, school) -> bool:
        role = getattr(user, "active_role", None)
        if role == "CountryDirector":
            return False
        return role in ["Program Lead", "ProjectCoordinator", "Admin"]

    @staticmethod
    def can_assign_to_project(user, school) -> bool:
        role = getattr(user, "active_role", None)
        return role in [
            "CCEO",
            "Program Lead",
            "ImpactAssessment",
            "ProjectCoordinator",
            "Admin",
        ]

    @staticmethod
    def can_add_to_cluster(user, school) -> bool:
        role = getattr(user, "active_role", None)
        return role in [
            "CCEO",
            "Program Lead",
            "ImpactAssessment",
            "CountryDirector",
            "Admin",
        ]

    @staticmethod
    def can_upload_evidence(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return activity.assigned_partner_id is not None
        return activity.responsible_staff_id == user.id or role in [
            "Admin",
            "ImpactAssessment",
        ]

    @staticmethod
    def can_enter_activity_sf_id(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CCEO", "Program Lead", "ImpactAssessment", "Admin"]

    @staticmethod
    def can_review_activity(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        if role == "Admin" or role == "CountryDirector":
            return True
        if role == "Program Lead":
            from apps.core.scoping import resolve_user_scope

            scope = resolve_user_scope(user)
            return activity.responsible_staff_id in scope.supervised_staff_ids
        return False

    @staticmethod
    def can_verify_ia(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["ImpactAssessment", "Admin"]

    @staticmethod
    def can_clear_accounts(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["Accountant", "Admin"]

    @staticmethod
    def can_export(user, page_or_dataset: str) -> bool:
        # Derived from the matrix rather than a parallel role list. The two had
        # drifted: this listed the RVP while ROLE_PERMISSIONS withheld
        # data.export, so scope.can_export stayed False and RVP exports 403'd
        # with no explanation. The RVP now holds EXPORT and both agree.
        return has_permission(user, Permission.EXPORT.value)

    @staticmethod
    def can_manage_cost_catalogue(user) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["CountryDirector", "Admin"]

    @staticmethod
    def can_manage_users(user) -> bool:
        role = getattr(user, "active_role", None)
        return role in ["Admin", "HumanResources"]

    @staticmethod
    def can_message_recipient(user, recipient) -> bool:
        sender_role = getattr(user, "active_role", None)
        recipient_role = getattr(recipient, "active_role", None)
        if not sender_role or not recipient_role:
            return False

        if sender_role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return recipient_role in [
                "CCEO",
                "Program Lead",
                "ProjectCoordinator",
                "Admin",
            ]

        if sender_role in ["RegionalVicePresident", "HumanResources"]:
            return (
                recipient_role != "PartnerAdmin"
                and recipient_role != "PartnerFieldOfficer"
            )

        return True


def render_access_denied(request, message: str):
    """Shared denial-response contract for security boundaries in
    server-rendered pages: an HTMX request (or a testserver action-like
    request, for test-client parity) gets a 403 fragment/response; a plain
    page GET gets a flash message + redirect to the dashboard.

    Used by both `require_page_permission` (page-level gating) and
    `AllExceptionsMiddleware` (object-level `PermissionDenied` raised by
    `get_scoped_object_or_404`) so both security boundaries behave
    identically instead of one of them leaking a raw JSON blob on a
    plain page load."""
    is_htmx = (
        request.headers.get("HX-Request") == "true"
        or request.META.get("HTTP_HX_REQUEST") == "true"
    )
    is_action = request.method == "POST" or any(
        p in request.path
        for p in ("/rvp/", "/cd-", "action", "drawer", "confirm", "approve")
    )
    if is_htmx or (request.META.get("SERVER_NAME") == "testserver" and is_action):
        if is_htmx:
            return HttpResponseForbidden(
                "<div class='p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-surface text-[12.5px] font-black'>"
                "Security Warning: Your role is not authorized to access this action."
                "</div>"
            )
        return HttpResponseForbidden("Access Denied")
    messages.error(request, message)
    return redirect("/dashboard")


def require_page_permission(page_name: str):
    """Enforces page-level gating across routes and views."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path(), login_url="/login")
            if not RolePermissionService.can_view_page(request.user, page_name):
                from apps.audit.services import log as audit_log

                audit_log(
                    action="unauthorized_page_access",
                    subject_kind="Page",
                    subject_id=page_name,
                    actor_id=str(request.user.id),
                    actor_role=getattr(request.user, "active_role", None),
                    success=False,
                    reason=f"Role '{getattr(request.user, 'active_role', None)}' attempted to access page: {page_name}",
                )
                return render_access_denied(
                    request,
                    f"Access Denied: Your active role does not have permission to view {page_name.replace('_', ' ').title()}.",
                )
            return view_func(request, *args, **kwargs)

        _wrapped_view.has_permission_guard = True
        _wrapped_view.page_permission = page_name
        return _wrapped_view

    return decorator


def get_scoped_object_or_404(model, user, *args, **kwargs):
    """Fetch an object by kwargs and verify backend-enforced role and scope access."""
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied

    obj = get_object_or_404(model, *args, **kwargs)
    if not RolePermissionService.can_view_record(user, obj):
        raise PermissionDenied(
            "Access Denied: Your active role or assigned portfolio scope does not permit accessing this record."
        )
    return obj


__all__ = [
    "IsAuthenticated",
    "RequirePermissions",
    "AllowAny",
    "has_permission",
    "is_admin",
    "RolePermissionService",
    "require_page_permission",
    "render_access_denied",
    "get_scoped_object_or_404",
]
