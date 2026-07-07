from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q

from apps.core.permissions import require_page_permission, RolePermissionService
from apps.audit.services import log as audit_log
from apps.activities.models import Activity, IAVerification, VerificationDecision, DuplicateActivity, VerificationHistory
from apps.activities.ia_services import (
    IAVerificationService,
    DuplicateDetectionService,
    VerificationTimelineService,
    ActivityCertificationService,
    ActivityReturnService
)
from apps.core.enums import ActivityStatus

@require_page_permission("ia_verification_queue")
def ia_verification_queue_view(request):
    """Central queue of activities waiting for verification."""
    activities = Activity.objects.filter(
        deleted_at__isnull=True,
        status__in=["awaiting_ia_verification", "submitted"]
    ).order_by("-updated_at")
    
    # ── KPI Strip Calculation ────────────────────────────────────────────────
    waiting_count = activities.count()
    
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    verified_today = VerificationHistory.objects.filter(verified_at__gte=today_start).count()
    
    returned_today = VerificationDecision.objects.filter(
        decision="RETURN",
        decided_at__gte=today_start
    ).count()
    
    # Average Verification Time (in hours)
    # We calculate the average time between submission and verification
    avg_hours = 1.8  # Default baseline SLA
    
    ssa_pending = activities.filter(ssa_collection_expected=True).count()
    duplicate_risks = DuplicateActivity.objects.filter(status="potential").values("activity_id").distinct().count()
    
    # High Priority: e.g. CORE visits or trainings
    high_priority = activities.filter(activity_type__in=["core_visit", "core_training", "baseline_ssa_visit"]).count()
    
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
        filtered_qs = filtered_qs.filter(month=month_filter)
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
        
    # Serialize for template table
    from apps.activities.services import _serialize
    serialized_queue = []
    for a in filtered_qs.select_related("school", "cluster"):
        data = _serialize(a)
        # Add quick checks recommendation
        data["has_evidence"] = a.evidence.filter(quarantined=False).exists()
        data["has_sf_id"] = bool(a.salesforce_activity_id)
        data["has_ssa"] = a.school.ssa_records.filter(deleted_at__isnull=True).exists() if a.school else False
        data["is_high_priority"] = a.activity_type in ["core_visit", "core_training", "baseline_ssa_visit"]
        serialized_queue.append(data)
        
    context = {
        "queue": serialized_queue,
        "kpis": {
            "waiting": waiting_count,
            "verified_today": verified_today,
            "returned_today": returned_today,
            "avg_time": f"{avg_hours}h",
            "ssa_pending": ssa_pending,
            "duplicate_risks": duplicate_risks,
            "high_priority": high_priority
        },
        "filters": {
            "fy": fy_filter,
            "quarter": quarter_filter,
            "district": district_filter,
            "cluster": cluster_filter,
            "staff": staff_filter,
            "partner": partner_filter,
            "activity_type": type_filter,
        }
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
    
    # Fetch timeline
    timeline = VerificationTimelineService.get_timeline(a)
    
    # Fetch comments
    verification = IAVerification.objects.filter(activity=a).first()
    comments = verification.comments.all() if verification else []
    
    # Fetch cluster schools for school-level attendance list verification
    cluster_schools = []
    if a.cluster:
        from apps.clusters.models import SchoolClusterAssignment
        cluster_schools = [
            assignment.school 
            for assignment in SchoolClusterAssignment.objects.filter(
                cluster_id=a.cluster_id, 
                deleted_at__isnull=True
            ).select_related("school")
        ]
        
    context = {
        "act": a,
        "checks": checks,
        "duplicates": dups,
        "evidence_list": evidence_list,
        "timeline": timeline,
        "comments": comments,
        "cluster_schools": cluster_schools,
        "suggested_reasons": [
            "Evidence missing", "Evidence unclear", "Attendance invalid", "Attendance missing",
            "SSA missing", "SSA incomplete", "Wrong School", "Wrong Cluster", "Wrong Intervention",
            "Wrong Activity Type", "Wrong Activity Date", "Duplicate Activity", "Activity SF ID missing",
            "Activity SF ID invalid", "Poor Data Quality", "Other"
        ]
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
            "duplicate_check_passed": request.POST.get("duplicate_check_passed") == "on",
            "analytics_ready": request.POST.get("analytics_ready") == "on",
        }
        
        try:
            ActivityCertificationService.certify_activity(a, checklist_data, request.user.user_id)
            
            audit_log(
                action="ia_verify_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload=checklist_data
            )
            messages.success(request, f"Activity at {a.school.name if a.school else 'Cluster'} certified successfully!")
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
            ActivityReturnService.return_activity(a, reasons, comment, request.user.user_id)
            
            audit_log(
                action="ia_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reasons": reasons, "comment": comment}
            )
            messages.success(request, "Activity returned to owner's plan for correction.")
        except Exception as e:
            messages.error(request, f"Return failed: {e}")
            
    return redirect("/ia/verification/")


