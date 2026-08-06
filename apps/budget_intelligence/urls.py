from django.urls import path

from . import views

urlpatterns = [
    path("", views.BiBoardsView.as_view(), name="boards"),
    path("snapshot", views.BiSnapshotView.as_view(), name="snapshot"),
    path("recompute", views.BiRecomputeView.as_view(), name="recompute"),
    path("insight/<str:insight_id>", views.BiInsightView.as_view(), name="insight"),
    path(
        "insight/<str:insight_id>/memo", views.BiInsightMemoView.as_view(), name="memo"
    ),
    path(
        "insight/<str:insight_id>/review",
        views.BiInsightReviewView.as_view(),
        name="review",
    ),
    path(
        "insight/<str:insight_id>/note", views.BiInsightNoteView.as_view(), name="note"
    ),
]
