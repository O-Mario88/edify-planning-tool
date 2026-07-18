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


def _login_stats():
    """Return coarse, real operational totals for the public sign-in hero.

    The values contain no user- or school-level detail and are cached because
    the login page is public. The page never substitutes demo/fabricated
    figures when the database is empty.
    """
    from apps.schools.models import School
    from apps.activities.models import Activity
    from apps.analytics.pl_analytics_service import COMPLETED_STATUSES, VISIT_TYPES
    from apps.core.fy import get_operational_fy
    from apps.targets.models import MonthlyPersonalTarget, TargetAchievementLedger

    fy = get_operational_fy()
    cache_key = f"frontend:login-stats:{fy}"
    cached = cache.get(cache_key)
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
        "stat_schools_reached": f"{School.objects.filter(deleted_at__isnull=True).count():,}",
        "stat_field_visits": f"{completed.filter(activity_type__in=VISIT_TYPES).count():,}",
        "stat_tasks_completed": f"{task_completion_pct}%",
        "stat_target_progress": f"{target_progress_pct}%",
    }
    cache.set(cache_key, stats, timeout=300)
    return stats


def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, "must_change_password", False):
            return redirect("/change-password")
        return redirect("/dashboard")

    if request.method == "POST":
        from apps.accounts.models import User
        from apps.accounts.auth_failure_service import AuthenticationFailureService
        from apps.accounts.lockout_service import AuthenticationLockoutService

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

        django_login(request, user)

        if not remember_me:
            request.session.set_expiry(0)
        else:
            request.session.set_expiry(1209600)  # 2 weeks

        # Force password change check
        if user.must_change_password:
            return redirect("/change-password")

        messages.success(request, f"Welcome back, {user.name}!")
        return redirect("/dashboard")

    return render(request, "pages/auth/login.html", _login_stats())


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
