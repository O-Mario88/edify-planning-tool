"""Partners URL routes — /api/partners/*."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.PartnerListOnboardView.as_view(), name="list"),
    path("eligible", views.PartnerEligibleView.as_view(), name="eligible"),
    path("me", views.PartnerMeView.as_view(), name="me"),
    path("me/activities", views.PartnerMeActivitiesView.as_view(), name="me-activities"),
    path("me/activities/<str:activity_id>/schedule", views.PartnerMeScheduleView.as_view(), name="me-schedule"),
    path("<str:partner_id>", views.PartnerUpdateView.as_view(), name="update"),
]
