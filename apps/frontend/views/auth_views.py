from django.shortcuts import render, redirect
from django.contrib.auth import login as django_login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


def login_view(request):
    if request.user.is_authenticated:
        if getattr(request.user, "must_change_password", False):
            return redirect("/change-password")
        return redirect("/dashboard")

    if request.method == "POST":
        from apps.accounts.models import User

        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me") == "on"

        # Look up user (including inactive, so we can track lockout state)
        user = User.objects.filter(email=email, deleted_at__isnull=True).first()

        now = timezone.now()

        # Check if account is permanently locked
        if user and user.locked_until and user.locked_until > now:
            return render(
                request,
                "pages/auth/login.html",
                {
                    "error": "This account has been locked due to too many failed login attempts. Please contact your administrator.",
                    "email": email,
                },
            )

        # Check lifecycle status
        if user and user.status not in ("active",):
            return render(
                request,
                "pages/auth/login.html",
                {"error": "Invalid email or password.", "email": email},
            )

        # Verify password
        password_ok = (
            bool(user and user.password and user.check_password(password))
            if user
            else False
        )

        if not user or not password_ok or not user.is_active:
            # Track failed attempt
            if user:
                # Same threshold source as the DRF login path
                # (auth_services._max_failed) — the two previously used
                # different hardcoded fallbacks (10 vs 5) for the same
                # setting. Lockout *duration* policy intentionally differs
                # per path and is not changed here.
                from apps.accounts.auth_services import _max_failed

                user.failed_login_count = (user.failed_login_count or 0) + 1
                max_failed = _max_failed()

                if user.failed_login_count >= max_failed:
                    # Permanent lock — set locked_until to 100 years from now
                    user.locked_until = now + timedelta(days=36500)
                    user.failed_login_count = 0
                    user.save(update_fields=["failed_login_count", "locked_until"])

                    # Notify all ADMIN users
                    _notify_admins_of_lockout(user)

                    return render(
                        request,
                        "pages/auth/login.html",
                        {
                            "error": "This account has been locked due to too many failed login attempts. Please contact your administrator.",
                            "email": email,
                        },
                    )
                else:
                    user.save(update_fields=["failed_login_count"])

            return render(
                request,
                "pages/auth/login.html",
                {"error": "Invalid email or password.", "email": email},
            )

        # Success — clear failure counter + stamp last login
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user.save(update_fields=["failed_login_count", "locked_until", "last_login_at"])

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

    return render(request, "pages/auth/login.html")


def _notify_admins_of_lockout(locked_user):
    """Create a high-priority notification for all ADMIN-role users when an account is locked."""
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService
        from apps.core.rbac import EdifyRole

        admin_users = User.objects.filter(
            roles__contains=[EdifyRole.ADMIN.value],
            is_active=True,
            deleted_at__isnull=True,
        )
        WorkflowNotificationService.trigger(
            event_type="account_lockout",
            category="general",
            priority="high",
            title=f"Account Locked: {locked_user.name}",
            body=f"{locked_user.email} has been locked after failed login attempts. Go to User Management to unlock.",
            context_type="User",
            context_id=locked_user.id,
            recipients=admin_users
        )
    except Exception:
        import logging

        logging.getLogger("edify.auth").exception(
            "Failed to notify admins of account lockout"
        )


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
