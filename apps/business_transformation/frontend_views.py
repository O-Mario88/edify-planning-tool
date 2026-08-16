import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.permissions import (
    has_permission,
    render_access_denied,
    require_page_permission,
)
from apps.core.rbac import Permission

from . import services


def _topbar_search(request, form_id: str, placeholder: str) -> dict:
    """Bind the shell's one top-bar search to this page's filter form.

    The pages carry no body search of their own (the search-consolidation
    guard holds that line); the top-bar input joins the filter form via the
    HTML5 form= attribute, so q submits and swaps with the other filters.
    """
    return {
        "attach_to": form_id,
        "input_id": f"{form_id}-q",
        "name": "q",
        "value": (request.GET.get("q") or "").strip(),
        "placeholder": placeholder,
    }


def _filters(request) -> dict:
    return {
        key: (request.GET.get(key) or "").strip()
        for key in (
            "fy",
            "q",
            "region",
            "district",
            "mfi",
            "status",
            "period_type",
            "quarter",
            "month",
            "custom_from",
            "custom_to",
            "school",
            "purpose",
            "edtech",
            "repayment_health",
            "salesforce_status",
            "ia_status",
            "impact_status",
            "case_status",
            "partner",
            "support_status",
            "page",
            "per_page",
        )
    }


def _loan_filters(request) -> dict:
    """Return only filters represented by controls on the loan dashboard."""

    return {
        key: (request.GET.get(key) or "").strip()
        for key in (
            "fy",
            "q",
            "mfi",
            "district",
            "status",
            "repayment_health",
            "salesforce_status",
            "page",
            "per_page",
        )
    }


@require_GET
@require_page_permission("business_transformation")
def workspace_page(request):
    context = services.workspace_context(request.user, _filters(request))
    context["filter_query"] = request.GET.urlencode()
    context["topbar_search"] = _topbar_search(
        request, "bt-workspace-filters", "Search Uganda portfolio"
    )
    return render(request, "pages/business_transformation/index.html", context)


@require_GET
@require_page_permission("business_transformation_finance")
def financial_health_page(request):
    context = services.financial_health_context(request.user, _filters(request))
    context["topbar_search"] = _topbar_search(
        request, "bt-school-portfolio-filters", "Name, ID, district or owner"
    )
    context["base_template"] = (
        "layouts/blank.html"
        if request.headers.get("HX-Request") == "true"
        else "layouts/shell.html"
    )
    return render(
        request,
        "pages/business_transformation/financial_health.html",
        context,
    )


@require_GET
@require_page_permission("business_transformation_government")
def government_requirements_page(request):
    context = services.government_requirements_context(request.user, _filters(request))
    context["topbar_search"] = _topbar_search(
        request, "bt-school-portfolio-filters", "Name, ID, district or owner"
    )
    context["base_template"] = (
        "layouts/blank.html"
        if request.headers.get("HX-Request") == "true"
        else "layouts/shell.html"
    )
    return render(
        request,
        "pages/business_transformation/government_requirements.html",
        context,
    )


@require_GET
@require_page_permission("business_transformation_reports")
def impact_reports_page(request):
    return render(
        request,
        "pages/business_transformation/impact_reports.html",
        services.impact_reports_context(request.user, _filters(request)),
    )


@require_GET
@require_page_permission("mfi_portal")
def mfi_portal_page(request, section: str = "dashboard"):
    return render(
        request,
        "pages/business_transformation/mfi_portal.html",
        services.mfi_portal_context(request.user, section, _filters(request)),
    )


@require_GET
@require_page_permission("loans")
def loan_page(request):
    loan_filters = _loan_filters(request)
    context = services.loan_register_context(request.user, loan_filters)
    context["filter_query"] = urlencode(
        {
            key: value
            for key, value in loan_filters.items()
            if value and key not in {"page", "per_page"}
        }
    )
    context["topbar_search"] = _topbar_search(
        request, "bt-loan-filters", "Search Uganda loans"
    )
    return render(request, "pages/business_transformation/loans.html", context)


@require_GET
@require_page_permission("loans")
def loan_drawer(request, loan_id: str):
    loan = services.scoped_loans(request.user).filter(id=loan_id).first()
    if loan is None:
        return render_access_denied(
            request, "This loan is outside your governed scope."
        )
    return render(
        request,
        "partials/business_transformation/loan_drawer.html",
        {
            "loan": loan,
            "can_confirm_salesforce": has_permission(
                request.user,
                Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value,
            ),
            "can_validate_ia": has_permission(
                request.user, Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value
            ),
        },
    )


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


