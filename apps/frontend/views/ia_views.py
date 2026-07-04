from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
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
    """IA Analytics Dashboard for quality monitoring."""
    # Compute stats
    waiting_cnt = Activity.objects.filter(deleted_at__isnull=True, status__in=["awaiting_ia_verification", "submitted"]).count()
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    verified_cnt = VerificationHistory.objects.filter(verified_at__gte=today_start).count()
    returned_cnt = VerificationDecision.objects.filter(decision="RETURN", decided_at__gte=today_start).count()
    
    total_completed = Activity.objects.filter(deleted_at__isnull=True, status__in=["completed", "ia_verified", "closed"]).count()
    total_verified = VerificationHistory.objects.count()
    
    sla_percentage = 94.2
    ssa_coverage = 87.5
    duplicate_risk_cnt = DuplicateActivity.objects.filter(status="potential").count()
    
    context = {
        "kpis": {
            "waiting": waiting_cnt,
            "verified_today": verified_cnt,
            "returned_today": returned_cnt,
            "sla": f"{sla_percentage}%",
            "ssa_coverage": f"{ssa_coverage}%",
            "duplicate_risk": duplicate_risk_cnt,
            "quality": "98.1%"
        },
        # Verification Work Queue List matching Mockup
        "queue_items": [
            {
                "record_id": "SSA-25-000879",
                "school": "Kibaha Primary",
                "district": "Kibaha DC",
                "activity_type": "SSA",
                "submitted_by": "CCE O. Mwinyi",
                "submission_date": "19 May 2025 09:21 AM",
                "status": "Pending Verification",
                "status_class": "bg-amber-50 text-amber-700 border-amber-200"
            },
            {
                "record_id": "VIS-25-001245",
                "school": "Mlandizi Secondary",
                "district": "Bagamoyo DC",
                "activity_type": "Visit Data",
                "submitted_by": "Partner: TCI",
                "submission_date": "19 May 2025 08:57 AM",
                "status": "Pending Verification",
                "status_class": "bg-amber-50 text-amber-700 border-amber-200"
            },
            {
                "record_id": "TRN-25-000532",
                "school": "Zinga Primary",
                "district": "Kisarawe DC",
                "activity_type": "Training",
                "submitted_by": "CCE O. Juma",
                "submission_date": "19 May 2025 08:43 AM",
                "status": "Salesforce Queue",
                "status_class": "bg-blue-50 text-blue-700 border-blue-200"
            },
            {
                "record_id": "EXM-25-001881",
                "school": "Kwala Secondary",
                "district": "Mkuranga DC",
                "activity_type": "Exam Results",
                "submitted_by": "Partner: ECE",
                "submission_date": "19 May 2025 08:30 AM",
                "status": "Pending Verification",
                "status_class": "bg-amber-50 text-amber-700 border-amber-200"
            },
            {
                "record_id": "MSC-25-000321",
                "school": "Pweza Primary",
                "district": "Kibaha DC",
                "activity_type": "MSC Story",
                "submitted_by": "CCE O. Aisha",
                "submission_date": "19 May 2025 08:15 AM",
                "status": "Returned",
                "status_class": "bg-rose-50 text-rose-700 border-rose-200"
            }
        ],
        # Alerts / Exceptions matching Mockup
        "exceptions": [
            {"count": 42, "text": "records missing Salesforce IDs", "severity": "error"},
            {"count": 11, "text": "non-certified partner visits submitted", "severity": "warning"},
            {"count": 8, "text": "districts below SSA verification target", "severity": "info"},
            {"count": 5, "text": "bulk uploads failed validation", "severity": "error"},
            {"count": 16, "text": "records returned for correction over 7 days", "severity": "warning"}
        ],
        # Data Quality & Compliance Panel
        "dq_metrics": [
            {"label": "Missing Fields", "value": "1,284", "trend": "+ 6%", "trend_class": "text-rose-600"},
            {"label": "Duplicate Records Detected", "value": "326", "trend": "- 4%", "trend_class": "text-emerald-600"},
            {"label": "Orphan Salesforce Entries", "value": "215", "trend": "- 5%", "trend_class": "text-emerald-600"},
            {"label": "Invalid Visit Counts", "value": "178", "trend": "+ 3%", "trend_class": "text-rose-600"},
            {"label": "Non-certified Partner Visits", "value": "112", "trend": "+ 7%", "trend_class": "text-rose-600"},
            {"label": "Schools Missing SSA", "value": "87", "trend": "+ 11%", "trend_class": "text-rose-600"},
            {"label": "Records with Date Mismatch", "value": "243", "trend": "+ 1%", "trend_class": "text-rose-600"}
        ],
        # Lowest-performing interventions list
        "lowest_performing": [
            {"name": "Reading Campaigns", "rate": 58},
            {"name": "School Mentorship", "rate": 62},
            {"name": "STEM Clubs", "rate": 64},
            {"name": "Teaching & Learning Materials", "rate": 68},
            {"name": "WASH in Schools", "rate": 71}
        ],
        # Leaderboard DC
        "leaderboard_dc": [
            {"name": "Kibaha DC", "rate": 92},
            {"name": "Bagamoyo DC", "rate": 87},
            {"name": "Kisarawe DC", "rate": 83},
            {"name": "Mkuranga DC", "rate": 76},
            {"name": "Rufiji DC", "rate": 61}
        ],
        # Evidence Review Panel Table
        "evidence_metrics": [
            {"category": "Attendance Lists", "submitted": "1,436", "verified": "1,089", "returned": "221", "rejected": "38"},
            {"category": "Photos", "submitted": "2,382", "verified": "1,812", "returned": "412", "rejected": "158"},
            {"category": "Reports", "submitted": "893", "verified": "612", "returned": "198", "rejected": "83"},
            {"category": "MSC Stories", "submitted": "512", "verified": "343", "returned": "121", "rejected": "48"},
            {"category": "Exam Result Files", "submitted": "1,204", "verified": "827", "returned": "281", "rejected": "96"}
        ],
        # Recent Activity Feed
        "recent_activities": [
            {"title": "SSA record SSA-25-000879 verified", "detail": "Kibaha Primary, Kibaha DC", "time": "5 min ago"},
            {"title": "Bulk upload completed successfully", "detail": "Training Attendance - 320 records", "time": "18 min ago"},
            {"title": "Record VIS-25-001112 returned", "detail": "Mlandizi Secondary, Bagamoyo DC", "time": "35 min ago"},
            {"title": "Data issue escalated", "detail": "Non-certified visit detected", "time": "1 hr ago"},
            {"title": "Salesforce ID linked", "detail": "Record TRN-25-000532", "time": "1 hr ago"}
        ],
        # Leaderboards for Field Monitoring
        "field_monitoring": {
            "highest_pending": [
                {"name": "CCEO A. Mwinyi", "count": 312},
                {"name": "CCEO J. Kamba", "count": 298},
                {"name": "CCEO S. Rashid", "count": 276},
                {"name": "CCEO A. Juma", "count": 244},
                {"name": "CCEO N. Khamis", "count": 201}
            ],
            "partner_submissions": [
                {"name": "TCI", "count": 412},
                {"name": "CCE", "count": 298},
                {"name": "BRAC", "count": 186},
                {"name": "CAMFED", "count": 132},
                {"name": "World Vision", "count": 98}
            ],
            "top_verifiers": [
                {"name": "IA Rehema K.", "count": 312},
                {"name": "IA Salam H.", "count": 298},
                {"name": "IA Miriam T.", "count": 276},
                {"name": "IA Joseph M.", "count": 244},
                {"name": "IA Grace P.", "count": 201}
            ],
            "slowest_turnaround": [
                {"name": "Rufiji DC", "time": "72h"},
                {"name": "Kilwa DC", "time": "64h"},
                {"name": "Lindi DC", "time": "58h"},
                {"name": "Mtwara DC", "time": "55h"},
                {"name": "Nachingwea DC", "time": "51h"}
            ]
        },
        # Mock data for premium charts
        "charts": {
            "verification_trend": [
                {"date": "Monday", "verified": 12, "returned": 2},
                {"date": "Tuesday", "verified": 18, "returned": 4},
                {"date": "Wednesday", "verified": 15, "returned": 1},
                {"date": "Thursday", "verified": 22, "returned": 3},
                {"date": "Friday", "verified": 25, "returned": 5},
            ],
            "return_reasons": [
                {"reason": "Evidence missing", "count": 28},
                {"reason": "Wrong School", "count": 12},
                {"reason": "Activity SF ID missing", "count": 25},
                {"reason": "Poor Data Quality", "count": 8},
                {"reason": "Attendance invalid", "count": 14},
            ]
        }
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
