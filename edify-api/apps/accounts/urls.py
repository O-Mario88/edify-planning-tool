"""Auth URL routes — mounted at /api/auth/*."""
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login", views.LoginView.as_view(), name="login"),
    path("me", views.MeView.as_view(), name="me"),
    path("refresh", views.RefreshView.as_view(), name="refresh"),
    path("logout", views.LogoutView.as_view(), name="logout"),
    path("forgot-password", views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password", views.ResetPasswordView.as_view(), name="reset-password"),
    path("invite/validate", views.InviteValidateView.as_view(), name="invite-validate"),
    path("set-password", views.SetPasswordView.as_view(), name="set-password"),
]
