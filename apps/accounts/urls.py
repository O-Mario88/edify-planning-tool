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
    # The money a move of that visit meets (docs/migration/29).
    path(
        "internal/visit-move-check",
        gateway_relay.visit_move_check,
        name="visit-move-check",
    ),
    # The money a cancel of that visit meets (docs/migration/30).
    path(
        "internal/visit-cancel-check",
        gateway_relay.visit_cancel_check,
        name="visit-cancel-check",
    ),
    # What a group reschedule or cancel would do (docs/migration/33).
    path(
        "internal/visit-group-check",
        gateway_relay.visit_group_check,
        name="visit-group-check",
    ),
    # An activity Go saved with no costs to follow, said on the realtime
    # stream (docs/migration/31).
    path(
        "internal/activity-changed",
        gateway_relay.activity_changed,
        name="activity-changed",
    ),
    # What follows a school visit's completion Go made (docs/migration/183).
    path(
        "internal/visit-completed",
        gateway_relay.visit_completed,
        name="visit-completed",
    ),
    path(
        "internal/costs-to-follow",
        gateway_relay.costs_to_follow,
        name="costs-to-follow",
    ),
]
