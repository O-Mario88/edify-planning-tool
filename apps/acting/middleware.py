"""The acting capacity of a request.

Runs directly after authentication. For a person with an active acting
appointment who is working in it, the request's principal is presented to
the rest of the stack in the acting role, inside the appointing leader's
seat (``apps.acting.services.attach``). Everything after this middleware
— page gates, link gating, scope, navigation, services — asks the gates it
always asked and is answered for the acting capacity.

Two further things are decided here because only here is the route known:

* **Writes are refused unless the action is delegated.** A role name inside
  a service cannot tell an acting leader from the substantive one, so nothing
  an acting capacity may change is left to those checks: a request that is
  not a read passes only where the appointment's policy says so
  (``ActingRole.may_send``: a follow-up action it names, or a page it leaves
  workable), or on one of the few personal routes below. Everything else
  answers 403 before the view runs.
* **The capacity is recorded for the audit log**, which is handed actor ids
  by services that never see a request.

The appointment is read from the database on every request made by a person
who has one (``User.acting_until`` spares everybody else the query). There
is no cache to go stale: a cancelled or ended appointment stops on the next
request.
"""

from __future__ import annotations

from django.http import HttpResponseForbidden

from apps.core import acting as acting_api

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Routes with no page permission that belong to the signed-in person's own
# account: signing out, switching role, their second factor, the policies
# they must acknowledge, and the presence stream.
PERSONAL_VIEWS = frozenset(
    {
        "logout_view",
        "switch_role_view",
        "force_change_password_view",
        "mfa_verify_view",
        "mfa_resend_view",
        "mfa_settings_view",
        "mfa_app_setup_view",
        "mfa_app_remove_view",
        "engagement_heartbeat_view",
        "submit_acknowledgement_view",
        "attest_offline_view",
        "stream",
    }
)


class ActingCapacityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            from apps.acting import services

            services.attach(user)
            acting_api.remember_request_capacity(user)
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method in SAFE_METHODS:
            return None
        user = getattr(request, "user", None)
        context = acting_api.acting_context(user) if user is not None else None
        if context is None:
            return None
        if may_write_route(context, view_func):
            return None
        return self._refuse(request, context, view_func)

    @staticmethod
    def _refuse(request, context, view_func):
        from apps.audit.services import log as audit_log
        from apps.core.permissions import render_access_denied

        audit_log(
            action="acting_capacity.write_refused",
            subject_kind="Route",
            subject_id=(request.path or "")[:128],
            actor_id=str(request.user.id),
            actor_role=context.substantive_role,
            success=False,
            reason=(
                f"{context.label} is not delegated changes on "
                f"{getattr(view_func, '__name__', 'this route')}."
            ),
        )
        message = (
            f"This is not part of your {context.label} appointment. It stays "
            f"with {context.seat_name}; your own work is under your "
            f"{context.substantive_role} role."
        )
        if request.headers.get("HX-Request") == "true":
            # The platform's own refusal fragment, drawn where the form was.
            return render_access_denied(request, message)
        # A refused change is always a 403, never a redirect that an API
        # client or a form post would follow as though it had been accepted.
        return HttpResponseForbidden(message)


def may_write_route(context, view_func) -> bool:
    """Whether the acting capacity may send a change to this route."""
    from apps.acting.policy import acting_role
    from apps.core.permissions import _page_permissions_of

    entry = acting_role(context.acting_role)
    if entry is None:
        return False
    name = _view_name(view_func)
    pages = _page_permissions_of(view_func)
    if pages:
        # The policy's whole rule for a page route: the named follow-up
        # actions, a person's own account pages, and never a withheld action.
        return entry.may_send(name, pages)
    if name in PERSONAL_VIEWS:
        return True
    # A route with no page gate is gated on permission keys (the API, the
    # catalogue, the milestone actions), and the acting capacity's keys are
    # already the policy's. Where the acting role reaches no further than
    # the appointee on shared ground, those routes stay as they were; where
    # it reaches the whole seat, none of them is delegated.
    return entry.keeps_own_page_writes


def _view_name(view_func) -> str:
    while getattr(view_func, "__wrapped__", None) is not None:
        view_func = view_func.__wrapped__
    return getattr(view_func, "__name__", "")


__all__ = ["ActingCapacityMiddleware", "PERSONAL_VIEWS", "may_write_route"]