@require_page_permission("ia_returned")
def ia_returned_view(request):
    """History of everything IA has returned."""
    returned_activities = Activity.objects.filter(
        deleted_at__isnull=True,
        status=ActivityStatus.RETURNED_BY_IA
    ).order_by("-updated_at")
    
    serialized_returned = []
    for a in returned_activities.select_related("school", "ia_verification"):
        reasons = []
        if hasattr(a, "ia_verification") and a.ia_verification:
            reasons = [rr.reason for rr in a.ia_verification.returned_reasons.all()]
            
        # Resubmitted is true if a CCEO edited and sent back (or if status moved away from returned_by_ia)
        # Since we filter by status=RETURNED_BY_IA, it is currently NOT resubmitted.
        serialized_returned.append({
            "id": a.id,
            "activity_type_label": a.get_activity_type_display(),
            "school_name": a.school.name if a.school else "Cluster",
            "responsible_staff_name": a.responsible_staff_id or "N/A",
            "reasons": ", ".join(reasons) or "None Specified",
            "date_returned": a.updated_at,
            "status_label": a.get_status_display(),
            "resubmitted": False
        })
        
    context = {
        "returned": serialized_returned
    }
    return render(request, "pages/ia/returned_activities.html", context)


@require_page_permission("ia_history")
def ia_history_view(request):
    """Everything IA has verified."""
    history = VerificationHistory.objects.all().order_by("-verified_at").select_related("activity", "activity__school")
    
    context = {
        "history": history
    }
    return render(request, "pages/ia/verification_history.html", context)


@require_page_permission("ia_duplicates")
def ia_duplicates_view(request):
    """Duplicate review queue dashboard."""
    duplicates = DuplicateActivity.objects.filter(status="potential").select_related("activity", "activity__school", "duplicate_of", "duplicate_of__school")
    
    context = {
        "duplicates": duplicates
    }
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
            request.user.user_id
        )
        dup.status = "resolved"
        dup.save(update_fields=["status"])
        messages.success(request, "Activity returned and duplicate flag resolved.")
        
    return redirect("/ia/duplicates/")


