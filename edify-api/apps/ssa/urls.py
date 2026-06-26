"""SSA URL routes — /api/ssa/*."""
from django.urls import path

from . import views

urlpatterns = [
    path("", views.SsaListUploadView.as_view(), name="list"),
    path("school/<str:school_id>", views.SsaSchoolHistoryView.as_view(), name="school-history"),
    path("school/<str:school_id>/recommendation", views.SsaRecommendationView.as_view(), name="recommendation"),
    path("verification-requirements", views.SsaVerificationRequirementsView.as_view(), name="verification-requirements"),
    path("verification-summary", views.SsaVerificationSummaryView.as_view(), name="verification-summary"),
]
