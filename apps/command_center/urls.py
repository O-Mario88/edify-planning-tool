from django.urls import path

from . import views

urlpatterns = [
    path("today", views.CommandCenterTodayView.as_view(), name="today"),
    path("alerts", views.CommandCenterAlertsView.as_view(), name="alerts"),
    path(
        "alerts/summary",
        views.CommandCenterAlertsSummaryView.as_view(),
        name="alerts-summary",
    ),
    path(
        "alerts/<str:alert_id>/dismiss",
        views.CommandCenterAlertDismissView.as_view(),
        name="dismiss",
    ),
]
