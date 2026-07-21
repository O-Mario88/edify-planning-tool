from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden
from apps.audit.services import log as audit_log
from apps.core.permissions import (
    has_permission,
    render_access_denied,
    require_page_permission,
)
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope
from apps.schools.models import SSAImportBatch
from apps.ssa.models import SsaRecord
from apps.ssa.upload_service import upload_ssa_file, import_ssa_batch
from apps.core.enums import VerificationStatus, SsaIntervention
from django.utils import timezone
import csv


@require_page_permission("ssa_performance")
def ssa_performance_view(request):
    """Unified, role-scoped SSA intelligence workspace."""
    from apps.analytics.decision_engine import ssa_performance_dashboard

    dashboard = ssa_performance_dashboard(request.user, request.GET.dict())
    template = (
        "partials/ssa/performance_workspace.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/ssa/performance.html"
    )
    return render(request, template, {"dashboard": dashboard})


@require_page_permission("ssa_performance")
def ssa_performance_export_view(request):
    """Export the exact confirmed, filtered school set shown by the dashboard."""
    from apps.analytics.decision_engine import ssa_performance_dashboard

    dashboard = ssa_performance_dashboard(request.user, request.GET.dict())
    if not dashboard["scope"]["can_export"]:
        return HttpResponseForbidden("Your role cannot export SSA performance data.")

    fy = dashboard["filters"]["fy"]
    quarter = dashboard["filters"]["quarter"]
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="ssa-performance-fy{fy}-{quarter.lower()}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "School ID",
            "School",
            "Region",
            "District",
            "Average score",
            "Lowest intervention",
            "Lowest score",
            "High risk",
        ]
    )
    for row in dashboard["export_rows"]:
        writer.writerow(
            [
                row["school_id"],
                row["school"],
                row["region"],
                row["district"],
                row["average"],
                row["lowest_intervention"],
                row["lowest_score"],
                row["high_risk"],
            ]
        )
    return response


@require_page_permission("ssa")
def ssa_template_download_view(request):
    """Download a CSV template with the correct SSA column headers + sample rows.

    Includes two sample rows: one for last FY (baseline) and one for current FY.
    The SSA Year column controls which FY each row targets:
      "last" or a year like "2025" → previous FY (baseline, upload once)
      "current" or a year like "2026" → current FY (requires baseline first)
    """
    from apps.core.fy import get_operational_fy

    current_fy = get_operational_fy()
    prev_fy = str(int(current_fy) - 1)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ssa_upload_template.csv"'

    writer = csv.writer(response)
    # Header row
    headers = ["School ID", "Assessment Date", "SSA Year", "New Enrolment"]
    for _code, label in SsaIntervention.choices:
        headers.append(f"{label} (0-10)")
    writer.writerow(headers)

    # Sample row 1: last FY baseline
    sample_prev = ["SCH-0001", f"{prev_fy}-06-15", prev_fy, "320"]
    for _code, _label in SsaIntervention.choices:
        sample_prev.append("6.0")
    writer.writerow(sample_prev)

    # Sample row 2: current FY
    sample_curr = ["SCH-0001", f"{current_fy}-07-01", current_fy, "340"]
    for _code, _label in SsaIntervention.choices:
        sample_curr.append("7.5")
    writer.writerow(sample_curr)

    return response


def _may_upload_ssa(request) -> bool:
    """Official SSA creation requires the SSA_UPLOAD permission, not just the
    page. The page key "ssa" is open to CD/RVP/PL/CCEO for READING, but a
    staff-collected upload is born verification_status="confirmed"
    (ssa/services.py) — so page access alone let four non-IA roles mint
    official confirmed SSA without IA ever touching it. The API sibling
    already enforces ssa.upload; the frontend must match it.
    """
    return has_permission(request.user, Permission.SSA_UPLOAD.value)


@require_page_permission("ssa")
def ssa_upload_center_view(request):
    if request.method == "POST":
        if not _may_upload_ssa(request):
            messages.error(
                request, "Only Impact Assessment may upload official SSA data."
            )
            return redirect("/ssa/upload/")
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "A file is required for upload.")
            return redirect("/ssa/upload/")

        try:
            result = upload_ssa_file(file, request.user)
            # Find the newly created batch
            batch = (
                SSAImportBatch.objects.filter(uploaded_by=request.user.user_id)
                .order_by("-created_at")
                .first()
            )
            if batch:
                return redirect(f"/ssa/upload/{batch.id}/preview/")
            else:
                messages.error(request, result.get("message", "Error uploading file."))
        except Exception as e:
            messages.error(request, f"Upload error: {e}")

    return render(
        request,
        "pages/ssa/upload_center.html",
        {
            "intervention_choices": SsaIntervention.choices,
        },
    )


