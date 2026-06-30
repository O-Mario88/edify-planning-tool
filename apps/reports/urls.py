from django.urls import path

from . import views

urlpatterns = [
    path("", views.ReportListView.as_view(), name="list"),
    path("generate", views.ReportGenerateView.as_view(), name="generate"),
    path("<str:report_id>", views.ReportDetailView.as_view(), name="detail"),
]
