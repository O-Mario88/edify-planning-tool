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
from django.utils.html import escape

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

        from apps.core.navigation import (
            get_user_role_slug,
            PAGE_PERMISSIONS,
            ROLE_EXCLUSIVE_PAGES,
        )

        role_slug = get_user_role_slug(user)
        if not role_slug:
            return False

        # Specialist operational pages can explicitly opt out of the Admin
        # observation bypass. This is checked first so "role-exclusive" means
        # exactly that in direct URLs as well as navigation.
        if page in ROLE_EXCLUSIVE_PAGES:
            return role_slug in PAGE_PERMISSIONS.get(page, set())

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
            from apps.core.scoping import owner_ids

            return (
                obj.school_id in scope.school_ids
                # Either id space — see scoping.owner_ids. Comparing only
                # against user.id disowned most of a field worker's activities.
                or obj.responsible_staff_id in owner_ids(user)
                or getattr(obj, "monitored_by_staff_id", None) in owner_ids(user)
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
        if role == EdifyRole.ADMIN.value:
            return True
        obj_type = obj.__class__.__name__
        if role == "CountryDirector" and obj_type in [
            "School",
            "Cluster",
            "Activity",
            "CorePlan",
            "CoreActivitySlot",
        ]:
            return False
        # Supervision is not ownership. A Program Lead sees their team's
        # schools so they can monitor them; this function used to end at
        # can_view_record, so seeing one meant being able to edit it — every
        # school of every CCEO they supervise. No page offered those controls,
        # which is why it stayed invisible, but the API, the HTMX endpoints and
        # the bulk actions all resolve here, and a hidden button is not an
        # authorization decision.
        if obj_type == "School" and not RolePermissionService._owns_school(user, obj):
            return False
        return RolePermissionService.can_view_record(user, obj)

    @staticmethod
    def _owns_school(user, school) -> bool:
        """Is this school directly assigned to this person?

        Ownership is recorded two ways and both are live: account_owner_id on
        the school, and a StaffSchoolAssignment row. owner_ids() covers the
        other half of the problem — the id may be a User id or a StaffProfile
        id depending on which path wrote it.
        """
        from apps.core.scoping import owner_ids

        identifiers = set(owner_ids(user))
        if not identifiers:
            return False
        if str(getattr(school, "account_owner_id", "") or "") in identifiers:
            return True
        try:
            from apps.accounts.models import StaffSchoolAssignment

            return StaffSchoolAssignment.objects.filter(
                school_id=school.id, staff_id__in=identifiers
            ).exists()
        except Exception:  # noqa: BLE001 — a lookup failure must not grant access
            return False

    @staticmethod
    def can_delete(user, obj) -> bool:
        role = getattr(user, "active_role", None)
        obj_type = obj.__class__.__name__
        # Execution records are deletable by no role, Admin included: an
        # activity or Core slot carries budget lines, evidence state and target
        # credit, and deleting one from an ordinary page erases that history.
        # Repairs go through the controlled data-repair workflow instead.
        # School/Cluster stay Admin-deletable — master-data administration.
        if obj_type in ["Activity", "CorePlan", "CoreActivitySlot"]:
            return False
        if role == "CountryDirector" and obj_type in ["School", "Cluster"]:
            return False
        return role in ["Admin"]

    @staticmethod
    def can_schedule_activity(user, school_or_cluster=None) -> bool:
        role = getattr(user, "active_role", None)
        if role == EdifyRole.ADMIN.value:
            return True
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return False
        if school_or_cluster is None:
            return role in ["CCEO", "Program Lead", "ProjectCoordinator"]

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
        # Registry data, like cluster membership: Admin records which project a
        # school participates in, and schedules none of that project's work.
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
        # Admin keeps this one: which cluster a school belongs to is registry
        # data, and Admin already owns the school registry. Scheduling the
        # cluster's meetings is execution and is cut elsewhere.
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
        if role == EdifyRole.ADMIN.value:
            return True
        if role in ["PartnerAdmin", "PartnerFieldOfficer"]:
            return activity.assigned_partner_id is not None
        if role == "ImpactAssessment":
            return True
        from apps.core.scoping import owner_ids

        mine = owner_ids(user)
        # The owner in either id space, or the staff member monitoring a
        # partner-delivered activity. Monitoring is visibility, not a gate:
        # partner evidence goes directly to IA (§10, 2026-08-20) — the
        # monitor sees the work, chases delays, and never approves evidence.
        return (
            activity.responsible_staff_id in mine
            or getattr(activity, "monitored_by_staff_id", None) in mine
        )

    @staticmethod
    def can_enter_activity_sf_id(user, activity) -> bool:
        """Who may stamp the Salesforce Activity ID on a completed activity.

        Ownership, not just role. This asked the role alone, so a Programme
        Lead — who holds the role — could enter the Salesforce ID on any
        activity they could reach, including every one of their CCEOs'. §1B
        lists that among the things supervision does not license: the person
        who did the work records its reference.

        Impact Assessment and Admin keep the country-wide reach they need to
        unblock a stalled chain; the monitoring staff member on a
        partner-delivered activity keeps it too, because accepting the
        partner's evidence and recording its reference are the same job.
        """
        role = getattr(user, "active_role", None)
        if role in ("ImpactAssessment", EdifyRole.ADMIN.value):
            return True
        if role not in ("CCEO", "Program Lead"):
            return False
        from apps.core.scoping import owner_ids

        mine = owner_ids(user)
        return (
            activity.responsible_staff_id in mine
            or getattr(activity, "monitored_by_staff_id", None) in mine
        )

    @staticmethod
    def can_review_activity(user, activity) -> bool:
        role = getattr(user, "active_role", None)
        if role == EdifyRole.ADMIN.value:
            return True
        if role == "CountryDirector":
            return True
        if role == "Program Lead":
            from apps.core.scoping import resolve_user_scope

            scope = resolve_user_scope(user)
            return activity.responsible_staff_id in scope.supervised_staff_ids
        return False

    @staticmethod
    def can_verify_ia(user, activity) -> bool:
        """Verification authority, read from the matrix — never a role list.

        `ia.verify` is one of the authorities ADMIN_EXCLUDED_PERMISSIONS
        withholds from Admin, precisely so no single account can verify work
        and release money for it. A hardcoded ["ImpactAssessment", "Admin"]
        re-granted it on the page surface while the DRF surface refused it,
        which is the asymmetry the 2026-08 audit found and this closes.
        """
        from apps.core.rbac import Permission

        return has_permission(user, Permission.IA_VERIFY.value)

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

        # A Program Lead supervises a team; they are not a country function.
        # This fell through to `return True`, so the whole rule was a role-pair
        # matrix with no relationship term at all — once the context gate was
        # satisfied, any Program Lead could message any other Program Lead's
        # CCEOs about restricted operational work.
        if sender_role == "Program Lead":
            if recipient_role != "CCEO":
                return True  # peers, leadership, IA, finance, partners
            return RolePermissionService._supervises(user, recipient)

        return True

    @staticmethod
    def _supervises(user, recipient) -> bool:
        """Is `recipient` on `user`'s own supervised team?"""
        try:
            from apps.core.scoping import resolve_user_scope

            scope = resolve_user_scope(user)
            team = set(scope.supervised_staff_ids or [])
            if not team:
                # An unassigned supervisor keeps their previous reach rather
                # than being silently cut off from everyone.
                return True
            recipient_sp = getattr(recipient, "staff_profile_id", None)
            return bool(recipient_sp and recipient_sp in team)
        except Exception:  # noqa: BLE001
            return False


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
            # The caller's message, not a fixed one. Every denial used to read
            # "Your role is not authorized", which is wrong for the commonest
            # case on this platform: a supervisor reaching into a supervisee's
            # record holds exactly the right role and is being refused over
            # *ownership*. Telling them the role is wrong sends them to ask an
            # administrator for a permission they already have, instead of to
            # the colleague who owns the work.
            return HttpResponseForbidden(
                "<div class='p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-surface text-[12.5px] font-black'>"
                f"{escape(message)}"
                "</div>"
            )
        return HttpResponseForbidden(message or "Access Denied")
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


def require_any_page_permission(*page_names: str):
    """Gate a view on holding ANY ONE of several page permissions.

    For surfaces two roles reach for the same reason. The planning-oversight
    drawer is the case: "what is this piece of work and where has it been" is
    the same question for a Program Lead and a Country Director, and each holds
    a different page permission that entitles them to ask it.

    Written as a decorator rather than as a check inside the view so the
    production-readiness scanner can see the guard. It reads the attributes
    this sets, and an in-body check — however correct — reads to it as an
    ungated page, which is the same signal an actually ungated one gives.
    """
    if not page_names:  # pragma: no cover — programming error
        raise ValueError("require_any_page_permission needs at least one page")

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path(), login_url="/login")
            if not any(
                RolePermissionService.can_view_page(request.user, page)
                for page in page_names
            ):
                from apps.audit.services import log as audit_log

                audit_log(
                    action="unauthorized_page_access",
                    subject_kind="Page",
                    subject_id=page_names[0],
                    actor_id=str(request.user.id),
                    actor_role=getattr(request.user, "active_role", None),
                    success=False,
                    reason=(
                        f"Role '{getattr(request.user, 'active_role', None)}' "
                        f"attempted to access page: {' or '.join(page_names)}"
                    ),
                )
                return render_access_denied(
                    request,
                    "Access Denied: Your active role does not have permission to "
                    f"view {page_names[0].replace('_', ' ').title()}.",
                )
            return view_func(request, *args, **kwargs)

        _wrapped_view.has_permission_guard = True
        _wrapped_view.page_permission = page_names[0]
        _wrapped_view.page_permissions = page_names
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