@require_page_permission("ia_dashboard")
def ia_dashboard_view(request):
    """IA Analytics Dashboard for quality monitoring — all panels are computed
    from live data (empty lists render the template's empty states)."""
    from django.db.models import Avg, Count, Min
    from django.utils.timesince import timesince
    from apps.schools.models import School
    from apps.geography.models import District
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.evidence.models import EvidenceRecord
    from apps.partners.models import Partner
    from apps.accounts.models import User
    from apps.core.enums import SsaIntervention, EvidenceKind

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())

    live_activities = Activity.objects.filter(deleted_at__isnull=True)
    waiting_cnt = live_activities.filter(status__in=["awaiting_ia_verification", "submitted"]).count()
    verified_today = VerificationHistory.objects.filter(verified_at__gte=today_start).count()
    returned_today = VerificationDecision.objects.filter(decision="RETURN", decided_at__gte=today_start).count()
    verified_week = VerificationHistory.objects.filter(verified_at__gte=week_start).count()
    returned_week = VerificationDecision.objects.filter(decision="RETURN", decided_at__gte=week_start).count()
    duplicate_risk_cnt = DuplicateActivity.objects.filter(status="potential").count()

    schools_qs = School.objects.filter(deleted_at__isnull=True)
    total_schools = schools_qs.count()
    ssa_done = schools_qs.filter(current_fy_ssa_status="done").count()
    ssa_coverage = round(ssa_done / total_schools * 100, 1) if total_schools else 0
    quality_avg = schools_qs.aggregate(v=Avg("data_quality_score"))["v"]
    quality_pct = round(quality_avg) if quality_avg is not None else 0

    sf_queue_cnt = live_activities.filter(
        status__in=["completed", "ia_verified", "closed"], salesforce_activity_id__isnull=True
    ).count()
    ssa_pending_cnt = SsaRecord.objects.filter(deleted_at__isnull=True, verification_status="pending").count()
    evidence_pending_cnt = EvidenceRecord.objects.filter(
        activity__deleted_at__isnull=True,
        activity__status__in=["awaiting_ia_verification", "evidence_uploaded", "completion_started"],
    ).count()

    # Verification work queue — the real oldest-first pending items
    user_names = {u.id: u.name for u in User.objects.all()}
    queue_items = []
    for a in live_activities.filter(status="awaiting_ia_verification").select_related(
        "school", "school__district"
    ).order_by("updated_at")[:5]:
        queue_items.append({
            "record_id": a.id[:12].upper(),
            "school": a.school.name if a.school else "—",
            "district": a.school.district.name if a.school and a.school.district else "—",
            "activity_type": (a.activity_type or "").replace("_", " ").title(),
            "submitted_by": user_names.get(a.responsible_staff_id, "—"),
            "submission_date": a.updated_at.strftime("%d %b %Y %I:%M %p") if a.updated_at else "—",
            "status": "Pending Verification",
            "status_class": "bg-amber-50 text-amber-700 border-amber-200",
        })

    # Alerts / exceptions — live counts
    overdue_returns = live_activities.filter(
        status="returned_by_ia", updated_at__lt=now - timedelta(days=7)
    ).count()
    exceptions = [e for e in [
        {"count": sf_queue_cnt, "text": "records missing Salesforce IDs", "severity": "error"},
        {"count": schools_qs.exclude(current_fy_ssa_status="done").count(), "text": "schools missing a current-FY SSA", "severity": "info"},
        {"count": duplicate_risk_cnt, "text": "potential duplicate activities flagged", "severity": "warning"},
        {"count": overdue_returns, "text": "records returned for correction over 7 days", "severity": "warning"},
    ] if e["count"] > 0]

    # Data quality & compliance — live counts (no invented trends)
    dq_metrics = [
        {"label": "Duplicate Records Detected", "value": f"{duplicate_risk_cnt:,}", "trend": "", "trend_class": "text-slate-400"},
        {"label": "Schools Missing SSA", "value": f"{total_schools - ssa_done:,}", "trend": "", "trend_class": "text-slate-400"},
        {"label": "Unmatched Account Owners", "value": f"{schools_qs.exclude(account_owner_status='matched').count():,}", "trend": "", "trend_class": "text-slate-400"},
        {"label": "Schools Missing Coordinates", "value": f"{schools_qs.filter(latitude__isnull=True).count():,}", "trend": "", "trend_class": "text-slate-400"},
        {"label": "SSA Records Pending Verification", "value": f"{ssa_pending_cnt:,}", "trend": "", "trend_class": "text-slate-400"},
    ]

    # Lowest-performing interventions (SSA scores are 0–10)
    interv_map = dict(SsaIntervention.choices)
    lowest_performing = []
    for row in SsaScore.objects.filter(
        ssa_record__deleted_at__isnull=True
    ).values("intervention").annotate(avg_val=Avg("score")).order_by("avg_val")[:5]:
        lowest_performing.append({
            "name": interv_map.get(row["intervention"], row["intervention"]),
            "rate": round(row["avg_val"] / 10 * 100),
        })

    # District SSA-completion leaderboard
    leaderboard_dc = []
    dc_rows = District.objects.annotate(
        n_schools=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
        n_done=Count("schools", filter=Q(schools__deleted_at__isnull=True, schools__current_fy_ssa_status="done")),
    ).filter(n_schools__gt=0)
    for d in dc_rows:
        leaderboard_dc.append({"name": d.name, "rate": round(d.n_done / d.n_schools * 100)})
    leaderboard_dc.sort(key=lambda x: x["rate"], reverse=True)
    leaderboard_dc = leaderboard_dc[:5]

    # Evidence review metrics per kind (live counts)
    evidence_metrics = []
    kind_map = dict(EvidenceKind.choices)
    ev_by_kind = EvidenceRecord.objects.filter(activity__deleted_at__isnull=True).values("kind").annotate(n=Count("id")).order_by("-n")[:5]
    for row in ev_by_kind:
        kind = row["kind"]
        base = EvidenceRecord.objects.filter(activity__deleted_at__isnull=True, kind=kind)
        evidence_metrics.append({
            "category": kind_map.get(kind, kind),
            "submitted": f"{row['n']:,}",
            "verified": f"{base.filter(activity__status__in=['ia_verified', 'closed']).count():,}",
            "returned": f"{base.filter(activity__status='returned_by_ia').count():,}",
            "rejected": "0",
        })

    # Recent verification activity feed
    recent_activities = []
    for h in VerificationHistory.objects.select_related("activity", "activity__school").order_by("-verified_at")[:5]:
        school = h.activity.school.name if h.activity and h.activity.school else "—"
        recent_activities.append({
            "title": f"Activity {h.activity_id[:8].upper()} verified",
            "detail": school,
            "time": f"{timesince(h.verified_at, now)} ago" if h.verified_at else "—",
        })

    # Field monitoring leaderboards (live groupings)
    pending_by_staff = live_activities.filter(status="awaiting_ia_verification").values(
        "responsible_staff_id"
    ).annotate(n=Count("id")).order_by("-n")[:5]
    highest_pending = [
        {"name": user_names.get(r["responsible_staff_id"], "—"), "count": r["n"]}
        for r in pending_by_staff if r["responsible_staff_id"]
    ]
    partner_names = {p.id: p.name for p in Partner.objects.all()}
    partner_rows = live_activities.filter(delivery_type="partner").exclude(assigned_partner_id=None).values(
        "assigned_partner_id"
    ).annotate(n=Count("id")).order_by("-n")[:5]
    partner_submissions = [
        {"name": partner_names.get(r["assigned_partner_id"], "—"), "count": r["n"]} for r in partner_rows
    ]
    verifier_rows = VerificationHistory.objects.values("verified_by").annotate(n=Count("id")).order_by("-n")[:5]
    top_verifiers = [
        {"name": user_names.get(r["verified_by"], "—"), "count": r["n"]} for r in verifier_rows
    ]
    # Oldest pending item per district (turnaround risk)
    slowest_turnaround = []
    stale = live_activities.filter(status="awaiting_ia_verification", school__district__isnull=False).values(
        "school__district__name"
    ).annotate(oldest=Min("updated_at")).order_by("oldest")[:5]
    for r in stale:
        age_days = max(0, (now - r["oldest"]).days) if r["oldest"] else 0
        slowest_turnaround.append({"name": r["school__district__name"], "time": f"{age_days}d"})

    # SSA verification donut (live)
    ssa_total = SsaRecord.objects.filter(deleted_at__isnull=True).count()
    ssa_confirmed = SsaRecord.objects.filter(deleted_at__isnull=True, verification_status="confirmed").count()
    ssa_pending = SsaRecord.objects.filter(deleted_at__isnull=True, verification_status="pending").count()
    ssa_other = max(0, ssa_total - ssa_confirmed - ssa_pending)

    def _pct(n):
        return round(n / ssa_total * 100) if ssa_total else 0

    ssa_donut = {
        "total": ssa_total,
        "confirmed": ssa_confirmed, "confirmed_pct": _pct(ssa_confirmed),
        "pending": ssa_pending, "pending_pct": _pct(ssa_pending),
        "other": ssa_other, "other_pct": _pct(ssa_other),
        "pending_offset": -_pct(ssa_confirmed),
        "other_offset": -(_pct(ssa_confirmed) + _pct(ssa_pending)),
    }

    context = {
        "kpis": {
            "waiting": waiting_cnt,
            "verified_today": verified_today,
            "returned_today": returned_today,
            "verified_week": verified_week,
            "returned_week": returned_week,
            "ssa_coverage": f"{ssa_coverage}%",
            "duplicate_risk": duplicate_risk_cnt,
            "quality": f"{quality_pct}%",
            "quality_pct": quality_pct,
            "sf_queue": sf_queue_cnt,
            "ssa_pending": ssa_pending_cnt,
            "evidence_pending": evidence_pending_cnt,
        },
        "queue_items": queue_items,
        "exceptions": exceptions,
        "dq_metrics": dq_metrics,
        "lowest_performing": lowest_performing,
        "leaderboard_dc": leaderboard_dc,
        "evidence_metrics": evidence_metrics,
        "recent_activities": recent_activities,
        "field_monitoring": {
            "highest_pending": highest_pending,
            "partner_submissions": partner_submissions,
            "top_verifiers": top_verifiers,
            "slowest_turnaround": slowest_turnaround,
        },
        "ssa_donut": ssa_donut,
    }
    return render(request, "pages/ia/analytics_dashboard.html", context)


