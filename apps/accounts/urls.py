"""Auth URL routes — mounted at /api/auth/*."""

from django.urls import path

from apps.daily_visit_batches import gateway_relay

from . import account_event_relay, security_event_relay, views

urlpatterns = [
    path("login", views.LoginView.as_view(), name="login"),
    path("login/verify", views.MfaVerifyView.as_view(), name="login-verify"),
    path("me", views.MeView.as_view(), name="me"),
    path("refresh", views.RefreshView.as_view(), name="refresh"),
    path("logout", views.LogoutView.as_view(), name="logout"),
    path("forgot-password", views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password", views.ResetPasswordView.as_view(), name="reset-password"),
    path("invite/validate", views.InviteValidateView.as_view(), name="invite-validate"),
    path("set-password", views.SetPasswordView.as_view(), name="set-password"),
    # From the Go gateway, which owns signing in (owner brief, 2026-11-11).
    path(
        "internal/security-events",
        security_event_relay.relay,
        name="security-events",
    ),
    path(
        "internal/account-events",
        account_event_relay.relay,
        name="account-events",
    ),
    # The money that follows a school visit Go saved (docs/migration/27).
    path(
        "internal/visit-day-check",
        gateway_relay.visit_day_check,
        name="visit-day-check",
    ),
    path(
        "internal/costs-to-follow",
        gateway_relay.costs_to_follow,
        name="costs-to-follow",
    ),
]
