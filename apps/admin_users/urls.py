from django.urls import path

from . import views

urlpatterns = [
    path("", views.AdminUserListCreateView.as_view(), name="list"),
    path("<str:user_id>", views.AdminUserDetailAPIView.as_view(), name="detail"),
    path(
        "<str:user_id>/resend-invite",
        views.ResendInviteView.as_view(),
        name="resend-invite",
    ),
    path(
        "<str:user_id>/revoke-invite",
        views.RevokeInviteView.as_view(),
        name="revoke-invite",
    ),
    path("<str:user_id>/suspend", views.SuspendView.as_view(), name="suspend"),
    path("<str:user_id>/disable", views.DisableView.as_view(), name="disable"),
    path("<str:user_id>/reactivate", views.ReactivateView.as_view(), name="reactivate"),
    path(
        "<str:user_id>/force-password-reset",
        views.ForcePasswordResetView.as_view(),
        name="force-password-reset",
    ),
]
