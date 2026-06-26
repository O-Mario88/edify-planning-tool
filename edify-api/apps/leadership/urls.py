from django.urls import path

from . import views

urlpatterns = [
    path("", views.LeadershipBoardsView.as_view(), name="boards"),
    path("snapshot", views.LeadershipSnapshotView.as_view(), name="snapshot"),
    path("recompute", views.LeadershipRecomputeView.as_view(), name="recompute"),
    path("insight/<str:insight_id>", views.LeadershipInsightView.as_view(), name="insight"),
    path("insight/<str:insight_id>/memo", views.LeadershipInsightMemoView.as_view(), name="memo"),
    path("insight/<str:insight_id>/review", views.LeadershipInsightReviewView.as_view(), name="review"),
    path("insight/<str:insight_id>/note", views.LeadershipInsightNoteView.as_view(), name="note"),
]
