"""Activities URL routes — /api/activities/*.

Static segment (payment-queue) declared before the :id param.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.ActivityListCreateView.as_view(), name="list"),
    path("schedule-school-visit", views.ScheduleSchoolVisitView.as_view(), name="schedule-school-visit"),
    path("schedule-cluster-activity", views.ScheduleClusterActivityView.as_view(), name="schedule-cluster-activity"),
    path("schedule-partner-visit", views.SchedulePartnerVisitView.as_view(), name="schedule-partner-visit"),
    path("payment-queue", views.ActivityPaymentQueueView.as_view(), name="payment-queue"),
    path("<str:activity_id>", views.ActivityDetailView.as_view(), name="detail"),
    path("<str:activity_id>/start-completion", views.StartCompletionView.as_view(), name="start-completion"),
    path("<str:activity_id>/complete", views.CompleteView.as_view(), name="complete"),
    path("<str:activity_id>/ia-confirm", views.IaConfirmView.as_view(), name="ia-confirm"),
    path("<str:activity_id>/reschedule", views.RescheduleView.as_view(), name="reschedule"),
    path("<str:activity_id>/reassign", views.ReassignView.as_view(), name="reassign"),
    path("<str:activity_id>/cancel", views.CancelView.as_view(), name="cancel"),
    path("<str:activity_id>/defer", views.DeferView.as_view(), name="defer"),
    path("<str:activity_id>/clear-payment", views.ActivityClearPaymentView.as_view(), name="clear-payment"),
]
