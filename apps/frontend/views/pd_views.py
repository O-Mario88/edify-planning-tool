"""My Professional Development — the one shared employee-owned workflow.

Every eligible employee reads and writes through the SAME view, SAME form and
SAME action dispatcher (`pd_action_view`, mirroring `core_schools_views`'s
`slot_action` polymorphic pattern) regardless of role — routing only changes
who reviews at each stage, resolved entirely inside the service layer. No
role-specific PD views exist anywhere in this file.
"""

from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django.shortcuts import redirect, render

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import require_export_permission, require_page_permission

from apps.professional_development.models import (
    PDCourseType,
    PDFundingType,
    ProfessionalDevelopmentRequest,
)
from apps.professional_development.services import StaffPDService, staff_display_info


def _own_request_or_404(request_id: str, user) -> ProfessionalDevelopmentRequest | None:
    sp_id = getattr(user, "staff_profile_id", None)
    return ProfessionalDevelopmentRequest.objects.filter(
        id=request_id, staff_id=sp_id
    ).first()


PD_FILE_AUTHORIZED_ROLES = (
    "HumanResources",
    "CountryDirector",
    "RegionalVicePresident",
    "Admin",
)


def _authorized_for_pd_file(req: ProfessionalDevelopmentRequest, user) -> bool:
    """Certificates/evidence are protected (§21) — visible only to the
    employee, their supervisor, and authorized HR/leadership. Files are
    stored outside any public media root and only ever reachable through
    this check — never an unprotected public URL."""
    if req.staff_id == (getattr(user, "staff_profile_id", None) or ""):
        return True
    if getattr(user, "active_role", "") in PD_FILE_AUTHORIZED_ROLES:
        return True
    from apps.accounts.models import StaffProfile
    from apps.professional_development.approval_service import PDApprovalRoutingService

    staff = StaffProfile.objects.filter(id=req.staff_id).first()
    supervisor = PDApprovalRoutingService.supervisor_for(staff) if staff else None
    return bool(supervisor and supervisor.user_id == user.user_id)


