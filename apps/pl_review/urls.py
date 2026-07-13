from django.urls import path

from . import views

urlpatterns = [
    path("", views.PlReviewQueueView.as_view(), name="queue"),
    path(
        "<str:activity_id>/confirm", views.PlReviewConfirmView.as_view(), name="confirm"
    ),
    path("<str:activity_id>/return", views.PlReviewReturnView.as_view(), name="return"),
]