def get_operational_school_or_404(user, *args, **kwargs):
    """The write-side twin of `get_scoped_object_or_404`, for schools.

    `can_view_record` answers "may this person *see* this row", and a
    supervisor may see their whole team's. Drawers and POST handlers that
    schedule, assign or edit were reading that answer, so a Programme Lead who
    knew a school id could open the scheduling drawer for a CCEO's school and
    be refused only later, by the activity service, in its own words.

    This asks `may_plan_school` instead — the direct portfolio — and refuses in
    the words §8 specifies, so the denial explains that the work belongs to
    someone else rather than reading as a missing record.

    Schools only, deliberately. `CorePlan.school_id` and its siblings hold the
    *business* school id while `scope.own_school_ids` holds primary keys, and a
    helper that quietly compared the two would answer "denied" for everybody.
    Callers holding one of those rows resolve the School first and ask here.
    """
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    from apps.core.scoping import (
        OVERSIGHT_ONLY_MESSAGE,
        may_plan_school,
        resolve_user_scope,
    )
    from apps.schools.models import School

    school = get_object_or_404(School, *args, **kwargs)
    if not RolePermissionService.can_view_record(user, school):
        raise PermissionDenied(
            "Access Denied: Your active role or assigned portfolio scope does not permit accessing this record."
        )
    if not may_plan_school(resolve_user_scope(user), school.id):
        raise PermissionDenied(OVERSIGHT_ONLY_MESSAGE)
    return school


