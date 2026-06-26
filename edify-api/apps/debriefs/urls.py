from django.urls import path

from . import views

urlpatterns = [
    path("", views.DebriefListSubmitView.as_view(), name="list"),
    path("today", views.DebriefTodayView.as_view(), name="today"),
    path("merge-partner-debrief", views.DebriefMergePartnerView.as_view(), name="merge"),
    path("<str:debrief_id>", views.DebriefDetailView.as_view(), name="detail"),
]
