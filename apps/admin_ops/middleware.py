"""Admin Support View — read-only enforcement for business-operation routes.

The Platform Operations doctrine gives Admin platform-wide *visibility* over
field-programme pages, and no authority over them. Hiding buttons is not
enforcement: an Admin (or anything holding an Admin session) can still POST
directly, fire an HTMX request, or edit a URL. This middleware refuses those
at the edge, so the rule holds no matter which view or service is reached.

Design choice — deny by default. The allow-list names the routes Admin *owns*
(their own operations workspace, user administration, configuration, support,
and the ordinary session/UI plumbing every role needs). Everything else is
business operations and is read-only for Admin. A new business route is
therefore protected the day it is added, which is the opposite of the failure
mode this replaces: a permission matrix that granted Admin every Permission,
including ones that did not exist when it was written.
"""

from __future__ import annotations

from django.http import HttpResponseForbidden, JsonResponse

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Routes Admin genuinely owns and may mutate. Verified against the URL conf,
# not guessed: user administration lives under /admin-panel, not /users, and a
# prefix that matches nothing would quietly grant nothing.
ADMIN_WRITABLE_PREFIXES: tuple[str, ...] = (
    # Platform operations: tickets, incidents, planning, my plan, maintenance.
    "/admin-ops",
    # Administration console: users, roles, audit, workflow rules, geography,
    # notification management, data quality, staff-setup queue.
    "/admin-panel",
    "/api/staff-candidates",  # creating a user for a candidate is user admin
    "/api/users",
    "/admin/",  # Django admin (geography bootstrap)
    "/system-health",
    "/data-repair",
    # School master data is Admin's remit (SCHOOL_UPLOAD / SCHOOL_EDIT are
    # kept). SSA score upload deliberately is NOT -- scores are field data, and
    # /ssa/upload stays blocked for Admin by omission.
    # School and SSA data administration: upload, edit, resolve duplicates.
    # Confirming an SSA record is IA's, and is not reachable here.
    "/schools/upload",
    "/ssa/upload",
    "/api/ssa/upload",
    "/api/schools/upload",
    "/data-quality",
    "/districts",
    "/cost-settings",
    # Session, personal and shared-UI plumbing every role keeps.
    "/login",
    "/logout",
    "/profile",
    "/settings",
    "/notifications",
    "/messages",
    "/search",
    "/help",
    "/support",
    "/api/notifications",
    "/api/messages",
    "/api/search",
)


# Administration endpoints that live under a business-looking path. A prefix
# cannot express "the delete action on a school, but not the clustering action
# on a school", so these are named by route instead. Each one is master-data or
# data-quality administration, which the doctrine keeps with Admin -- unlike
# clustering, scheduling and assignment, which are field-programme decisions.
ADMIN_WRITABLE_ROUTE_NAMES: frozenset[str] = frozenset(
    {
        "school_delete",  # master-data administration; can_delete(School) is Admin's
        "data_quality_issue_action",  # the Data Quality Center's own actions
        # Cluster membership is registry data. Scheduling a cluster meeting is
        # not, and is deliberately absent from this list.
        "school_edit_drawer",
        "school_change_type",
        "school_onboard_drawer",
        "add_school",
        "add_to_cluster_drawer",
        "assign_to_project_drawer",
        "cluster_bulk_assign_drawer",
        "create_cluster",
        # Personal policy-agreement plumbing is not business execution. Admin
        # is still a staff member who must acknowledge mandatory policies, and
        # the policy gate cannot release the session until these writes land.
        # Name the exact routes rather than allowing all /api/documents writes:
        # document authoring and lifecycle mutations stay read-only.
        "submit_acknowledgement",
        "attest_offline",
        "document_engagement",
        "document_print",
    }
)


def _named_route_is_admin_writable(path: str) -> bool:
    try:
        from django.urls import resolve

        return resolve(path).url_name in ADMIN_WRITABLE_ROUTE_NAMES
    except Exception:
        return False


def _is_admin(request) -> bool:
    user = getattr(request, "user", None)
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "active_role", None) == "Admin"
    )


def admin_may_mutate(path: str) -> bool:
    return path.startswith(ADMIN_WRITABLE_PREFIXES) or _named_route_is_admin_writable(
        path
    )


class AdminReadOnlyBusinessMiddleware:
    """Reject Admin mutations of field-programme records, however they arrive."""

    MESSAGE = (
        "Admin Support View is read-only. Platform operations may observe this "
        "record but cannot change business planning or execution. Raise a "
        "support ticket or use the Data Repair Center instead."
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in SAFE_METHODS
            and _is_admin(request)
            and not admin_may_mutate(request.path)
        ):
            return self._refuse(request)
        return self.get_response(request)

    def _refuse(self, request):
        from apps.audit.services import log as audit_log

        # `AuditLog.subject_id` is a 30-char identifier column, not a URL: a
        # path longer than that silently failed to write, which would have made
        # exactly the refusals worth auditing the ones with no audit row. The
        # full path lives in the payload; the subject is the route's first
        # segment, which is what makes the rows groupable.
        segment = (request.path.strip("/").split("/") or [""])[0]
        audit_log(
            action="admin_ops.readonly.blocked",
            subject_kind="route",
            subject_id=segment[:30] or "root",
            actor_id=getattr(request.user, "id", None),
            actor_role="Admin",
            success=False,
            reason="Admin attempted a business mutation in read-only support view.",
            payload={"method": request.method, "path": request.path},
        )
        if request.headers.get("HX-Request"):
            # HTMX swaps the response body, so the refusal has to be readable
            # in place rather than a bare status code.
            return HttpResponseForbidden(
                f'<div class="edify-inline-error" role="alert">{self.MESSAGE}</div>'
            )
        if request.path.startswith("/api/") or request.headers.get(
            "Accept", ""
        ).startswith("application/json"):
            return JsonResponse({"detail": self.MESSAGE}, status=403)
        return HttpResponseForbidden(self.MESSAGE)


class AdminSupportViewBannerMiddleware:
    """Flag business pages an Admin is observing, so the template can say so.

    Sets ``request.admin_support_view`` — the shell renders the
    "Admin Support View · Read Only" banner from it, and mutation controls
    hide behind the same flag. The banner is a courtesy; the refusal above is
    the enforcement.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.admin_support_view = _is_admin(request) and not admin_may_mutate(
            request.path
        )
        return self.get_response(request)