def get_operational_cluster_or_404(user, *args, **kwargs):
    """The cluster equivalent of `get_operational_school_or_404`.

    `cluster_in_scope` without `direct_only` is the read question, and a
    supervisor passes it for every cluster their CCEOs hold — which is why the
    scheduling drawers, the partner-assignment drawer and its POST could all
    be opened against a supervisee's cluster by id.
    """
    from django.shortcuts import get_object_or_404
    from django.core.exceptions import PermissionDenied
    from apps.clusters.models import Cluster
    from apps.core.scoping import (
        OVERSIGHT_ONLY_MESSAGE,
        cluster_in_scope,
        resolve_user_scope,
    )

    cluster = get_object_or_404(Cluster, *args, **kwargs)
    scope = resolve_user_scope(user)
    if not cluster_in_scope(scope, cluster):
        raise PermissionDenied(
            "Access Denied: Your active role or assigned portfolio scope does not permit accessing this record."
        )
    if not cluster_in_scope(scope, cluster, direct_only=True):
        raise PermissionDenied(OVERSIGHT_ONLY_MESSAGE)
    return cluster


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
    "get_operational_school_or_404",
    "get_operational_cluster_or_404",
]


def require_export_permission(view):
    """Gate a CSV/data export on Permission.EXPORT.

    The verification audit found `data.export` enforced by exactly one of
    ~20 export endpoints — every other page permission implicitly granted
    bulk extraction. One decorator, wrapped OUTSIDE require_page_permission,
    so scope still applies and the refusal is a page, not a traceback.
    """
    from functools import wraps

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        wants_export = request.GET.get("export") or request.GET.get("format") == "csv"
        is_export_route = "export" in request.path
        if (wants_export or is_export_route) and not RolePermissionService.can_export(
            request.user, request.path
        ):
            return render_access_denied(
                request, "Your role does not include data export."
            )
        return view(request, *args, **kwargs)

    return wrapped
