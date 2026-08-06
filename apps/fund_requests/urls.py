from django.urls import path

from . import views

# Static segments (advances/*) MUST come before <str:request_id> so they aren't
# captured as a request_id.
urlpatterns = [
    path("", views.FundRequestListSubmitView.as_view(), name="list"),
    path(
        "regenerate-weekly",
        views.FundRequestRegenerateWeeklyView.as_view(),
        name="regen-weekly",
    ),
    path(
        "regenerate-monthly",
        views.FundRequestRegenerateMonthlyView.as_view(),
        name="regen-monthly",
    ),
    # Weekly advance queues + the responsible-user confirmation / Accountant
    # disbursement / accountability / reimbursement actions.
    path("advance-queues", views.AdvanceQueuesView.as_view(), name="advance-queues"),
    path(
        "advances/<str:advance_id>/confirm-advance",
        views.ConfirmAdvanceView.as_view(),
        name="advance-confirm",
    ),
    path(
        "advances/<str:advance_id>/self-funded",
        views.SelfFundedView.as_view(),
        name="advance-self-funded",
    ),
    path(
        "advances/<str:advance_id>/not-requested",
        views.NotRequestedView.as_view(),
        name="advance-not-requested",
    ),
    path(
        "advances/<str:advance_id>/disburse",
        views.AdvanceDisburseView.as_view(),
        name="advance-disburse",
    ),
    path(
        "advances/<str:advance_id>/account",
        views.AdvanceAccountView.as_view(),
        name="advance-account",
    ),
    path(
        "advances/<str:advance_id>/account-approve",
        views.AdvanceAccountApproveView.as_view(),
        name="advance-account-approve",
    ),
    path(
        "advances/<str:advance_id>/submit-reimbursement",
        views.AdvanceReimburseSubmitView.as_view(),
        name="advance-reimburse-submit",
    ),
    path(
        "advances/<str:advance_id>/reimburse",
        views.AdvanceReimburseView.as_view(),
        name="advance-reimburse",
    ),
    # Weekly fund request routes (must be declared before parametrized request_id)
    path("weekly/generate", views.WeeklyGenerateView.as_view(), name="weekly-generate"),
    path("weekly", views.WeeklyRequestListView.as_view(), name="weekly-list"),
    path(
        "weekly/<str:request_id>",
        views.WeeklyRequestDetailView.as_view(),
        name="weekly-detail",
    ),
    path(
        "weekly/<str:request_id>/request-advance",
        views.WeeklyRequestConfirmView.as_view(),
        name="weekly-request-advance",
    ),
    path(
        "weekly/<str:request_id>/self-funded",
        views.WeeklyRequestSelfFundedView.as_view(),
        name="weekly-self-funded",
    ),
    path(
        "weekly/<str:request_id>/not-requested",
        views.WeeklyRequestNotRequestedView.as_view(),
        name="weekly-not-requested",
    ),
    path(
        "weekly/<str:request_id>/disburse",
        views.WeeklyRequestDisburseView.as_view(),
        name="weekly-disburse",
    ),
    # Direct weekly request confirm routes (without weekly/ prefix)
    path(
        "<str:request_id>/request-advance",
        views.WeeklyRequestConfirmView.as_view(),
        name="weekly-request-advance-direct",
    ),
    path(
        "<str:request_id>/self-funded",
        views.WeeklyRequestSelfFundedView.as_view(),
        name="weekly-self-funded-direct",
    ),
    path(
        "<str:request_id>/not-requested",
        views.WeeklyRequestNotRequestedView.as_view(),
        name="weekly-not-requested-direct",
    ),
    # Then the parametrized fund-request routes.
    path("<str:request_id>", views.FundRequestDetailView.as_view(), name="detail"),
    path("<str:request_id>/approve", views.ApproveView.as_view(), name="approve"),
    path("<str:request_id>/return", views.ReturnView.as_view(), name="return"),
    path("<str:request_id>/reject", views.RejectView.as_view(), name="reject"),
    path("<str:request_id>/disburse", views.DisburseView.as_view(), name="disburse"),
    path("<str:request_id>/account", views.AccountView.as_view(), name="account"),
    path(
        "<str:request_id>/account-approve",
        views.AccountApproveView.as_view(),
        name="account-approve",
    ),
    path(
        "<str:request_id>/account-return",
        views.AccountReturnView.as_view(),
        name="account-return",
    ),
]
