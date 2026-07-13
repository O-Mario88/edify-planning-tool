"""Schools URL routes — /api/schools/*.

Route ordering matters: static segments (proposals, bulk) come BEFORE the
`:schoolId` param so they don't get captured as a schoolId. This mirrors the
NestJS controller declaration order.
"""

from django.urls import path

from . import upload_views, views

urlpatterns = [
    # Static segments first.
    path("", views.SchoolListCreateView.as_view(), name="list"),
    path("proposals", views.SchoolProposalsView.as_view(), name="proposals"),
    path("bulk", views.SchoolBulkUploadView.as_view(), name="bulk"),
    path("upload", upload_views.SchoolFileUploadView.as_view(), name="upload"),
    # Then the parametrized routes.
    path("<str:school_id>", views.SchoolDetailView.as_view(), name="detail"),
    path("<str:school_id>/impact", views.SchoolImpactView.as_view(), name="impact"),
    path(
        "<str:school_id>/workflow", views.SchoolWorkflowView.as_view(), name="workflow"
    ),
    path(
        "<str:school_id>/next-actions",
        views.SchoolNextActionsView.as_view(),
        name="next-actions",
    ),
    path(
        "<str:school_id>/cluster",
        views.SchoolClusterAssignView.as_view(),
        name="cluster",
    ),
    path("<str:school_id>/type", views.SchoolTypeView.as_view(), name="type"),
    path(
        "<str:school_id>/resolve-duplicate",
        views.SchoolResolveDuplicateView.as_view(),
        name="resolve-duplicate",
    ),
]
