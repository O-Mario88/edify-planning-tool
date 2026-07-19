from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta

from django.db.models import Avg, DurationField, ExpressionWrapper, F, Q

from apps.core.permissions import require_page_permission, RolePermissionService
from apps.audit.services import log as audit_log
from apps.activities.models import (
    Activity,
    IAVerification,
    VerificationDecision,
    DuplicateActivity,
    VerificationHistory,
)
from apps.activities.ia_services import (
    IAVerificationService,
    DuplicateDetectionService,
    VerificationTimelineService,
    ActivityCertificationService,
    ActivityReturnService,
)
from apps.core.enums import ActivityStatus

QUEUE_PAGE_SIZE = 50


@require_page_permission("ia_verification_queue")
def ia_verification_queue_view(request):
    """Central queue of activities waiting for verification.

    Defense-in-depth (2026-07-15 preventive-verification mandate §11): even
    though the only paths into "awaiting_ia_verification" already require a
    Salesforce ID (apps.activities.services.complete()), this queue's own
    query excludes any activity without one — no future code path that sets
    this status can silently skip the requirement."""
    activities = (
        Activity.objects.filter(
            deleted_at__isnull=True, status="awaiting_ia_verification"
        )
        .exclude(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
        .order_by("-updated_at")
    )

    # ── KPI Strip Calculation ────────────────────────────────────────────────
    waiting_count = activities.count()

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    verified_today = VerificationHistory.objects.filter(
        verified_at__gte=today_start
    ).count()

    returned_today = VerificationDecision.objects.filter(
        decision="RETURN", decided_at__gte=today_start
    ).count()

    # Verification SLA is measured from the immutable IA-queue entry time,
    # never from Activity.updated_at (which changes during review). Limit the
    # operational headline to the latest 30 days while keeping each history
    # row available for the long-range audit view.
    sla_history = VerificationHistory.objects.filter(
        verified_at__gte=timezone.now() - timedelta(days=30),
        activity__submitted_to_ia_at__isnull=False,
    )
    turnaround = ExpressionWrapper(
        F("verified_at") - F("activity__submitted_to_ia_at"),
        output_field=DurationField(),
    )
    average_duration = sla_history.aggregate(value=Avg(turnaround))["value"]
    avg_hours = (
        round(average_duration.total_seconds() / 3600, 1)
        if average_duration is not None
        else None
    )
    sla_total = sla_history.count()
    sla_compliant_count = sla_history.filter(
        verified_at__lte=F("activity__submitted_to_ia_at") + timedelta(hours=24)
    ).count()
    sla_compliance = (
        round((sla_compliant_count / sla_total) * 100, 1) if sla_total else None
    )

    ssa_pending = activities.filter(ssa_collection_expected=True).count()
    duplicate_risks = (
        DuplicateActivity.objects.filter(status="potential")
        .values("activity_id")
        .distinct()
        .count()
    )

    # High Priority: e.g. CORE visits or trainings
    high_priority = activities.filter(
        activity_type__in=["core_visit", "core_training", "baseline_ssa_visit"]
    ).count()

    # ── Filtering ────────────────────────────────────────────────────────────
    fy_filter = request.GET.get("fy")
    quarter_filter = request.GET.get("quarter")
    month_filter = request.GET.get("month")
    region_filter = request.GET.get("region")
    district_filter = request.GET.get("district")
    cluster_filter = request.GET.get("cluster")
    school_filter = request.GET.get("school")
    staff_filter = request.GET.get("staff")
    partner_filter = request.GET.get("partner")
    type_filter = request.GET.get("activity_type")
    project_filter = request.GET.get("project")
    core_school_filter = request.GET.get("core_school")
    status_filter = request.GET.get("status")

    filtered_qs = activities

    if fy_filter:
        filtered_qs = filtered_qs.filter(fy=fy_filter)
    if quarter_filter:
        filtered_qs = filtered_qs.filter(quarter=quarter_filter)
    if month_filter:
        # Activity stores planned_month (int), not "month".
        try:
            filtered_qs = filtered_qs.filter(planned_month=int(month_filter))
        except (TypeError, ValueError):
            pass
    if region_filter:
        filtered_qs = filtered_qs.filter(school__region_id=region_filter)
    if district_filter:
        filtered_qs = filtered_qs.filter(school__district_id=district_filter)
    if cluster_filter:
        filtered_qs = filtered_qs.filter(cluster_id=cluster_filter)
    if school_filter:
        filtered_qs = filtered_qs.filter(school_id=school_filter)
    if staff_filter:
        filtered_qs = filtered_qs.filter(responsible_staff_id=staff_filter)
    if partner_filter:
        filtered_qs = filtered_qs.filter(assigned_partner_id=partner_filter)
    if type_filter:
        filtered_qs = filtered_qs.filter(activity_type=type_filter)
    if project_filter:
        filtered_qs = filtered_qs.filter(project_id=project_filter)
    if core_school_filter == "true":
        filtered_qs = filtered_qs.filter(school__school_type="core")
    if status_filter:
        filtered_qs = filtered_qs.filter(status=status_filter)

    # Serialize for template table
    from apps.activities.services import _serialize
    from django.core.paginator import Paginator

    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1
    paginator = Paginator(
        filtered_qs.select_related("school", "cluster"), QUEUE_PAGE_SIZE
    )
    page_obj = paginator.get_page(page_number)
    page_activities = list(page_obj.object_list)

    # Batch-fetch evidence/SSA existence for the CURRENT PAGE only, instead
    # of one `.exists()` query per activity per field (was unbounded: 2
    # queries x every row in the queue, not just the page being rendered).
    from apps.evidence.models import EvidenceRecord
    from apps.ssa.models import SsaRecord

    page_activity_ids = [a.id for a in page_activities]
    page_school_ids = [a.school_id for a in page_activities if a.school_id]
    activities_with_evidence = set(
        EvidenceRecord.objects.filter(
            activity_id__in=page_activity_ids, quarantined=False
        )
        .values_list("activity_id", flat=True)
        .distinct()
    )
    schools_with_ssa = set(
        SsaRecord.objects.filter(school_id__in=page_school_ids, deleted_at__isnull=True)
        .values_list("school_id", flat=True)
        .distinct()
    )

    serialized_queue = []
    for a in page_activities:
        data = _serialize(a)
        # Add quick checks recommendation
        data["has_evidence"] = a.id in activities_with_evidence
        data["has_sf_id"] = bool(a.salesforce_activity_id)
        data["has_ssa"] = bool(a.school_id) and a.school_id in schools_with_ssa
        data["is_high_priority"] = a.activity_type in [
            "core_visit",
            "core_training",
            "baseline_ssa_visit",
        ]
        serialized_queue.append(data)

    kpi_items = [
        {
            "label": "Awaiting Verification",
            "value": str(waiting_count),
            "helper": "Active certification queue",
            "icon": "clock",
            "variant": "info",
        },
        {
            "label": "Verified Today",
            "value": f"+{verified_today}",
            "helper": (
                f"{sla_compliance:g}% within 24h"
                if sla_compliance is not None
                else "SLA tracking ready"
            ),
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Returned Today",
            "value": str(returned_today),
            "helper": "Returned to field",
            "icon": "warning",
            "variant": "danger",
        },
        {
            "label": "Avg Process SLA",
            "value": f"{avg_hours:g}h" if avg_hours is not None else "—",
            "helper": (
                "30-day measured turnaround"
                if avg_hours is not None
                else "No measured cycle yet"
            ),
            "icon": "clock",
            "variant": "info",
        },
        {
            "label": "SSA Pending",
            "value": str(ssa_pending),
            "helper": "Needs collection",
            "icon": "warning",
            "variant": "warning",
        },
        {
            "label": "Duplicate Risks",
            "value": str(duplicate_risks),
            "helper": "Potential duplicates",
            "icon": "danger",
            "variant": "danger",
        },
        {
            "label": "High Priority",
            "value": str(high_priority),
            "helper": "Core visits/trainings",
            "icon": "warning",
            "variant": "warning",
        },
    ]

    context = {
        "queue": serialized_queue,
        "page_obj": page_obj,
        "kpi_strip_items": kpi_items,
        "kpis": {
            "waiting": waiting_count,
            "verified_today": verified_today,
            "returned_today": returned_today,
            "avg_time": f"{avg_hours:g}h" if avg_hours is not None else "—",
            "sla_compliance": sla_compliance,
            "sla_sample_size": sla_total,
            "ssa_pending": ssa_pending,
            "duplicate_risks": duplicate_risks,
            "high_priority": high_priority,
        },
        "filters": {
            "fy": fy_filter,
            "quarter": quarter_filter,
            "district": district_filter,
            "cluster": cluster_filter,
            "staff": staff_filter,
            "partner": partner_filter,
            "activity_type": type_filter,
        },
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "pages/ia/partials/queue_table.html", context)

    return render(request, "pages/ia/verification_queue.html", context)


@require_page_permission("ia_review_workspace")
def ia_review_workspace_view(request, activity_id):
    """Premium workspace for verifying a single activity."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)

    # Resolve checks
    checks = IAVerificationService.get_verification_checks(a)

    # Run duplicate checks
    dups = DuplicateDetectionService.detect_duplicates(a)

    # Fetch evidence records
    from apps.evidence.models import EvidenceRecord

    evidence_list = EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False)

    # Show the actual confirmed SSA values for this activity's school/FY. The
    # previous workspace displayed four invented scores whenever the generic
    # "SSA uploaded" check was true, which could mislead an IA decision.
    ssa_scores = []
    if a.school_id:
        from apps.core.enums import SsaIntervention
        from apps.ssa.models import SsaRecord

        ssa_record = (
            SsaRecord.objects.filter(
                school_id=a.school_id,
                fy=a.fy,
                verification_status="confirmed",
                deleted_at__isnull=True,
            )
            .prefetch_related("scores")
            .order_by("-date_of_ssa")
            .first()
        )
        if ssa_record:
            labels = dict(SsaIntervention.choices)
            ssa_scores = [
                {
                    "label": labels.get(score.intervention, score.intervention),
                    "value": score.score,
                }
                for score in ssa_record.scores.all().order_by("intervention")
            ]

    # Fetch timeline
    timeline = VerificationTimelineService.get_timeline(a)

    # Fetch comments
    verification = IAVerification.objects.filter(activity=a).first()
    comments = verification.comments.all() if verification else []

    # Fetch cluster schools for school-level attendance list verification
    cluster_schools = []
    if a.cluster:
        from apps.schools.models import School

        cluster_schools = list(
            School.objects.filter(
                cluster_id=a.cluster_id, deleted_at__isnull=True
            ).order_by("name")
        )

    context = {
        "act": a,
        "checks": checks,
        "duplicates": dups,
        "evidence_list": evidence_list,
        "timeline": timeline,
        "comments": comments,
        "cluster_schools": cluster_schools,
        "ssa_scores": ssa_scores,
        "suggested_reasons": [
            "Evidence missing",
            "Evidence unclear",
            "Attendance invalid",
            "Attendance missing",
            "SSA missing",
            "SSA incomplete",
            "Wrong School",
            "Wrong Cluster",
            "Wrong Intervention",
            "Wrong Activity Type",
            "Wrong Activity Date",
            "Duplicate Activity",
            "Activity SF ID missing",
            "Activity SF ID invalid",
            "Poor Data Quality",
            "Other",
        ],
    }
    return render(request, "pages/ia/review_workspace.html", context)


@require_page_permission("ia_review_workspace")
def ia_verify_action(request, activity_id):
    """POST to approve and certify the activity."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)

    if not RolePermissionService.can_verify_ia(request.user, a):
        return HttpResponseForbidden("Access Denied: Unauthorized role.")

    if request.method == "POST":
        checklist_data = {
            "evidence_exists": request.POST.get("evidence_exists") == "on",
            "attendance_valid": request.POST.get("attendance_valid") == "on",
            "ssa_uploaded": request.POST.get("ssa_uploaded") == "on",
            "correct_school": request.POST.get("correct_school") == "on",
            "correct_cluster": request.POST.get("correct_cluster") == "on",
            "correct_intervention": request.POST.get("correct_intervention") == "on",
            "sf_id_entered": request.POST.get("sf_id_entered") == "on",
            "duplicate_check_passed": request.POST.get("duplicate_check_passed")
            == "on",
            "analytics_ready": request.POST.get("analytics_ready") == "on",
        }

        try:
            ActivityCertificationService.certify_activity(
                a, checklist_data, request.user.user_id
            )

            audit_log(
                action="ia_verify_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload=checklist_data,
            )
            messages.success(
                request,
                f"Activity at {a.school.name if a.school else 'Cluster'} certified successfully!",
            )
        except Exception as e:
            messages.error(request, f"Verification failed: {e}")

    return redirect("/ia/verification/")


@require_page_permission("ia_review_workspace")
def ia_return_action(request, activity_id):
    """POST to return activity for correction."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)

    if not RolePermissionService.can_verify_ia(request.user, a):
        return HttpResponseForbidden("Access Denied: Unauthorized role.")

    if request.method == "POST":
        reasons = request.POST.getlist("reasons")
        comment = request.POST.get("comment", "").strip()

        if not reasons:
            messages.error(request, "Please select at least one return reason.")
            return redirect(f"/ia/verification/{activity_id}/")

        try:
            ActivityReturnService.return_activity(
                a, reasons, comment, request.user.user_id
            )

            audit_log(
                action="ia_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reasons": reasons, "comment": comment},
            )
            messages.success(
                request, "Activity returned to owner's plan for correction."
            )
        except Exception as e:
            messages.error(request, f"Return failed: {e}")

    return redirect("/ia/verification/")


@require_page_permission("ia_returned")
def ia_returned_view(request):
    """History of everything IA has returned."""
    returned_activities = Activity.objects.filter(
        deleted_at__isnull=True, status=ActivityStatus.RETURNED_BY_IA
    ).order_by("-updated_at")

    serialized_returned = []
    for a in returned_activities.select_related("school", "ia_verification"):
        reasons = []
        if hasattr(a, "ia_verification") and a.ia_verification:
            reasons = [rr.reason for rr in a.ia_verification.returned_reasons.all()]

        # Resubmitted is true if a CCEO edited and sent back (or if status moved away from returned_by_ia)
        # Since we filter by status=RETURNED_BY_IA, it is currently NOT resubmitted.
        serialized_returned.append(
            {
                "id": a.id,
                "activity_type_label": a.get_activity_type_display(),
                "school_name": a.school.name if a.school else "Cluster",
                "responsible_staff_name": a.responsible_staff_id or "N/A",
                "reasons": ", ".join(reasons) or "None Specified",
                "date_returned": a.updated_at,
                "status_label": a.get_status_display(),
                "resubmitted": False,
            }
        )

    context = {"returned": serialized_returned}
    return render(request, "pages/ia/returned_activities.html", context)


@require_page_permission("ia_history")
def ia_history_view(request):
    """Everything IA has verified."""
    history = (
        VerificationHistory.objects.all()
        .order_by("-verified_at")
        .select_related("activity", "activity__school")
    )

    context = {"history": history}
    return render(request, "pages/ia/verification_history.html", context)


@require_page_permission("ia_duplicates")
def ia_duplicates_view(request):
    """Duplicate review queue dashboard."""
    duplicates = DuplicateActivity.objects.filter(status="potential").select_related(
        "activity", "activity__school", "duplicate_of", "duplicate_of__school"
    )

    context = {"duplicates": duplicates}
    return render(request, "pages/ia/duplicate_review.html", context)


@require_page_permission("ia_duplicates")
def ia_duplicate_action(request, duplicate_id):
    """Handles actions on potential duplicates: merge, ignore, return, flag."""
    dup = get_object_or_404(DuplicateActivity, id=duplicate_id)
    action = request.POST.get("action")

    if action == "ignore":
        dup.status = "ignored"
        dup.save(update_fields=["status"])
        messages.success(request, "Duplicate flag ignored.")
    elif action == "flag":
        dup.status = "flagged"
        dup.save(update_fields=["status"])
        messages.success(request, "Activity flagged for investigation.")
    elif action == "return":
        # Return the target activity
        ActivityReturnService.return_activity(
            dup.activity,
            ["Duplicate Activity"],
            f"Flagged as duplicate of Activity ID {dup.duplicate_of_id}.",
            request.user.user_id,
        )
        dup.status = "resolved"
        dup.save(update_fields=["status"])
        messages.success(request, "Activity returned and duplicate flag resolved.")

    return redirect("/ia/duplicates/")


@require_page_permission("ia_dashboard")
def ia_dashboard_view(request):
    """IA Analytics Dashboard for quality monitoring — all metrics computed live."""
    from datetime import timedelta

    from django.db.models import Avg, Count
    from django.utils.timesince import timesince

    from apps.activities.models import ReturnedReason
    from apps.accounts.models import User
    from apps.core.enums import EvidenceKind, SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.evidence.models import EvidenceRecord
    from apps.geography.models import District
    from apps.partners.models import Partner
    from apps.schools.models import School, UploadBatch
    from apps.ssa.models import SsaRecord, SsaScore

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())  # Monday of current week
    week_end = week_start + timedelta(days=6)
    fy = get_operational_fy()

    PENDING_STATUSES = ["awaiting_ia_verification"]
    # Local to the IA dashboard on purpose, and NOT the platform's
    # ACHIEVED_STATUSES (ia_verified / closed / accountant_confirmed).
    # This queue asks "what work has been done and is therefore
    # verifiable", which includes `completed` work that has not yet
    # reached IA -- the whole point of the queue -- and excludes
    # accountant_confirmed, a finance state IA does not act on.
    # Renamed so it stops shadowing the shared name.
    IA_REVIEWABLE_STATUSES = ["completed", "ia_verified", "closed"]

    activities = Activity.objects.filter(deleted_at__isnull=True)
    waiting_qs = activities.filter(status__in=PENDING_STATUSES)
    waiting_cnt = waiting_qs.count()

    verified_today = VerificationHistory.objects.filter(
        verified_at__gte=today_start
    ).count()
    verified_week = VerificationHistory.objects.filter(
        verified_at__gte=week_start
    ).count()

    # Verification SLA is measured from the moment an activity enters the IA
    # queue to its recorded verification.  Keep the query bounded to the
    # current and previous week so the dashboard remains constant-cost while
    # still providing an honest week-over-week comparison.
    previous_week_start = week_start - timedelta(days=7)
    sla_rows = VerificationHistory.objects.filter(
        verified_at__gte=previous_week_start,
        verified_at__lte=now,
        activity__submitted_to_ia_at__isnull=False,
    ).values_list("verified_at", "activity__submitted_to_ia_at")
    current_sla_durations = []
    previous_sla_durations = []
    for verified_at, submitted_at in sla_rows:
        duration_hours = (verified_at - submitted_at).total_seconds() / 3600
        if verified_at >= week_start:
            current_sla_durations.append(duration_hours)
        else:
            previous_sla_durations.append(duration_hours)

    def _sla_percentage(durations):
        if not durations:
            return None
        return round(
            sum(duration <= 24 for duration in durations) / len(durations) * 100,
            1,
        )

    current_sla_pct = _sla_percentage(current_sla_durations)
    previous_sla_pct = _sla_percentage(previous_sla_durations)
    sla_delta = (
        round(current_sla_pct - previous_sla_pct, 1)
        if current_sla_pct is not None and previous_sla_pct is not None
        else None
    )
    verification_sla = {
        "pct": current_sla_pct,
        "sample_size": len(current_sla_durations),
        "previous_pct": previous_sla_pct,
        "delta": sla_delta,
    }
    returned_today = VerificationDecision.objects.filter(
        decision="RETURN", decided_at__gte=today_start
    ).count()
    returned_open_qs = activities.filter(status="returned_by_ia")
    returned_open = returned_open_qs.count()
    returned_open_school_cnt = (
        returned_open_qs.exclude(school_id__isnull=True)
        .values("school_id")
        .distinct()
        .count()
    )
    duplicate_risk_cnt = DuplicateActivity.objects.filter(status="potential").count()

    # ── Awaiting Follow-up (Grid Row 5) — real return→correction cycle time,
    # pairing each RETURN decision with the next APPROVE on the same
    # verification (a second RETURN before that APPROVE starts a new cycle).
    decision_rows = list(
        VerificationDecision.objects.filter(decision__in=("RETURN", "APPROVE"))
        .order_by("verification_id", "decided_at")
        .values("verification_id", "decision", "decided_at")
    )
    decisions_by_verification = {}
    for row in decision_rows:
        decisions_by_verification.setdefault(row["verification_id"], []).append(row)
    resolution_days = []
    for rows in decisions_by_verification.values():
        pending_return_at = None
        for row in rows:
            if row["decision"] == "RETURN":
                pending_return_at = row["decided_at"]
            elif row["decision"] == "APPROVE" and pending_return_at:
                resolution_days.append(
                    (row["decided_at"] - pending_return_at).total_seconds() / 86400
                )
                pending_return_at = None
    avg_resolution_days = (
        round(sum(resolution_days) / len(resolution_days), 1)
        if resolution_days
        else None
    )

    # ── School-derived KPIs ─────────────────────────────────────────────────
    schools = School.objects.filter(deleted_at__isnull=True)
    school_total = schools.count()
    ssa_done_cnt = schools.filter(current_fy_ssa_status="done").count()
    ssa_scheduled_cnt = schools.filter(
        current_fy_ssa_status__in=["scheduled", "partner_assigned"]
    ).count()
    ssa_not_done_cnt = school_total - ssa_done_cnt - ssa_scheduled_cnt
    ssa_coverage = round(ssa_done_cnt / school_total * 100, 1) if school_total else 0.0

    quality_avg = schools.aggregate(avg=Avg("data_quality_score"))["avg"]
    quality_pct = round(quality_avg) if quality_avg is not None else 0

    # ── Header KPI strip counts ─────────────────────────────────────────────
    missing_sf_id = (
        activities.filter(status__in=IA_REVIEWABLE_STATUSES)
        .filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
        .count()
    )
    ssa_pending_review = SsaRecord.objects.filter(
        deleted_at__isnull=True, verification_status="pending"
    ).count()
    evidence_pending = EvidenceRecord.objects.filter(
        quarantined=False, status="uploaded"
    ).count()
    uploads_today = (
        SsaRecord.objects.filter(
            deleted_at__isnull=True, created_at__gte=today_start
        ).count()
        + EvidenceRecord.objects.filter(created_at__gte=today_start).count()
    )

    kpi_items = [
        {
            "label": "Uploaded Today",
            "value": f"{uploads_today:,}",
            "helper": "Latest uploads",
            "icon": "info",
            "variant": "info",
        },
        {
            "label": "Pending Verification",
            "value": f"{waiting_cnt:,}",
            "helper": "Awaiting review",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Verified This Week",
            "value": f"{verified_week:,}",
            "helper": "Completed verifications",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Returned",
            "value": f"{returned_open:,}",
            "helper": "Awaiting correction",
            "icon": "danger",
            "variant": "danger",
        },
        {
            "label": "Data Quality Score",
            "value": f"{quality_pct}%",
            "helper": "Average quality",
            "icon": "check",
            "variant": "success",
        },
    ]

    # ── Verification work queue (5 most recent pending) ─────────────────────
    queue_activities = list(
        waiting_qs.select_related("school", "school__district").order_by("-updated_at")[
            :5
        ]
    )
    staff_ids = {
        a.responsible_staff_id for a in queue_activities if a.responsible_staff_id
    }
    staff_names = (
        dict(User.objects.filter(id__in=staff_ids).values_list("id", "name"))
        if staff_ids
        else {}
    )
    status_classes = {
        "awaiting_ia_verification": "bg-amber-50 text-amber-700 border-amber-200",
    }
    queue_items = [
        {
            "record_id": str(a.id)[-8:].upper(),
            "school": a.school.name if a.school else "Cluster",
            "district": a.school.district.name
            if a.school and a.school.district_id
            else "—",
            "activity_type": a.get_activity_type_display(),
            "submitted_by": staff_names.get(
                a.responsible_staff_id, a.responsible_staff_id or "—"
            ),
            "submission_date": timezone.localtime(a.updated_at).strftime(
                "%d %b %Y %I:%M %p"
            ),
            "status": a.get_status_display(),
            "status_class": status_classes.get(
                a.status, "bg-slate-50 text-slate-700 border-slate-200"
            ),
        }
        for a in queue_activities
    ]

    # ── District SSA completion stats (shared by exceptions + leaderboard) ──
    district_stats = list(
        District.objects.annotate(
            total=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
            done=Count(
                "schools",
                filter=Q(
                    schools__deleted_at__isnull=True,
                    schools__current_fy_ssa_status="done",
                ),
            ),
        ).filter(total__gt=0)
    )
    districts_below_target = sum(1 for d in district_stats if d.done / d.total < 0.5)

    # ── Alerts / Exceptions (only real, non-zero conditions) ────────────────
    dup_school_cnt = schools.filter(
        duplicate_status__in=["potential", "confirmed"]
    ).count()
    overdue_returns = activities.filter(
        status="returned_by_ia", updated_at__lt=now - timedelta(days=7)
    ).count()
    failed_uploads = UploadBatch.objects.filter(
        status__in=["failed", "rejected"]
    ).count()
    exceptions = [
        e
        for e in [
            {
                "count": missing_sf_id,
                "text": "completed/verified activities missing Salesforce IDs",
                "severity": "error",
            },
            {
                "count": duplicate_risk_cnt,
                "text": "activities flagged as potential duplicates",
                "severity": "warning",
            },
            {
                "count": dup_school_cnt,
                "text": "schools flagged as potential duplicates",
                "severity": "warning",
            },
            {
                "count": districts_below_target,
                "text": "districts below 50% SSA completion",
                "severity": "info",
            },
            {
                "count": overdue_returns,
                "text": "activities returned for correction over 7 days ago",
                "severity": "warning",
            },
            {
                "count": failed_uploads,
                "text": "bulk uploads failed validation",
                "severity": "error",
            },
        ]
        if e["count"] > 0
    ]

    # ── Data Quality & Compliance panel ─────────────────────────────────────
    dq_metrics = [
        {
            "label": "Schools Missing SSA",
            "value": schools.exclude(current_fy_ssa_status="done").count(),
        },
        {
            "label": "Duplicate Records Detected",
            "value": duplicate_risk_cnt + dup_school_cnt,
        },
        {
            "label": "Schools with Missing Fields",
            "value": schools.exclude(data_quality_status="Clean").count(),
        },
        {"label": "Activities Missing Salesforce IDs", "value": missing_sf_id},
    ]

    # ── SSA monitoring: lowest-performing interventions (0–10 score scale) ──
    # Confirmed-only (an unverified upload must not rank interventions), and
    # scoped strictly to the selected FY. There used to be a silent
    # all-time fallback here when the current FY had no rows, which
    # presented historical scores under a current-FY heading with nothing
    # telling the reader the period had changed — better to show an honest
    # empty state.
    score_rows = SsaScore.objects.filter(
        ssa_record__deleted_at__isnull=True,
        ssa_record__fy=fy,
        ssa_record__verification_status="confirmed",
    )
    intervention_labels = dict(SsaIntervention.choices)
    lowest_performing = [
        {
            "name": intervention_labels.get(r["intervention"], r["intervention"]),
            "rate": round(r["avg"] / 10 * 100),
        }
        for r in score_rows.values("intervention")
        .annotate(avg=Avg("score"))
        .order_by("avg")[:5]
    ]

    # ── District SSA completion leaderboard (min 5 schools) ─────────────────
    leaderboard_dc = sorted(
        (
            {"name": d.name, "rate": round(d.done / d.total * 100)}
            for d in district_stats
            if d.total >= 5
        ),
        key=lambda item: -item["rate"],
    )[:5]

    # ── SSA donuts: school coverage + record review status ──────────────────
    def _pct(part, whole):
        return round(part / whole * 100) if whole else 0

    ssa_overview = {
        "total": school_total,
        "done": ssa_done_cnt,
        "done_pct": _pct(ssa_done_cnt, school_total),
        "scheduled": ssa_scheduled_cnt,
        "scheduled_pct": _pct(ssa_scheduled_cnt, school_total),
        "not_done": ssa_not_done_cnt,
        "not_done_pct": _pct(ssa_not_done_cnt, school_total),
    }
    ssa_overview["scheduled_offset"] = -ssa_overview["done_pct"]
    ssa_overview["not_done_offset"] = -(
        ssa_overview["done_pct"] + ssa_overview["scheduled_pct"]
    )

    ssa_records = SsaRecord.objects.filter(deleted_at__isnull=True)
    ssa_rec_total = ssa_records.count()
    ssa_rec_confirmed = ssa_records.filter(verification_status="confirmed").count()
    ssa_rec_pending = ssa_records.filter(verification_status="pending").count()
    ssa_rec_other = ssa_rec_total - ssa_rec_confirmed - ssa_rec_pending
    ssa_review = {
        "total": ssa_rec_total,
        "confirmed": ssa_rec_confirmed,
        "confirmed_pct": _pct(ssa_rec_confirmed, ssa_rec_total),
        "pending": ssa_rec_pending,
        "pending_pct": _pct(ssa_rec_pending, ssa_rec_total),
        "other": ssa_rec_other,
        "other_pct": _pct(ssa_rec_other, ssa_rec_total),
    }

    # ── Evidence review panel (grouped by kind, split by review status) ─────
    kind_labels = dict(EvidenceKind.choices)
    evidence_metrics = [
        {
            "category": kind_labels.get(row["kind"], row["kind"]),
            "submitted": row["submitted"],
            "verified": row["verified"],
            "returned": row["returned"],
            "rejected": row["rejected"],
        }
        for row in EvidenceRecord.objects.filter(quarantined=False)
        .values("kind")
        .annotate(
            submitted=Count("id"),
            verified=Count("id", filter=Q(status="accepted")),
            returned=Count("id", filter=Q(status="returned")),
            rejected=Count("id", filter=Q(status="rejected")),
        )
        .order_by("-submitted")
    ]
    evidence_totals = {
        "submitted": sum(m["submitted"] for m in evidence_metrics),
        "verified": sum(m["verified"] for m in evidence_metrics),
        "returned": sum(m["returned"] for m in evidence_metrics),
        "rejected": sum(m["rejected"] for m in evidence_metrics),
    }

    # ── Recent activity feed (verifications + returns, merged by time) ──────
    def _activity_detail(a):
        school = a.school.name if a.school else "Cluster"
        district = a.school.district.name if a.school and a.school.district_id else ""
        return f"{school}, {district}" if district else school

    events = []
    for vh in VerificationHistory.objects.select_related(
        "activity", "activity__school", "activity__school__district"
    ).order_by("-verified_at")[:5]:
        events.append(
            {
                "title": f"{vh.activity.get_activity_type_display()} verified",
                "detail": _activity_detail(vh.activity),
                "ts": vh.verified_at,
            }
        )
    for vd in (
        VerificationDecision.objects.filter(decision="RETURN")
        .select_related(
            "verification__activity",
            "verification__activity__school",
            "verification__activity__school__district",
        )
        .order_by("-decided_at")[:5]
    ):
        events.append(
            {
                "title": f"{vd.verification.activity.get_activity_type_display()} returned for correction",
                "detail": _activity_detail(vd.verification.activity),
                "ts": vd.decided_at,
            }
        )
    events.sort(key=lambda e: e["ts"], reverse=True)
    recent_activities = [
        {
            "title": e["title"],
            "detail": e["detail"],
            "time": f"{timesince(e['ts'])} ago",
        }
        for e in events[:5]
    ]

    # ── Field monitoring leaderboards ───────────────────────────────────────
    pending_rows = list(
        waiting_qs.exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .values("responsible_staff_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    verifier_rows = list(
        VerificationHistory.objects.filter(verified_at__gte=week_start)
        .values("verified_by")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    fm_user_ids = {r["responsible_staff_id"] for r in pending_rows} | {
        r["verified_by"] for r in verifier_rows
    }
    fm_names = (
        dict(User.objects.filter(id__in=fm_user_ids).values_list("id", "name"))
        if fm_user_ids
        else {}
    )

    partner_rows = list(
        waiting_qs.filter(delivery_type="partner")
        .exclude(assigned_partner_id__isnull=True)
        .exclude(assigned_partner_id="")
        .values("assigned_partner_id")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    )
    partner_names = (
        dict(
            Partner.objects.filter(
                id__in=[r["assigned_partner_id"] for r in partner_rows]
            ).values_list("id", "name")
        )
        if partner_rows
        else {}
    )

    field_monitoring = {
        "highest_pending": [
            {
                "name": fm_names.get(
                    r["responsible_staff_id"], r["responsible_staff_id"]
                ),
                "count": r["c"],
            }
            for r in pending_rows
        ],
        "partner_submissions": [
            {
                "name": partner_names.get(
                    r["assigned_partner_id"], r["assigned_partner_id"]
                ),
                "count": r["c"],
            }
            for r in partner_rows
        ],
        "top_verifiers": [
            {"name": fm_names.get(r["verified_by"], r["verified_by"]), "count": r["c"]}
            for r in verifier_rows
        ],
    }

    # ── Charts: verified/returned per last 5 weekdays + return reasons ──────
    weekday_starts = []
    cursor = today_start
    while len(weekday_starts) < 5:
        if cursor.weekday() < 5:
            weekday_starts.append(cursor)
        cursor -= timedelta(days=1)
    weekday_starts.reverse()
    verification_trend = [
        {
            "date": day.strftime("%A"),
            "verified": VerificationHistory.objects.filter(
                verified_at__gte=day, verified_at__lt=day + timedelta(days=1)
            ).count(),
            "returned": VerificationDecision.objects.filter(
                decision="RETURN",
                decided_at__gte=day,
                decided_at__lt=day + timedelta(days=1),
            ).count(),
        }
        for day in weekday_starts
    ]
    return_reasons = [
        {"reason": r["reason"], "count": r["c"]}
        for r in ReturnedReason.objects.values("reason")
        .annotate(c=Count("id"))
        .order_by("-c")[:5]
    ]

    # ── Upload intake status ────────────────────────────────────────────────
    last_batch = UploadBatch.objects.order_by("-created_at").first()
    upload_status = {
        "last_upload": last_batch.created_at if last_batch else None,
        "failed": failed_uploads,
    }

    from apps.debriefs.rollup_service import field_debrief_intelligence_summary

    field_debrief_intel = field_debrief_intelligence_summary(request.user)

    context = {
        "kpis": {
            "waiting": waiting_cnt,
            "verified_today": verified_today,
            "verified_week": verified_week,
            "returned_today": returned_today,
            "returned_open": returned_open,
            "duplicate_risk": duplicate_risk_cnt,
            "ssa_coverage": f"{ssa_coverage}%",
            "quality": f"{quality_pct}%",
            "quality_pct": quality_pct,
            "uploads_today": uploads_today,
            "sf_queue": missing_sf_id,
            "ssa_pending_review": ssa_pending_review,
            "evidence_pending": evidence_pending,
        },
        "date_range": f"{week_start.strftime('%b')} {week_start.day} – {week_end.strftime('%b')} {week_end.day}, {week_end.year}",
        "kpi_strip_items": kpi_items,
        "queue_items": queue_items,
        "exceptions": exceptions,
        "dq_metrics": dq_metrics,
        "lowest_performing": lowest_performing,
        "leaderboard_dc": leaderboard_dc,
        "ssa_overview": ssa_overview,
        "ssa_review": ssa_review,
        "evidence_metrics": evidence_metrics,
        "evidence_totals": evidence_totals,
        "recent_activities": recent_activities,
        "field_monitoring": field_monitoring,
        "upload_status": upload_status,
        "returned_open_school_cnt": returned_open_school_cnt,
        "avg_resolution_days": avg_resolution_days,
        "verification_sla": verification_sla,
        "charts": {
            "verification_trend": verification_trend,
            "return_reasons": return_reasons,
        },
        "field_debrief_intel": field_debrief_intel,
    }
    return render(request, "pages/ia/analytics_dashboard.html", context)


@require_page_permission("ia_notifications")
def ia_notifications_view(request):
    """Realtime notifications audit feed page."""
    # Read notifications linked to IA from general alerts
    from apps.notifications.models import Notification

    # We can fetch notifications generated by IA triggers
    alerts = Notification.objects.filter(
        Q(title__icontains="IA")
        | Q(title__icontains="Verification")
        | Q(title__icontains="Submitted")
    ).order_by("-created_at")[:50]

    context = {"alerts": alerts}
    return render(request, "pages/ia/notifications.html", context)


@require_page_permission("ia_compare")
def ia_compare_view(request):
    """Compares planned vs actual activity fields and attached evidence side-by-side."""
    activity_id = request.GET.get("activity_id")
    a = None
    timeline = []
    evidence_list = []
    ssa_record = None

    # If no ID, get first waiting
    if not activity_id:
        first_waiting = Activity.objects.filter(
            deleted_at__isnull=True, status="awaiting_ia_verification"
        ).first()
        if first_waiting:
            activity_id = first_waiting.id

    if activity_id:
        a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
        timeline = VerificationTimelineService.get_timeline(a)
        from apps.evidence.models import EvidenceRecord

        evidence_list = EvidenceRecord.objects.filter(
            activity_id=a.id, quarantined=False
        )

        if a.school:
            from apps.ssa.models import SsaRecord

            ssa_record = (
                SsaRecord.objects.filter(school=a.school, deleted_at__isnull=True)
                .order_by("-date_of_ssa")
                .first()
            )

    waiting_list = Activity.objects.filter(
        deleted_at__isnull=True, status="awaiting_ia_verification"
    )

    context = {
        "act": a,
        "timeline": timeline,
        "evidence_list": evidence_list,
        "ssa_record": ssa_record,
        "waiting_list": waiting_list,
        "selected_activity_id": activity_id,
    }
    return render(request, "pages/ia/compare_evidence.html", context)


@require_page_permission("activity_timeline")
def activity_timeline_view(request, activity_id):
    """Visual walkthrough step-by-step history log for auditing."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    timeline = VerificationTimelineService.get_timeline(a)

    context = {"act": a, "timeline": timeline}
    return render(request, "pages/ia/activity_timeline.html", context)
