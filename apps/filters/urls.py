from django.urls import path

from . import views

urlpatterns = [
    path("options", views.FilterOptionsView.as_view(), name="options"),
    path("counts", views.FilterCountsView.as_view(), name="counts"),
    path(
        "core-header-summary",
        views.CoreHeaderSummaryView.as_view(),
        name="core-header-summary",
    ),
]
