"""Staff-setup candidate URL routes — /api/staff-candidates/*."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.StaffCandidateListView.as_view(), name="list"),
    path("<str:candidate_id>", views.StaffCandidateDetailView.as_view(), name="detail"),
    path(
        "<str:candidate_id>/create-user",
        views.StaffCandidateCreateUserView.as_view(),
        name="create-user",
    ),
    path(
        "<str:candidate_id>/match-existing-user",
        views.StaffCandidateMatchExistingView.as_view(),
        name="match-existing",
    ),
    path(
        "<str:candidate_id>/ignore",
        views.StaffCandidateIgnoreView.as_view(),
        name="ignore",
    ),
]
