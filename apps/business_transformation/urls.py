from django.urls import path

from . import views


urlpatterns = [
    path("cases", views.CaseListView.as_view(), name="cases"),
    path("cases/<str:case_id>/triage", views.CaseTriageView.as_view(), name="triage"),
    path("mfis", views.MfiListCreateView.as_view(), name="mfis"),
    path("mfi-members", views.MfiMemberCreateView.as_view(), name="mfi-members"),
    path("referrals", views.ReferralCreateView.as_view(), name="referrals"),
    path("loan-purposes", views.LoanPurposeListView.as_view(), name="loan-purposes"),
    path(
        "referrals/<str:referral_id>/decision",
        views.ReferralDecisionView.as_view(),
        name="referral-decision",
    ),
    path("loans", views.LoanListCreateView.as_view(), name="loans"),
    path(
        "loans/<str:loan_id>/salesforce-confirmation",
        views.LoanSalesforceConfirmationView.as_view(),
        name="loan-salesforce-confirmation",
    ),
    path(
        "loans/<str:loan_id>/salesforce-return",
        views.LoanSalesforceReturnView.as_view(),
        name="loan-salesforce-return",
    ),
    path(
        "loans/<str:loan_id>/ia-validation",
        views.LoanIAValidationView.as_view(),
        name="loan-ia-validation",
    ),
    path(
        "loans/<str:loan_id>/repayment-snapshots",
        views.RepaymentSnapshotCreateView.as_view(),
        name="repayment-snapshots",
    ),
    path(
        "verification-requirements/<str:requirement_id>/activity",
        views.VerificationActivityLinkView.as_view(),
        name="verification-activity",
    ),
    path(
        "verification-requirements/<str:requirement_id>/result",
        views.LoanUseResultView.as_view(),
        name="loan-use-result",
    ),
    path("metrics", views.PortfolioMetricsView.as_view(), name="metrics"),
]
