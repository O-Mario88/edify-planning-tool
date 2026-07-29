"""The mandatory-policy access gate.

A user who has not answered an active mandatory policy targeted at them does not
reach the application. Enforced in middleware, not in a template redirect,
because a redirect only stops the person who followed a link: a direct URL, an
HTMX fragment, a DRF endpoint, an SSE stream, a file download and an export all
reach the same data by other doors, and every one of them has to be shut.

The allow-list is small and deliberate. A gated person must still be able to
read the policy they are being asked about, download or print it where that is
permitted, answer it, say why they disagree, reach HR, and log out. Anything
else waits.

Two states are gated, and they differ:

* **Pending** — the person has not answered. They go to the Agreement Center.
* **Disagreed** — they answered, and said no. They stay in restricted mode
  until HR resolves it, and may change their answer at any time. Nothing is
  suspended or deleted automatically; employment and partnership consequences
  are a governance process, not a middleware side effect.
"""

from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import redirect

AGREEMENT_URL = "/policy-agreement"
RESTRICTED_URL = "/policy-agreement/restricted"

#: Prefixes a gated user may still reach.
GATE_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/policy-agreement",
    "/documents/",  # the viewer, its preview stream, download and print
    "/api/documents/",  # heartbeat + acknowledgement submission
    "/login",
    "/logout",
    "/password",
    "/set-password",
    "/support",  # contacting the platform team
    "/help",  # HR contact details and accessibility guidance live here
    "/static/",
    "/media/",
    "/favicon",
    "/healthz",
    "/api/health",
    "/accessibility",
)


def is_exempt(path: str) -> bool:
    return path.startswith(GATE_EXEMPT_PREFIXES)


class PolicyGateService:
    """Resolves what, if anything, is blocking a user."""

    @staticmethod
    def any_blocking_policy_exists() -> bool:
        """Is there a live policy that withholds the application at all?

        This runs on every authenticated request, so the common case has to be
        cheap. Until somebody publishes a policy configured to block access,
        one EXISTS query answers the whole question and the two per-user reads
        below never happen. Memoised per request, so a page that issues several
        internal requests does not repeat even that.
        """
        from apps.core import request_cache
        from apps.documents.models import DocumentAsset, READABLE_STATUSES

        def compute():
            return DocumentAsset.objects.filter(
                status__in=READABLE_STATUSES,
                blocks_application_access=True,
                acknowledgement_required=True,
            ).exists()

        return request_cache.memoize("documents.blocking_policy_exists", compute)

    @staticmethod
    def blocking_acknowledgements(user):
        from apps.documents.services import AcknowledgementService

        return AcknowledgementService.blocking_for(user)

    @staticmethod
    def disagreements(user):
        from apps.documents.services import AcknowledgementService

        return AcknowledgementService.disagreed_for(user)

    @staticmethod
    def state_for(user) -> tuple[str, list]:
        """('clear' | 'pending' | 'restricted', acknowledgements)."""
        if not PolicyGateService.any_blocking_policy_exists():
            return "clear", []
        declined = PolicyGateService.disagreements(user)
        if declined:
            return "restricted", declined
        pending = PolicyGateService.blocking_acknowledgements(user)
        if pending:
            return "pending", pending
        return "clear", []


class PolicyGateMiddleware:
    """Withhold the application until active mandatory policies are answered."""

    MESSAGE = (
        "A mandatory policy is waiting for your response. Open the Policy "
        "Agreement Center to read it and record your answer."
    )
    RESTRICTED_MESSAGE = (
        "Your access is limited while your policy disagreement is with HR. You "
        "can still read the policy, contact HR, and change your answer."
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            not user
            or not getattr(user, "is_authenticated", False)
            or is_exempt(request.path)
        ):
            return self.get_response(request)

        try:
            state, _ = PolicyGateService.state_for(user)
        except Exception:  # noqa: BLE001 — the gate must never 500 the platform
            return self.get_response(request)

        if state == "clear":
            return self.get_response(request)

        message = self.RESTRICTED_MESSAGE if state == "restricted" else self.MESSAGE
        destination = RESTRICTED_URL if state == "restricted" else AGREEMENT_URL
        return self._withhold(request, message, destination)

    def _withhold(self, request, message: str, destination: str):
        from apps.audit.services import log as audit_log

        audit_log(
            action="documents.access_gate_applied",
            subject_kind="route",
            subject_id=(request.path.strip("/").split("/") or ["root"])[0][:30]
            or "root",
            actor_id=getattr(request.user, "id", None),
            actor_role=getattr(request.user, "active_role", None),
            success=False,
            reason="Mandatory policy outstanding.",
            payload={"path": request.path, "method": request.method},
        )
        wants_json = request.path.startswith("/api/") or request.headers.get(
            "Accept", ""
        ).startswith("application/json")
        if wants_json:
            return JsonResponse(
                {"detail": message, "redirect": destination}, status=403
            )
        if request.headers.get("HX-Request"):
            # HTMX swaps the body, so a bare redirect would silently replace a
            # fragment with a whole page. HX-Redirect moves the browser instead.
            from django.http import HttpResponse

            response = HttpResponse(status=200)
            response["HX-Redirect"] = destination
            return response
        return redirect(destination)