@require_GET
@require_page_permission("loans")
def loan_export_action(request):
    if not has_permission(
        request.user, Permission.BUSINESS_TRANSFORMATION_EXPORT.value
    ):
        return render_access_denied(
            request, "Your active role cannot export the Uganda loan register."
        )
    loans = services.loan_export_rows(request.user, _loan_filters(request))
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="uganda-governed-loan-register.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "Lending partner",
            "School ID",
            "School",
            "Current enrolment",
            "Loan purpose",
            "MFI loan reference",
            "Salesforce Loan ID",
            "Salesforce status",
            "Salesforce confirmed at",
            "Loan status",
            "IA validation",
            "Impact status",
            "Approved amount (UGX)",
            "Disbursed amount (UGX)",
            "Disbursement date",
            "Term months",
            "Repayment frequency",
            "Last repayment data date",
        ]
    )
    for loan in loans.iterator(chunk_size=500):
        writer.writerow(
            [
                _csv_safe(loan.mfi.name),
                _csv_safe(loan.school.school_id),
                _csv_safe(loan.school.name),
                loan.school.enrollment or "",
                _csv_safe(loan.purpose.label),
                _csv_safe(loan.external_loan_reference),
                loan.salesforce_loan_id or "",
                loan.get_salesforce_status_display(),
                loan.salesforce_confirmed_at.isoformat()
                if loan.salesforce_confirmed_at
                else "",
                loan.get_status_display(),
                loan.get_ia_validation_status_display(),
                loan.get_impact_status_display(),
                loan.approved_amount or "",
                loan.disbursed_amount or "",
                loan.disbursement_date.isoformat() if loan.disbursement_date else "",
                loan.term_months or "",
                _csv_safe(loan.repayment_frequency),
                loan.last_repayment_data_date.isoformat()
                if loan.last_repayment_data_date
                else "",
            ]
        )
    return response


@require_POST
@require_page_permission("loans")
def loan_save_action(request):
    services.register_or_update_loan(request.POST.dict(), request.user)
    messages.success(request, "Loan record saved.")
    return redirect("/loans")


@require_POST
@require_page_permission("loans")
def salesforce_confirmation_action(request, loan_id: str):
    result = services.confirm_salesforce_loan(
        loan_id, request.POST.dict(), request.user
    )
    messages.success(
        request,
        f"Salesforce Loan ID {result['salesforceLoanId']} confirmed.",
    )
    return redirect("/loans")


@require_POST
@require_page_permission("loans")
def salesforce_return_action(request, loan_id: str):
    services.return_salesforce_loan(loan_id, request.POST.dict(), request.user)
    messages.success(request, "Loan returned to the MFI for correction.")
    return redirect("/loans")


@require_POST
@require_page_permission("loans")
def ia_validation_action(request, loan_id: str):
    result = services.validate_loan_by_ia(loan_id, request.POST.dict(), request.user)
    message = (
        "Loan verified as a programme record."
        if result["iaValidationStatus"] == "verified"
        else "Loan returned for correction."
    )
    messages.success(request, message)
    return redirect("/loans")


@require_POST
@require_page_permission("loans")
def repayment_snapshot_action(request, loan_id: str):
    services.add_repayment_snapshot(loan_id, request.POST.dict(), request.user)
    messages.success(request, "Repayment snapshot recorded.")
    return redirect("/loans")


@require_POST
@require_page_permission("loans")
def repayment_snapshot_save_action(request):
    services.add_repayment_snapshot(
        request.POST.get("loanId", ""), request.POST.dict(), request.user
    )
    messages.success(request, "Repayment snapshot recorded.")
    return redirect("/loans")


@require_GET
@require_page_permission("business_transformation")
def portfolio_partial(request):
    context = services.workspace_context(request.user, _filters(request))
    return render(request, "partials/business_transformation/portfolio.html", context)


@require_POST
@require_page_permission("business_transformation")
def triage_action(request, case_id: str):
    services.triage_case(case_id, request.POST.dict(), request.user)
    messages.success(request, "Business Transformation triage decision saved.")
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Redirect"] = "/business-transformation"
        return response
    return redirect("/business-transformation")
