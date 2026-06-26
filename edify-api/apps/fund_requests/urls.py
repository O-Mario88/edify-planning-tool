from django.urls import path

from . import views

urlpatterns = [
    path("", views.FundRequestListSubmitView.as_view(), name="list"),
    path("regenerate-weekly", views.FundRequestRegenerateWeeklyView.as_view(), name="regen-weekly"),
    path("regenerate-monthly", views.FundRequestRegenerateMonthlyView.as_view(), name="regen-monthly"),
    path("<str:request_id>", views.FundRequestDetailView.as_view(), name="detail"),
    path("<str:request_id>/approve", views.ApproveView.as_view(), name="approve"),
    path("<str:request_id>/return", views.ReturnView.as_view(), name="return"),
    path("<str:request_id>/reject", views.RejectView.as_view(), name="reject"),
    path("<str:request_id>/disburse", views.DisburseView.as_view(), name="disburse"),
    path("<str:request_id>/account", views.AccountView.as_view(), name="account"),
    path("<str:request_id>/account-approve", views.AccountApproveView.as_view(), name="account-approve"),
    path("<str:request_id>/account-return", views.AccountReturnView.as_view(), name="account-return"),
]
