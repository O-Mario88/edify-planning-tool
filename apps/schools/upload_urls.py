"""Upload-batch read routes — /api/uploads/*."""

from django.urls import path

from . import upload_views

urlpatterns = [
    path("", upload_views.UploadBatchListView.as_view(), name="uploads-list"),
    path(
        "<str:batch_id>",
        upload_views.UploadBatchDetailView.as_view(),
        name="uploads-detail",
    ),
    path(
        "<str:batch_id>/rows",
        upload_views.UploadBatchRowsView.as_view(),
        name="uploads-rows",
    ),
    path(
        "<str:batch_id>/<str:action>",
        upload_views.UploadBatchActionView.as_view(),
        name="uploads-action",
    ),
]
