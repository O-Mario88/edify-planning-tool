from django.urls import path

from . import views

urlpatterns = [
    path("", views.MwpList.as_view(), name="list"),
    path("<str:budget_id>", views.MwpDetail.as_view(), name="detail"),
    path(
        "<str:budget_id>/admin-lines",
        views.MwpAdminLineAdd.as_view(),
        name="admin-line-add",
    ),
    path(
        "<str:budget_id>/admin-lines/<str:line_id>",
        views.MwpAdminLineRemove.as_view(),
        name="admin-line-remove",
    ),
    path(
        "<str:budget_id>/submit-to-rvp",
        views.MwpSubmitToRvp.as_view(),
        name="submit-to-rvp",
    ),
    path(
        "<str:budget_id>/rvp-approve", views.MwpRvpApprove.as_view(), name="rvp-approve"
    ),
    path("<str:budget_id>/rvp-return", views.MwpRvpReturn.as_view(), name="rvp-return"),
    path(
        "<str:budget_id>/send-to-accountant",
        views.MwpSendToAccountant.as_view(),
        name="send-to-accountant",
    ),
]
