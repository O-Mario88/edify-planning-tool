from django.urls import path

from . import views

urlpatterns = [
    # A partner's form (owner, 2026-10-14: "partners HAVE to upload because
    # that is how we verify their work"). Staff work takes no upload: the view
    # refuses it. This route was commented out on 2026-10-13 (UPLOAD-OFF) and
    # is back for partner work.
    path("upload", views.EvidenceUploadView.as_view(), name="upload"),
    path(
        "activity/<str:activity_id>/form",
        views.EvidenceFormDocumentView.as_view(),
        name="form-document",
    ),
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