@require_page_permission("ssa")
def ssa_upload_preview_view(request, batch_id):
    batch = get_object_or_404(SSAImportBatch, id=batch_id)
    rows = batch.rows.all()

    if request.method == "POST":
        # The commit is the moment records are minted — same gate as upload.
        if not _may_upload_ssa(request):
            messages.error(
                request, "Only Impact Assessment may finalize an SSA import."
            )
            return redirect("/ssa")
        result = import_ssa_batch(batch, request.user)
        messages.success(
            request,
            f"Import finalized: {result['created']} records verified, {result['unmatched']} unmatched rows queued.",
        )
        return redirect(f"/ssa/upload/{batch.id}/result/")

    ready_rows = rows.filter(status="ready")
    unmatched_rows = rows.filter(status="unmatched")
    blocked_rows = rows.filter(status="blocked")

    ready_count = ready_rows.count()
    unmatched_count = unmatched_rows.count()
    blocked_count = blocked_rows.count()

    context = {
        "batch": batch,
        "ready_rows": ready_rows,
        "unmatched_rows": unmatched_rows,
        "blocked_rows": blocked_rows,
        "ready_count": ready_count,
        "unmatched_count": unmatched_count,
        "blocked_count": blocked_count,
        "total_count": ready_count + unmatched_count + blocked_count,
    }
    return render(request, "pages/ssa/upload_preview.html", context)


@require_page_permission("ssa")
def ssa_upload_result_view(request, batch_id):
    batch = get_object_or_404(SSAImportBatch, id=batch_id)
    rows = batch.rows.all()

    context = {
        "batch": batch,
        "processed": rows.count(),
        "created": rows.filter(status="ready").count(),
        "unmatched": rows.filter(status="unmatched").count(),
        "failed": rows.filter(status="blocked").count(),
        "pending_verification": rows.filter(
            status="ready"
        ).count(),  # since they land as pending
    }
    return render(request, "pages/ssa/upload_result.html", context)


@require_page_permission("ssa")
def ssa_verification_queue_view(request):
    # The "ssa" page permission is role-only. Without a scope filter this
    # listed every pending SSA record country-wide, and the POST branch below
    # accepted verify/return on any id -- so a CCEO could confirm or reject
    # another region's assessments, which then feed that region's
    # recommendations and impact numbers.
    scope = resolve_user_scope(request.user)
    records = (
        SsaRecord.objects.filter(
            deleted_at__isnull=True,
            verification_status=VerificationStatus.PENDING.value,
        )
        .select_related("school")
        .order_by("-date_of_ssa")
    )
    if not scope.country_scope:
        records = (
            records.filter(school_id__in=list(scope.school_ids or []))
            if scope.school_ids
            else records.none()
        )

    # Confirming an SSA is the QA control the entire scoring, targets and
    # impact stack rests on — it is Impact Assessment's authority, not a
    # by-product of being able to open the page. Everyone else (CD/PL/CCEO)
    # reads the queue; only ia.verify holders may act on it.
    can_verify = has_permission(request.user, Permission.IA_VERIFY.value)

    if request.method == "POST":
        if not can_verify:
            return render_access_denied(
                request,
                "Only Impact Assessment may confirm or return an SSA record.",
            )
        record_id = request.POST.get("record_id")
        action = request.POST.get("action")
        # Re-derive from the scoped queryset: taking the id straight from
        # POST would let a caller act on a record the list never showed them.
        rec = records.filter(id=record_id).first()
        if rec is None:
            raise Http404("SSA record not found.")

        if action == "verify":
            rec.verification_status = VerificationStatus.CONFIRMED.value
            rec.verified_by_user_id = request.user.user_id
            rec.verified_at = timezone.now()
            rec.save()

            # Update school status
            from apps.ssa.services import _recompute_readiness

            _recompute_readiness(rec.school)

            audit_log(
                action="ssa_verify",
                subject_kind="SsaRecord",
                subject_id=rec.id,
                actor_id=request.user.user_id,
                actor_role=getattr(request.user, "active_role", None),
                payload={"schoolId": rec.school_id, "schoolName": rec.school.name},
            )
            messages.success(
                request, f"SSA for '{rec.school.name}' has been successfully verified."
            )
        elif action == "return":
            rec.verification_status = VerificationStatus.RETURNED.value
            rec.save()

            from apps.ssa.services import _recompute_readiness

            _recompute_readiness(rec.school)

            audit_log(
                action="ssa_return",
                subject_kind="SsaRecord",
                subject_id=rec.id,
                actor_id=request.user.user_id,
                actor_role=getattr(request.user, "active_role", None),
                payload={"schoolId": rec.school_id, "schoolName": rec.school.name},
            )
            messages.warning(
                request, f"SSA for '{rec.school.name}' returned for correction."
            )

        return redirect("/ssa/verification/")

    context = {
        "records": records,
        "total_pending": records.count(),
        "can_verify": can_verify,
    }
    return render(request, "pages/ssa/verification_queue.html", context)
