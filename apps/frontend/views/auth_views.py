from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import (
    authenticate,
    login as django_login,
    logout as django_logout,
)
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone
from django.views.decorators.http import require_http_methods


def _login_stats():
    """Return coarse, real operational totals for the public sign-in hero.

    The values contain no user- or school-level detail and are cached because
    the login page is public. The page never substitutes demo/fabricated
    figures when the database is empty.
    """
    from apps.schools.lifecycle_service import active_schools
    from apps.activities.models import Activity
    from apps.analytics.pl_analytics_service import COMPLETED_STATUSES, VISIT_TYPES
    from apps.core.fy import get_operational_fy
    from apps.targets.models import MonthlyPersonalTarget, TargetAchievementLedger

    fy = get_operational_fy()
    cache_key = f"frontend:login-stats:{fy}"
    # The cache is an optimisation here, never a dependency. This is the login
    # page — the one page that must stand when everything optional is down —
    # and failure injection found a cache outage turning it into a 500. A
    # raising cache degrades to computing the figures fresh.
    try:
        cached = cache.get(cache_key)
    except Exception:  # noqa: BLE001 — any cache failure means "no cache"
        cached = None
    if cached is not None:
        return cached

    current_fy_activities = Activity.objects.filter(
        deleted_at__isnull=True,
        fy=fy,
    ).exclude(status__in=("cancelled", "rejected", "deferred"))
    completed = current_fy_activities.filter(status__in=COMPLETED_STATUSES)

    total_activity_count = current_fy_activities.count()
    completed_activity_count = completed.count()
    task_completion_pct = (
        round((completed_activity_count / total_activity_count) * 100)
        if total_activity_count
        else 0
    )

    target_total = (
        MonthlyPersonalTarget.objects.filter(fy=fy).aggregate(total=Sum("target"))[
            "total"
        ]
        or 0
    )
    target_achieved = (
        TargetAchievementLedger.objects.filter(
            fy=fy,
            validation_status="validated",
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    target_progress_pct = (
        min(100, round((target_achieved / target_total) * 100)) if target_total else 0
    )

    stats = {
        # Schools the programme currently reaches, so a school that has closed
        # stops counting. The alternative reading — lifetime reach, where a
        # school worked in for three years still counts after it shuts — was
        # considered and rejected: this sits beside live figures, and a number
        # that only ever goes up next to ones that move would misread as
        # current.
        "stat_schools_reached": f"{active_schools().count():,}",
        "stat_field_visits": f"{completed.filter(activity_type__in=VISIT_TYPES).count():,}",
        "stat_tasks_completed": f"{task_completion_pct}%",
        "stat_target_progress": f"{target_progress_pct}%",
    }
    try:
        cache.set(cache_key, stats, timeout=300)
    except Exception:  # noqa: BLE001 — losing the memo costs a recompute, nothing more
        pass
    return stats


# Holds only the address someone chose to have prefilled — never a token, never
# anything that authenticates. A year is fine for a convenience of that kind.
REMEMBERED_EMAIL_COOKIE = "edify_remembered_email"
REMEMBERED_EMAIL_MAX_AGE = 365 * 24 * 60 * 60


def _remember(response, email: str | None):
    """Prefill this address next time, or stop doing so."""
    if email:
        response.set_cookie(
            REMEMBERED_EMAIL_COOKIE,
            email,
            max_age=REMEMBERED_EMAIL_MAX_AGE,
            httponly=True,
            samesite="Lax",
            secure=not settings.DEBUG,
        )
    else:
        response.delete_cookie(REMEMBERED_EMAIL_COOKIE)
    return response


def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, "must_change_password", False):
            return redirect("/change-password")
        return redirect("/dashboard")

    if request.method == "POST":
        from apps.accounts.models import User
        from apps.accounts.auth_failure_service import AuthenticationFailureService
        from apps.accounts.lockout_service import AuthenticationLockoutService
        from apps.core.throttling import throttle_by_ip

        # Per-IP ceiling, sharing the API login's budget and limit. Per-account
        # lockout already stops a brute force against one account; this is the
        # other shape — one guess each across many accounts from one address —
        # which the DRF login has always been bounded against and this door
        # was not.
        if not throttle_by_ip(
            request,
            name="auth.login",
            limit=getattr(settings, "RATE_LIMIT_LOGIN_PER_MIN", 10),
        ):
            return render(
                request,
                "pages/auth/login.html",
                {
                    "error": "Too many sign-in attempts. Please wait a minute "
                    "and try again.",
                    "email": request.POST.get("email", "").strip().lower(),
                },
                status=429,
            )

        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me") == "on"

        # Pre-check so a locked account never reaches the password compare.
        # authenticate() below re-checks this itself, so there's no
        # race/bypass between the two. The PUBLIC message is identical to
        # every other rejection below (SEC-02) — locked, wrong password, and
        # unknown email must be externally indistinguishable; only the
        # audit log (via AuthenticationFailureService) records the real cause.
        existing = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if existing:
            state = AuthenticationLockoutService.check_lockout(existing)
            if state.locked:
                message = AuthenticationFailureService.reject(
                    email=email,
                    user=existing,
                    reason="account_locked_escalated"
                    if state.escalated
                    else "account_locked",
                )
                return render(
                    request,
                    "pages/auth/login.html",
                    {
                        "error": message,
                        "email": email,
                        "remember_me": remember_me,
                        **_login_stats(),
                    },
                )

        # ONE authentication call — the LockoutEnforcingModelBackend
        # (AUTHENTICATION_BACKENDS) enforces lockout, lifecycle status, and
        # password verification, and records the failed/success outcome via
        # AuthenticationLockoutService (which also fires the admin
        # notification itself if this attempt just escalated the account —
        # uniform across every login surface, not view-specific logic).
        # Same call the DRF API login path makes
        # (apps.accounts.auth_services.login).
        user = authenticate(request, email=email, password=password)

        if user is None:
            message = AuthenticationFailureService.reject(
                email=email,
                user=existing,
                reason="invalid_password" if existing else "unknown_email",
            )
            return render(
                request,
                "pages/auth/login.html",
                {
                    "error": message,
                    "email": email,
                    "remember_me": remember_me,
                    **_login_stats(),
                },
            )

        # The second factor, if this account has one. Note what does NOT
        # happen here: django_login. A correct password moves the browser to a
        # code prompt and nothing more — the pending state below is a note
        # saying "this password checked out", not a session, and it carries no
        # authority anywhere in the product.
        from apps.accounts import mfa_service

        if mfa_service.required_for(user):
            challenge, delivery = mfa_service.start_challenge(user)
            if challenge is None:
                # Too many codes issued for this account lately. The message is
                # the same one a bad password gets: whoever is here has already
                # cleared the password, so naming the limit they hit would only
                # tell them how to pace the next run.
                return render(
                    request,
                    "pages/auth/login.html",
                    {
                        "error": AuthenticationFailureService.reject(
                            email=email,
                            user=user,
                            reason="mfa_challenge_rate_limited",
                        ),
                        "email": email,
                        "remember_me": remember_me,
                        **_login_stats(),
                    },
                )
            _begin_pending_login(request, user, challenge, remember_me)
            if not delivery.ok:
                # The prompt is still the right place to land — "Send a new
                # code" is there — but sending someone to wait for a code that
                # was never accepted, with no sign anything went wrong, is how
                # a person sits staring at an empty inbox.
                _flash(request, MFA_MESSAGES["delivery_failed"])
            return _remember(redirect("/login/verify"), email if remember_me else None)

        django_login(request, user)

        # No set_expiry() here on purpose. The session now expires after
        # SESSION_COOKIE_AGE of inactivity, and SlidingSessionMiddleware slides
        # that window forward while someone is working, so an active user is
        # never signed out mid-task. Calling set_expiry(0) would pin the
        # session to the browser tab and set_expiry(1209600) would hold it open
        # for a fortnight — both override the idle timeout, which is the whole
        # control. "Remember me" keeps the email prefilled next time; it does
        # not, and can no longer, extend how long an unattended session lives.

        # Force password change check
        if user.must_change_password:
            return _remember(
                redirect("/change-password"), email if remember_me else None
            )

        messages.success(request, f"Welcome back, {user.name}!")
        return _remember(redirect("/dashboard"), email if remember_me else None)

    # "Remember me" prefills the address it was ticked with. It deliberately
    # does not extend the session — see the login POST branch.
    return render(
        request,
        "pages/auth/login.html",
        {
            "email": request.COOKIES.get(REMEMBERED_EMAIL_COOKIE, ""),
            "remember_me": bool(request.COOKIES.get(REMEMBERED_EMAIL_COOKIE)),
            **_login_stats(),
            **_take_notice(request),
        },
    )


@require_http_methods(["GET", "POST"])
def reset_password_view(request):
    """Render and process the browser password-reset link.

    Reset emails have always targeted ``/reset-password``. The API service
    that validates and consumes the token already existed, but the browser
    route did not, so every emailed link ended at a production 404. Keep the
    mutation in the canonical service and use a regular Django POST so CSRF
    protection and a no-JavaScript fallback are both automatic.
    """
    from apps.accounts import auth_services
    from apps.core.exceptions import BadRequest

    token = (request.POST.get("token") or request.GET.get("token") or "").strip()

    if request.method == "POST":
        try:
            auth_services.reset_password(
                token,
                request.POST.get("password", ""),
                request.POST.get("confirm", ""),
            )
        except BadRequest as exc:
            return render(
                request,
                "pages/auth/reset_password.html",
                {"token": token, "error": str(exc.detail)},
            )

        _flash(
            request,
            "Your password has been reset. Sign in with your new password.",
            ok=True,
        )
        return redirect("frontend:login")

    return render(
        request,
        "pages/auth/reset_password.html",
        {
            "token": token,
            "invalid_link": not auth_services.password_reset_token_is_valid(token),
        },
    )


# ── Second factor ────────────────────────────────────────────────────────────
#
# Between a correct password and a session there is a waiting room. What sits
# in it is three values in the session — which user passed the password check,
# which challenge they must answer, and when the attempt started — and that is
# all. It is deliberately not a login: request.user is still anonymous, no
# permission check anywhere in the product consults these keys, and the only
# thing that reads them is the verification view below.
PENDING_USER = "mfa_pending_user_id"
PENDING_CHALLENGE = "mfa_pending_challenge_id"
PENDING_STARTED = "mfa_pending_started_at"
PENDING_REMEMBER = "mfa_pending_remember"

# How long the whole attempt may stay open. The code has its own, shorter life
# (mfa_service.CODE_TTL); this bounds the waiting room itself, so an abandoned
# half-login does not sit there indefinitely waiting for someone to walk up to
# the same browser.
PENDING_MAX_AGE_SECONDS = 15 * 60


# The sign-in screens are their own layout and do not render Django's message
# framework, so a `messages.error` here is written to somewhere nobody is
# looking — and then surfaces on whatever page the person opens next. These two
# carry a one-shot notice across the redirects inside the sign-in flow instead.
AUTH_NOTICE = "auth_notice"


def _flash(request, text: str, *, ok: bool = False):
    request.session[AUTH_NOTICE] = {"text": text, "ok": ok}


def _take_notice(request) -> dict:
    notice = request.session.pop(AUTH_NOTICE, None) or {}
    if not notice.get("text"):
        return {}
    return {"notice": notice["text"]} if notice.get("ok") else {"error": notice["text"]}


def _begin_pending_login(request, user, challenge, remember_me):
    # Cycle the session key before writing the pending state. Someone who
    # planted a session cookie on this browser earlier must not end up holding
    # the key to the session the login completes into.
    request.session.cycle_key()
    request.session[PENDING_USER] = str(user.id)
    request.session[PENDING_CHALLENGE] = str(challenge.id)
    request.session[PENDING_STARTED] = timezone.now().isoformat()
    request.session[PENDING_REMEMBER] = bool(remember_me)


def _clear_pending_login(request):
    for key in (PENDING_USER, PENDING_CHALLENGE, PENDING_STARTED, PENDING_REMEMBER):
        request.session.pop(key, None)


def _pending_login(request):
    """The waiting-room state, or None if there isn't a usable one."""
    user_id = request.session.get(PENDING_USER)
    challenge_id = request.session.get(PENDING_CHALLENGE)
    started = request.session.get(PENDING_STARTED)
    if not (user_id and challenge_id and started):
        return None

    try:
        began = timezone.datetime.fromisoformat(started)
    except (TypeError, ValueError):
        return None
    if (timezone.now() - began).total_seconds() > PENDING_MAX_AGE_SECONDS:
        _clear_pending_login(request)
        return None

    from apps.accounts import mfa_service

    challenge = mfa_service.open_challenge(challenge_id, user_id)
    if challenge is None:
        _clear_pending_login(request)
        return None
    return challenge


def _mfa_page(request, challenge, **extra):
    from apps.accounts import mfa_service

    return render(
        request,
        "pages/auth/mfa_verify.html",
        {
            "channel": challenge.channel,
            "destination_hint": challenge.destination_hint,
            "code_length": mfa_service.CODE_DIGITS,
            "can_resend": challenge.deliveries < mfa_service.MAX_DELIVERIES,
            **_take_notice(request),
            **extra,
        },
    )


# What the person reading the screen is told. Deliberately concrete: hiding
# whether a code was wrong or merely stale helps nobody who has the code, and
# leaves the person who mistyped it staring at the same message twice.
MFA_MESSAGES = {
    "code_incorrect": "That code is not right.",
    "code_expired": "That code has expired. Sign in again to get a new one.",
    "too_many_attempts": ("Too many incorrect codes. Sign in again to start over."),
    "already_used": "That code has already been used.",
    "resend_limit": "You have requested the maximum number of codes. Sign in again.",
    "resend_too_soon": "A code was just sent. Give it a moment before asking for another.",
    "delivery_failed": (
        "We could not send the code. Try again, or contact your administrator."
    ),
}


def mfa_verify_view(request):
    """Answer the second factor and, on success, actually sign in."""
    if request.user.is_authenticated:
        return redirect("/dashboard")

    challenge = _pending_login(request)
    if challenge is None:
        _flash(request, "Your sign-in attempt expired. Please start again.")
        return redirect("/login")

    if request.method != "POST":
        return _mfa_page(request, challenge)

    from apps.accounts import mfa_service
    from apps.audit.services import log as audit_log

    result = mfa_service.verify(challenge, request.POST.get("code", ""))
    user = challenge.user

    audit_log(
        action="mfa_verify",
        subject_kind="User",
        subject_id=str(user.id),
        actor_id=str(user.id),
        actor_role=user.active_role,
        success=result.ok,
        reason="" if result.ok else result.reason,
        payload={"channel": challenge.channel},
    )

    if not result.ok:
        # A dead challenge cannot be answered again, so the waiting room is
        # cleared and the person starts from the password. Leaving it open
        # would be an unauthenticated page that keeps accepting guesses.
        if result.reason in (
            mfa_service.TOO_MANY_ATTEMPTS,
            mfa_service.CODE_EXPIRED,
            mfa_service.ALREADY_USED,
        ):
            _clear_pending_login(request)
            _flash(request, MFA_MESSAGES[result.reason])
            return redirect("/login")
        return _mfa_page(
            request,
            challenge,
            error=MFA_MESSAGES[result.reason],
            attempts_left=result.attempts_left,
        )

    remember_me = bool(request.session.get(PENDING_REMEMBER))
    _clear_pending_login(request)
    # django_login cycles the session key again, so the identifier the waiting
    # room was held under is not the one the signed-in session uses.
    django_login(request, user)

    if user.must_change_password:
        return _remember(
            redirect("/change-password"), user.email if remember_me else None
        )
    messages.success(request, f"Welcome back, {user.name}!")
    return _remember(redirect("/dashboard"), user.email if remember_me else None)


@require_POST
def mfa_resend_view(request):
    """Send another code for the attempt already in progress."""
    challenge = _pending_login(request)
    if challenge is None:
        _flash(request, "Your sign-in attempt expired. Please start again.")
        return redirect("/login")

    from apps.accounts import mfa_service

    delivery = mfa_service.resend(challenge)
    if delivery.ok:
        _flash(request, f"A new code is on its way to {delivery.hint}.", ok=True)
    else:
        _flash(
            request,
            MFA_MESSAGES.get(delivery.reason, MFA_MESSAGES["delivery_failed"]),
        )
    return redirect("/login/verify")


@login_required(login_url="/login")
@require_POST
def mfa_settings_view(request):
    """Turn the second factor on or off for yourself, and choose the channel."""
    from apps.accounts import mfa_service
    from apps.audit.services import log as audit_log

    user = request.user
    enable = request.POST.get("mfa_enabled") == "on"
    channel = request.POST.get("mfa_channel", mfa_service.EMAIL_CHANNEL)

    if getattr(settings, "MFA_REQUIRED_FOR_ALL", False) and not enable:
        messages.error(
            request,
            "Two-step verification is required for every account here and "
            "cannot be turned off.",
        )
        return redirect("/settings")

    # Never enrol onto a channel that cannot deliver — that is not a security
    # control, it is a lockout with a confirmation message.
    if channel not in mfa_service.available_channels(user):
        channel = mfa_service.EMAIL_CHANNEL

    user.mfa_enabled = enable
    user.mfa_channel = channel
    user.save(update_fields=["mfa_enabled", "mfa_channel", "updated_at"])

    audit_log(
        action="mfa_enrolment_changed",
        subject_kind="User",
        subject_id=str(user.id),
        actor_id=str(user.id),
        actor_role=user.active_role,
        success=True,
        payload={"enabled": enable, "channel": channel},
    )

    if enable:
        _, hint = mfa_service.destination_for(user, channel)
        messages.success(
            request,
            f"Two-step verification is on. Codes will go to {hint}.",
        )
    else:
        messages.success(request, "Two-step verification is off.")
    return redirect("/settings")


@require_POST
def logout_view(request):
    django_logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("/login")


@login_required(login_url="/login")
@require_POST
def switch_role_view(request):
    role = request.POST.get("role")
    user = request.user
    if role in user.roles:
        old_role = user.active_role
        user.active_role = role
        user.save()
        from apps.audit.services import log as audit_log

        audit_log(
            action="role_switch",
            subject_kind="User",
            subject_id=str(user.id),
            actor_id=str(user.id),
            actor_role=role,
            success=True,
            payload={"old_role": old_role, "new_role": role},
        )
        messages.success(request, f"Switched active role to {role}.")
    else:
        from apps.audit.services import log as audit_log

        audit_log(
            action="role_switch",
            subject_kind="User",
            subject_id=str(user.id),
            actor_id=str(user.id),
            actor_role=user.active_role,
            success=False,
            reason=f"User attempted to switch to invalid/unassigned role: {role}",
            payload={"requested_role": role},
        )
        messages.error(request, "Access restricted: Invalid role request.")
    return redirect("/dashboard")


@login_required(login_url="/login")
def force_change_password_view(request):
    """Force password change page. Users with must_change_password=True
    are redirected here and cannot navigate away until they set a new password."""
    user = request.user

    # If the user doesn't need to change password, redirect to dashboard
    if not user.must_change_password:
        return redirect("/dashboard")

    if request.method == "POST":
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")

        if new_password != confirm_password:
            return render(
                request,
                "pages/auth/change_password.html",
                {"error": "Passwords do not match."},
            )

        from apps.core.security import validate_password

        violations = validate_password(new_password, user.email)
        if violations:
            return render(
                request,
                "pages/auth/change_password.html",
                {"error": " ".join(violations)},
            )

        user.set_password(new_password)
        user.must_change_password = False
        user.password_set_at = timezone.now()
        user.save(update_fields=["password", "must_change_password", "password_set_at"])

        # Re-authenticate the user so the session stays valid after password change
        django_login(request, user)

        messages.success(
            request, "Your password has been updated successfully. Welcome!"
        )
        return redirect("/dashboard")

    return render(request, "pages/auth/change_password.html")
