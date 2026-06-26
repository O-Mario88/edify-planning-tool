from django.urls import path

from . import views

urlpatterns = [
    path("time-period", views.TargetTimePeriodView.as_view(), name="time-period"),
    path("summary", views.TargetSummaryView.as_view(), name="summary"),
    path("", views.TargetListSetView.as_view(), name="list"),
]
