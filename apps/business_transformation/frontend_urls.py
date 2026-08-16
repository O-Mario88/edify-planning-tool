from django.urls import path

from . import frontend_views


urlpatterns = [
    path("mfi-portal", frontend_views.mfi_portal_page, name="mfi_portal"),
    path(
        "mfi-portal/<str:section>",
        frontend_views.mfi_portal_page,
        name="mfi_portal_section",
    ),
    path("loans", frontend_views.loan_page, name="loans"),
    path("loans/<str:loan_id>/drawer", frontend_views.loan_drawer, name="loan_drawer"),
    path("loans/export.csv", frontend_views.loan_export_action, name="loan_export"),
    path("loans/save", frontend_views.loan_save_action, name="loan_save"),
    path(
        "loans/<str:loan_id>/salesforce-confirmation",
        frontend_views.salesforce_confirmation_action,
        name="loan_salesforce_confirmation",
    ),
    path(
        "loans/<str:loan_id>/salesforce-return",
        frontend_views.salesforce_return_action,
        name="loan_salesforce_return",
    ),
    path(
        "loans/<str:loan_id>/ia-validation",
        frontend_views.ia_validation_action,
        name="loan_ia_validation",
    ),
    path(
        "loans/repayment-snapshots",
        frontend_views.repayment_snapshot_save_action,
        name="loan_repayment_snapshot_save",
    ),
    path(
        "loans/<str:loan_id>/repayment-snapshots",
        frontend_views.repayment_snapshot_action,
        name="loan_repayment_snapshot",
    ),
    path(
        "business-transformation",
        frontend_views.workspace_page,
        name="business_transformation",
    ),
    path(
        "business-transformation/overview",
        frontend_views.workspace_page,
        name="business_transformation_overview",
    ),
    path(
        "business-transformation/business-accounting-finance",
        frontend_views.financial_health_page,
        name="business_transformation_finance",
    ),
    path(
        "business-transformation/government-requirements",
        frontend_views.government_requirements_page,
        name="business_transformation_government",
    ),
    path(
        "business-transformation/impact-reports",
        frontend_views.impact_reports_page,
        name="business_transformation_reports",
    ),
    path(
        "business-transformation/portfolio",
        frontend_views.portfolio_partial,
        name="business_transformation_portfolio",
    ),
    path(
        "business-transformation/cases/<str:case_id>/triage",
        frontend_views.triage_action,
        name="business_transformation_triage",
    ),
]