def _serve_pd_file(model_cls, file_id: str, user, download: bool):
    import os

    from django.http import FileResponse

    from apps.professional_development.uploads import pd_storage_dir

    rec = model_cls.objects.select_related("request").filter(id=file_id).first()
    if not rec or not _authorized_for_pd_file(rec.request, user):
        return HttpResponseNotFound("File not found.")
    path = os.path.join(pd_storage_dir(), rec.uri)
    if not os.path.exists(path):
        return HttpResponseNotFound("File not found on disk.")
    response = FileResponse(
        open(path, "rb"), content_type=rec.mime_type or "application/octet-stream"
    )
    inline_ok = (rec.mime_type or "").startswith(
        "image/"
    ) or rec.mime_type == "application/pdf"
    disposition = "attachment" if download or not inline_ok else "inline"
    response["Content-Disposition"] = (
        f'{disposition}; filename="{rec.original_name or rec.uri}"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_page_permission("my_professional_development")
def pd_certificate_file_view(request, file_id):
    from apps.professional_development.models import ProfessionalDevelopmentCertificate

    return _serve_pd_file(
        ProfessionalDevelopmentCertificate,
        file_id,
        request.user,
        request.GET.get("download") == "1",
    )


@require_page_permission("my_professional_development")
def pd_evidence_file_view(request, file_id):
    from apps.professional_development.models import ProfessionalDevelopmentEvidence

    return _serve_pd_file(
        ProfessionalDevelopmentEvidence,
        file_id,
        request.user,
        request.GET.get("download") == "1",
    )


@require_page_permission("my_professional_development")
def my_professional_development_view(request):
    from apps.core.fy import fy_options, get_operational_fy
    from apps.professional_development.completion_service import PDCourseTrackingService

    sp_id = getattr(request.user, "staff_profile_id", None)
    if sp_id:
        PDCourseTrackingService.sync_all(sp_id)

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    data = StaffPDService.get_page(request.user, fy=fy)
    context = {
        **data,
        "fy_options": fy_options(),
        "course_types": PDCourseType.choices,
        "funding_types": PDFundingType.choices,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/professional_development/body.html", context)
    return render(request, "pages/professional_development/index.html", context)


@require_page_permission("my_professional_development")
def pd_allocation_history_view(request):
    return render(
        request,
        "partials/professional_development/allocation_history_drawer.html",
        {
            "history": StaffPDService.allocation_history(request.user),
        },
    )


@require_page_permission("my_professional_development")
def pd_request_view(request):
    """GET: new/edit draft form drawer. POST: save draft or submit."""
    from apps.core.fy import get_operational_fy

    from apps.professional_development.approval_service import PDApprovalRoutingService
    from apps.professional_development.completion_service import (
        RETURN_REASON_TARGETS,
        PDCourseTrackingService,
    )
    from apps.professional_development.fund_service import PDFundRequestService
    from apps.professional_development.models import (
        ProfessionalDevelopmentRequest as PDR,
    )

    req_id = request.GET.get("id") or request.POST.get("id")
    sp_id = getattr(request.user, "staff_profile_id", None)
    if not sp_id:
        return HttpResponseForbidden("No staff profile on this account.")

    if request.method == "GET":
        instance = None
        reviewing = False
        if req_id:
            instance = _own_request_or_404(req_id, request.user)
            if instance is None:
                # Not the owner — allow read-only reviewer access at exactly
                # the stage this principal is entitled to act on. Anyone else
                # (wrong stage, wrong role, wrong person) still gets 404, so
                # the URL never leaks another employee's PD file.
                candidate = PDR.objects.filter(id=req_id).first()
                if candidate and (
                    PDApprovalRoutingService.can_review(candidate, request.user)
                    or PDFundRequestService.can_review(candidate, request.user)
                    or PDCourseTrackingService.can_signoff_review(
                        candidate, request.user
                    )
                ):
                    instance, reviewing = candidate, True
                else:
                    return HttpResponseNotFound("Request not found.")
        conflict = None
        if instance and instance.start_date and instance.end_date:
            conflict_user = request.user
            if reviewing:
                from apps.accounts.models import StaffProfile

                conflict_user = StaffProfile.objects.get(id=instance.staff_id).user
            conflict = StaffPDService.check_conflict(
                conflict_user, instance.start_date, instance.end_date
            )
        editable_statuses = ("draft", "returned_by_supervisor", "returned_by_hr")
        is_editable = not reviewing and (
            instance is None or instance.status in editable_statuses
        )
        balances = None
        if not reviewing:
            balances = StaffPDService.balances(
                request.user, (instance.fy if instance else get_operational_fy())
            )
        signoff_gates = None
        if instance and instance.status in ("awaiting_hr_signoff", "completed_closed"):
            signoff_gates = PDCourseTrackingService._assert_signoff_eligible(instance)
        return render(
            request,
            "partials/professional_development/request_form.html",
            {
                "instance": instance,
                "reviewing": reviewing,
                "is_editable": is_editable,
                "staff_info": staff_display_info(request.user)
                if not reviewing
                else None,
                "course_types": PDCourseType.choices,
                "funding_types": PDFundingType.choices,
                "conflict": conflict,
                "fy": get_operational_fy(),
                "balances": balances,
                "evidence": instance.evidence_files.all() if instance else [],
                "certificates": instance.certificates.all() if instance else [],
                "signoff_gates": signoff_gates,
                "return_reason_categories": list(RETURN_REASON_TARGETS.keys())
                if instance
                else [],
                "drawer_size": "lg",
            },
        )

    # POST — save draft or submit
    from apps.professional_development.approval_service import PDApprovalRoutingService

    info = staff_display_info(request.user)
    fy = request.POST.get("fy") or get_operational_fy()
    instance = _own_request_or_404(req_id, request.user) if req_id else None
    editable_statuses = ("draft", "returned_by_supervisor", "returned_by_hr")
    if instance is not None and instance.status not in editable_statuses:
        return HttpResponseBadRequest("This request can no longer be edited.")

    def _int(name, default=0):
        raw = (request.POST.get(name) or "").strip()
        try:
            return (
                int(float(raw) * 100) if raw else default
            )  # currency major units -> cents
        except ValueError:
            return default

    fields = dict(
        fy=fy,
        staff_id=info["staff_id"],
        staff_name=info["staff_name"],
        position=info["position"],
        country=info["country"],
        department=info["department"],
        supervisor_staff_id=info["supervisor_staff_id"],
        supervisor_name=info["supervisor_name"],
        course_name=(request.POST.get("course_name") or "").strip(),
        course_category=(request.POST.get("course_category") or "").strip(),
        course_type=(request.POST.get("course_type") or "").strip(),
        institution=(request.POST.get("institution") or "").strip(),
        course_link=(request.POST.get("course_link") or "").strip(),
        certification_expected=request.POST.get("certification_expected") == "on",
        course_objectives=request.POST.get("course_objectives") or "",
        skills_to_develop=request.POST.get("skills_to_develop") or "",
        relevance_to_role=request.POST.get("relevance_to_role") or "",
        expected_benefit=request.POST.get("expected_benefit") or "",
        work_time_impact=request.POST.get("work_time_impact") or "",
        notes=request.POST.get("notes") or "",
        course_fee_cents=_int("course_fee"),
        other_costs_cents=_int("other_costs"),
        employee_contribution_cents=_int("employee_contribution"),
        requested_amount_cents=_int("requested_amount"),
        funding_type=(request.POST.get("funding_type") or "self_funded").strip(),
        payment_recipient=(request.POST.get("payment_recipient") or "").strip(),
        payment_details=request.POST.get("payment_details") or "",
        exception_reason=(request.POST.get("exception_reason") or "").strip(),
        created_by=request.user.user_id,
    )
    start_raw, end_raw = request.POST.get("start_date"), request.POST.get("end_date")
    if start_raw:
        fields["start_date"] = start_raw
    if end_raw:
        fields["end_date"] = end_raw

    if instance is None:
        instance = ProfessionalDevelopmentRequest(**fields)
    else:
        for k, v in fields.items():
            if k not in ("staff_id", "created_by"):
                setattr(instance, k, v)
    instance.save()

    if request.POST.get("intent") == "submit":
        try:
            PDApprovalRoutingService.submit(instance, request.user)
            messages.success(request, "Professional Development request submitted.")
        except (BadRequest, Forbidden) as exc:
            messages.error(request, str(exc))
    else:
        messages.success(request, "Draft saved.")
    return redirect("/my-professional-development")


@require_page_permission("my_professional_development")
def pd_evidence_upload_view(request, request_id):
    from apps.professional_development.completion_service import PDCourseTrackingService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    try:
        PDCourseTrackingService.upload_evidence(
            request_id,
            request.user,
            request.FILES.get("file"),
            kind=request.POST.get("kind") or "admission_letter",
        )
        messages.success(request, "Evidence uploaded.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/my-professional-development/request?id={request_id}")


@require_page_permission("my_professional_development")
def pd_certificate_upload_view(request, request_id):
    from apps.professional_development.completion_service import PDCourseTrackingService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    try:
        PDCourseTrackingService.upload_certificate(
            request_id,
            request.user,
            request.FILES.get("file"),
            certificate_name=request.POST.get("certificate_name", ""),
            certificate_number=request.POST.get("certificate_number", ""),
            issuing_institution=request.POST.get("issuing_institution", ""),
            issue_date=request.POST.get("issue_date") or None,
            expiry_date=request.POST.get("expiry_date") or None,
            verification_link=request.POST.get("verification_link", ""),
        )
        messages.success(request, "Certificate uploaded.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/my-professional-development")


@require_page_permission("my_professional_development")
def pd_action_view(request, request_id):
    """Polymorphic action dispatcher — every non-file-upload PD action goes
    through here. Each service call enforces its own ownership/role checks;
    this view only translates the result into a redirect + message."""
    from apps.professional_development.approval_service import PDApprovalRoutingService
    from apps.professional_development.completion_service import PDCourseTrackingService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    action = (request.POST.get("action") or "").strip()
    P, note = request.user, request.POST.get("note") or request.POST.get("reason") or ""
    try:
        if action == "supervisor_approve":
            PDApprovalRoutingService.supervisor_approve(request_id, P)
            messages.success(request, "Request approved and sent to HR.")
        elif action == "supervisor_return":
            PDApprovalRoutingService.supervisor_return(request_id, P, note)
            messages.info(request, "Request returned to the employee.")
        elif action == "hr_approve":
            PDApprovalRoutingService.hr_approve(
                request_id, P, exception=request.POST.get("exception") == "true"
            )
            messages.success(request, "Request approved.")
        elif action == "hr_return":
            PDApprovalRoutingService.hr_return(request_id, P, note)
            messages.info(request, "Request returned to the employee.")
        elif action == "hr_reject":
            PDApprovalRoutingService.hr_reject(request_id, P, note)
            messages.info(request, "Request rejected.")
        elif action == "confirm_enrollment":
            enrollment_date = (
                request.POST.get("enrollment_date") or date.today().isoformat()
            )
            PDCourseTrackingService.confirm_enrollment(
                request_id,
                P,
                enrollment_date=enrollment_date,
                reference=request.POST.get("enrollment_reference", ""),
            )
            messages.success(request, "Enrollment confirmed.")
        elif action == "mark_complete":
            PDCourseTrackingService.mark_complete(
                request_id,
                P,
                actual_completion_date=request.POST.get("actual_completion_date")
                or date.today().isoformat(),
                course_outcome=request.POST.get("course_outcome", ""),
                skills_gained=request.POST.get("skills_gained", ""),
                application_plan=request.POST.get("application_plan", ""),
            )
            messages.success(request, "Marked complete — upload your certificate next.")
        elif action in ("defer", "withdraw"):
            PDCourseTrackingService.mark_deferred_or_withdrawn(
                request_id,
                P,
                outcome="deferred" if action == "defer" else "withdrawn",
                reason=note,
            )
            messages.info(request, f"Course marked {action}d.")
        elif action == "confirm_bamboohr":
            PDCourseTrackingService.confirm_bamboohr(
                request_id, P, reference=request.POST.get("bamboohr_reference", "")
            )
            messages.success(request, "BambooHR upload confirmed.")
        elif action == "verify_bamboohr":
            PDCourseTrackingService.verify_bamboohr(request_id, P)
            messages.success(request, "BambooHR upload verified.")
        elif action == "submit_accountability":

            def cents(name):
                raw = (request.POST.get(name) or "0").strip()
                try:
                    return int(float(raw) * 100)
                except ValueError:
                    return 0

            PDCourseTrackingService.submit_accountability(
                request_id,
                P,
                actual_spent=cents("actual_spent"),
                returned_amount=cents("returned_amount"),
                netsuite_expense_id=request.POST.get("netsuite_expense_id", ""),
                variance_note=request.POST.get("variance_note", ""),
            )
            messages.success(request, "Accountability submitted.")
        elif action == "sign_off":
            PDCourseTrackingService.sign_off(request_id, P)
            messages.success(request, "Course signed off and closed.")
        elif action == "hr_return_completion":
            PDCourseTrackingService.hr_return_completion(
                request_id, P, request.POST.get("reason_category", "other"), note
            )
            messages.info(request, "Completion returned to the employee.")
        elif action == "cancel":
            req = _own_request_or_404(request_id, P)
            if req is None:
                return HttpResponseForbidden("Not your request.")
            if req.status != "draft":
                return HttpResponseBadRequest("Only a draft can be cancelled.")
            req.status = "cancelled"
            req.save(update_fields=["status", "updated_at"])
            messages.info(request, "Draft cancelled.")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/my-professional-development")


@require_page_permission("my_professional_development")
def pd_fund_action_view(request, fund_request_id):
    from apps.professional_development.fund_service import PDFundRequestService

    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    action = (request.POST.get("action") or "").strip()
    try:
        if action == "disburse":
            PDFundRequestService.disburse(
                fund_request_id,
                request.user,
                method=request.POST.get("method", "bank_transfer"),
                reference=request.POST.get("reference", ""),
                notes=request.POST.get("notes", ""),
            )
            messages.success(request, "PD funds disbursed.")
        elif action == "hold":
            PDFundRequestService.hold(
                fund_request_id, request.user, request.POST.get("reason", "")
            )
            messages.info(request, "PD fund request held.")
        elif action == "return":
            PDFundRequestService.return_request(
                fund_request_id, request.user, request.POST.get("reason", "")
            )
            messages.info(request, "PD fund request returned.")
        elif action == "clear_accountability":
            PDFundRequestService.clear_accountability(
                request.POST.get("request_id"), request.user
            )
            messages.success(request, "Accountability cleared.")
        elif action == "return_accountability":
            PDFundRequestService.return_accountability(
                request.POST.get("request_id"),
                request.user,
                request.POST.get("reason", ""),
            )
            messages.info(request, "Accountability returned.")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/my-professional-development")


@require_page_permission("my_professional_development")
@require_export_permission
def pd_export_view(request):
    from django.http import HttpResponse
    from django.utils import timezone
    import csv

    from apps.core.fy import get_operational_fy

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    bal = StaffPDService.balances(request.user, fy)
    rows = StaffPDService.get_page(request.user, fy=fy)["courses"]
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="pd-report-fy{fy}.csv"'
    writer = csv.writer(resp)
    writer.writerow(
        [
            f"My Professional Development — FY {fy}",
            f"Generated {timezone.now():%d %b %Y %H:%M}",
            request.user.name,
        ]
    )
    writer.writerow([])
    writer.writerow(
        [
            f"Annual Allocation ({bal['currency']})",
            "Committed",
            "Used (Accounted)",
            "Remaining",
        ]
    )
    writer.writerow(
        [
            bal["annual_allocation"] / 100,
            bal["committed"] / 100,
            bal["accounted"] / 100,
            bal["remaining"] / 100,
        ]
    )
    writer.writerow([])
    writer.writerow(
        ["Course", "Institution", "Type", "Start", "End", "Status", "Funding Used"]
    )
    for r in rows:
        writer.writerow(
            [
                r["course_name"],
                r["institution"],
                r["course_type"],
                r["start_date"],
                r["end_date"],
                r["status"],
                r["funding_used"],
            ]
        )
    return resp
