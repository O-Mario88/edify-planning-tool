from django.urls import path

from . import views

urlpatterns = [
    path("", views.NotificationRecentView.as_view(), name="list"),
    path("recent", views.NotificationRecentView.as_view(), name="recent"),
    path("rail", views.NotificationRailView.as_view(), name="rail"),
    path("counts", views.NotificationCountsView.as_view(), name="counts"),
    path(
        "unread-count", views.NotificationUnreadCountView.as_view(), name="unread-count"
    ),
    path(
        "mark-all-read",
        views.NotificationMarkAllReadView.as_view(),
        name="mark-all-read",
    ),
    path(
        "<str:notification_id>/read", views.NotificationReadView.as_view(), name="read"
    ),
    path(
        "<str:notification_id>/resolve",
        views.NotificationResolveView.as_view(),
        name="resolve",
    ),
]
