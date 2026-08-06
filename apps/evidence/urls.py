from django.urls import path

from . import views

urlpatterns = [
    path("upload", views.EvidenceUploadView.as_view(), name="upload"),
    path(
        "activity/<str:activity_id>",
        views.EvidenceActivityListView.as_view(),
        name="activity-list",
    ),
    path("<str:evidence_id>/file", views.EvidenceFileView.as_view(), name="file"),
    path("<str:evidence_id>/review", views.EvidenceReviewView.as_view(), name="review"),
    path(
        "<str:evidence_id>/prepare-view",
        views.EvidencePrepareViewView.as_view(),
        name="prepare-view",
    ),
    path(
        "<str:evidence_id>/rendition",
        views.EvidenceRenditionView.as_view(),
        name="rendition",
    ),
]
