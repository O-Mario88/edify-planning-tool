from django.urls import path

from . import views

urlpatterns = [
    path("candidates", views.CoreCandidatesListView.as_view(), name="candidates"),
    path(
        "candidates/<str:school_id>/verify",
        views.CoreCandidateVerifyView.as_view(),
        name="verify",
    ),
    path(
        "candidates/<str:school_id>/reject",
        views.CoreCandidateRejectView.as_view(),
        name="reject",
    ),
    path(
        "candidates/<str:school_id>/onboard",
        views.CoreCandidateOnboardView.as_view(),
        name="onboard",
    ),
    path("plans", views.CorePlansListView.as_view(), name="plans"),
    path(
        "plans/<str:plan_id>/follow-up/schedule",
        views.CoreFollowUpScheduleView.as_view(),
        name="follow-up-schedule",
    ),
    path(
        "plans/<str:plan_id>/follow-up/ssa",
        views.CoreFollowUpSsaView.as_view(),
        name="follow-up-ssa",
    ),
    path(
        "schools/<str:school_id>", views.CoreSchoolDetailView.as_view(), name="detail"
    ),
    path(
        "schools/<str:school_id>/champion/advance",
        views.CoreChampionAdvanceView.as_view(),
        name="champion-advance",
    ),
    path(
        "slots/<str:slot_id>/<str:action>",
        views.CoreSlotActionView.as_view(),
        name="slot-action",
    ),
]
