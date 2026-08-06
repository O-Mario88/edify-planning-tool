from django.urls import path

from . import views

urlpatterns = [
    path("roster", views.HrRosterView.as_view(), name="roster"),
    path("leave", views.HrLeaveListView.as_view(), name="leave"),
    path("leave/calendar", views.HrLeaveCalendarView.as_view(), name="leave-calendar"),
    path(
        "leave/<str:leave_id>/approve",
        views.LeaveApproveView.as_view(),
        name="leave-approve",
    ),
    path(
        "leave/<str:leave_id>/reject",
        views.LeaveRejectView.as_view(),
        name="leave-reject",
    ),
]