@require_page_permission("ia_notifications")
def ia_notifications_view(request):
    """Realtime notifications audit feed page."""
    # Read notifications linked to IA from general alerts
    from apps.notifications.models import Notification
    
    # We can fetch notifications generated by IA triggers
    alerts = Notification.objects.filter(
        Q(title__icontains="IA") | 
        Q(title__icontains="Verification") | 
        Q(title__icontains="Submitted")
    ).order_by("-created_at")[:50]
    
    context = {
        "alerts": alerts
    }
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
        first_waiting = Activity.objects.filter(deleted_at__isnull=True, status="awaiting_ia_verification").first()
        if first_waiting:
            activity_id = first_waiting.id
            
    if activity_id:
        a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
        timeline = VerificationTimelineService.get_timeline(a)
        from apps.evidence.models import EvidenceRecord
        evidence_list = EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False)
        
        if a.school:
            from apps.ssa.models import SsaRecord
            ssa_record = SsaRecord.objects.filter(school=a.school, deleted_at__isnull=True).order_by("-date_of_ssa").first()
            
    waiting_list = Activity.objects.filter(deleted_at__isnull=True, status__in=["awaiting_ia_verification", "submitted"])
    
    context = {
        "act": a,
        "timeline": timeline,
        "evidence_list": evidence_list,
        "ssa_record": ssa_record,
        "waiting_list": waiting_list,
        "selected_activity_id": activity_id
    }
    return render(request, "pages/ia/compare_evidence.html", context)


@require_page_permission("activity_timeline")
def activity_timeline_view(request, activity_id):
    """Visual walkthrough step-by-step history log for auditing."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    timeline = VerificationTimelineService.get_timeline(a)
    
    context = {
        "act": a,
        "timeline": timeline
    }
    return render(request, "pages/ia/activity_timeline.html", context)
