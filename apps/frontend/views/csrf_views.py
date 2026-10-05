"""What a person sees when a request's security token is refused.

Django's own answer is a bare page reading "CSRF verification failed. Request
aborted." — true, and useless to whoever is looking at it. The usual cause here
is ordinary: Django replaces the token every time a sign-in completes, so a tab
that was open before that sign-in is holding the old one. The session-expired
dialog opens sign-in in a new tab, so this happens to people doing exactly what
they were asked to do.

Nothing here relaxes the check. The request was refused before this view ran
and stays refused; what changes is that the answer says so plainly, and leaves
the browser holding a token that works, so sending it again succeeds.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render

logger = logging.getLogger("edify.security")

# The sign-in steps. A refused token here is answered with the step's own page,
# freshly rendered: someone already signed in is sent on to their dashboard by
# that page, and anyone else gets a form that will be accepted.
SIGN_IN_STEPS = {
    "/login": (
        "/login",
        "That sign-in page had been open for a while, so it was not sent. "
        "Please sign in again.",
    ),
    "/login/verify": (
        "/login/verify",
        "This page had been open for a while, so the code was not sent. "
        "Please enter it again.",
    ),
    "/login/resend-code": (
        "/login/verify",
        "This page had been open for a while, so no new code was sent. "
        "Please ask again.",
    ),
}

NOT_SENT = (
    "Nothing was changed. This page's security check was out of date. "
    "Please try again."
)


def csrf_failure(request, reason=""):
    # Rendering a token is what makes CsrfViewMiddleware send the cookie, and
    # it is asked for on every branch — including the ones that render no
    # form — so a browser that arrived with no cookie leaves with one.
    get_token(request)
    _record(request, reason)

    if request.headers.get("HX-Request"):
        return HttpResponse(
            NOT_SENT, status=403, content_type="text/plain; charset=utf-8"
        )
    if _wants_json(request):
        return JsonResponse({"code": "csrf_failed", "detail": NOT_SENT}, status=403)

    step = SIGN_IN_STEPS.get(request.path)
    if step:
        from apps.frontend.views.auth_views import _flash

        destination, notice = step
        if not _signed_in(request):
            _flash(request, notice)
        return redirect(destination)

    return render(
        request,
        "pages/auth/request_not_sent.html",
        {"signed_in": _signed_in(request)},
        status=403,
    )


def _signed_in(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user is not None and user.is_authenticated)


def _wants_json(request) -> bool:
    if request.path.startswith("/api/"):
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _record(request, reason: str) -> None:
    """One line that says which door was refused and why.

    Django logs the reason and the path. What it leaves out is what tells a
    stale tab from a blocked cookie from a foreign origin, and that is the
    difference between "expected" and "something is wrong with the deployment".
    No token, cookie value or query string is written.
    """
    referrer = urlsplit(request.headers.get("Referer", ""))
    logger.warning(
        "csrf_rejected %s",
        json.dumps(
            {
                "reason": str(reason),
                "path": request.path,
                "method": request.method,
                "htmx": bool(request.headers.get("HX-Request")),
                "signed_in": _signed_in(request),
                "cookie": "csrftoken" in request.COOKIES,
                "origin": request.headers.get("Origin", ""),
                "referrer": f"{referrer.netloc}{referrer.path}",
            },
            sort_keys=True,
        ),
    )
