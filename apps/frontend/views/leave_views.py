from __future__ import annotations

from datetime import datetime, date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permissions import render_access_denied, require_page_permission
from apps.accounts.models import (
    Leave,
    LeaveTypePolicy,
    LeaveBalance,
    TemporaryCoverageAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    PublicHoliday,
    User,
    CalendarBlock,
)
from apps.activities.models import Activity
from apps.hr.leave_services import (
    LeaveBalanceService,
    CoverageAssignmentService,
    LeaveRequestService,
    LeaveApprovalService,
    LeaveImpactAnalysisService,
    CalendarBlockService,
    LeaveConflictDetectionService,
    PlanningAvailabilityService,
    LeaveImpactPreviewService,
    TeamAvailabilityService,
    LeaveNotificationService,
)
from apps.core.navigation import get_user_role_slug


@require_page_permission("personal_time_off")
def personal_time_off_view(request):
    """Cockpit for requesting and managing personal leaves, matching the premium dashboard layout reference."""
    user = request.user
    role = get_user_role_slug(user)
    sp = getattr(user, "staff_profile", None)
    if not sp:
        sp, _ = StaffProfile.objects.get_or_create(
            user=user, defaults={"onboarding_state": "active", "title": "Staff"}
        )

    if not LeaveTypePolicy.objects.exists():
        LeaveBalanceService.seed_default_policies()

    year = timezone.now().year
    LeaveBalanceService.recalculate_balances(sp, year)

    balances = LeaveBalance.objects.filter(staff=sp, year=year).select_related(
        "staff__user"
    )
    policy_map = {p.leave_type: p.label for p in LeaveTypePolicy.objects.all()}

    balances_data = []
    pto_remaining = 21
    pto_entitlement = 21
    pto_used = 0
    pto_usage_pct = 0
    for b in balances:
        balances_data.append(
            {
                "type": b.leave_type,
                "label": policy_map.get(
                    b.leave_type, b.leave_type.replace("_", " ").title()
                ),
                "entitlement": b.entitlement,
                "used": b.used,
                "pending": b.pending,
                "remaining": b.remaining,
                "pct_used": round((b.used / max(b.entitlement, 1)) * 100)
                if b.entitlement
                else 0,
            }
        )
        if b.leave_type == "personal_time_off":
            pto_remaining = b.remaining
            pto_entitlement = b.entitlement
            pto_used = b.used
            pto_usage_pct = (
                round((b.used / max(b.entitlement, 1)) * 100) if b.entitlement else 0
            )

    balance_priority = {
        "personal_time_off": 0,
        "sick_leave": 1,
        "maternity_leave": 2,
        "paternity_leave": 3,
        "bereavement_leave": 4,
    }
    balances_data.sort(
        key=lambda balance: (
            balance_priority.get(balance["type"], len(balance_priority)),
            balance["label"],
        )
    )

    # Query user leaves history
    leaves = (
        Leave.objects.filter(staff=sp)
        .order_by("-created_at")
        .select_related("covering_staff__user")
    )
    reviewer_ids = {
        leave.reviewed_by_user_id for leave in leaves if leave.reviewed_by_user_id
    }
    reviewer_map = {u.id: u.name for u in User.objects.filter(id__in=reviewer_ids)}

    leaves_data = []
    for leave in leaves:
        try:
            s_dt = datetime.strptime(leave.start_date, "%Y-%m-%d")
            e_dt = datetime.strptime(leave.end_date, "%Y-%m-%d")
            day_str = f"({s_dt.strftime('%a')} - {e_dt.strftime('%a')})"
        except Exception:
            day_str = ""

        leaves_data.append(
            {
                "id": leave.id,
                "type_label": policy_map.get(
                    leave.type, leave.type.replace("_", " ").title()
                ),
                "start_date": leave.start_date,
                "end_date": leave.end_date,
                "day_str": day_str,
                "days": leave.days,
                "days_charged": leave.days_charged
                if leave.days_charged is not None
                else leave.days,
                "hours_covered": leave.hours_covered
                if leave.hours_covered is not None
                else (leave.days * 8),
                "status": leave.status,
                "reason": leave.reason,
                "cover_name": leave.covering_staff.user.name
                if leave.covering_staff
                else "None",
                "coverage_notes": leave.coverage_notes,
                "reviewer_name": reviewer_map.get(
                    leave.reviewed_by_user_id, "Pending Review"
                )
                if leave.reviewed_by_user_id
                else "Pending Review",
            }
        )

    past_request_statuses = {"completed", "rejected"}
    past_requests_count = sum(
        leave["status"] in past_request_statuses for leave in leaves_data
    )
    upcoming_requests_count = len(leaves_data) - past_requests_count

    # Coverage Assignments list. status="active" alone is not enough — an
    # assignment whose window has closed keeps that status (nothing ever
    # transitions it to "expired"), so the datetime bounds must be checked
    # here too, matching the pattern already used for authorization in
    # apps/core/permissions.py and apps/core/scoping.py.
    now = timezone.now()
    my_coverages = TemporaryCoverageAssignment.objects.filter(
        covering_staff=sp,
        status="active",
        start_datetime__lte=now,
        end_datetime__gte=now,
    ).select_related("original_staff__user", "leave_request")

    delegations_for_me = TemporaryCoverageAssignment.objects.filter(
        original_staff=sp,
        status="active",
        start_datetime__lte=now,
        end_datetime__gte=now,
    ).select_related("covering_staff__user", "leave_request")

    pending_coverages = Leave.objects.filter(
        covering_staff=sp, coverage_status="Awaiting Acceptance", status="pending"
    ).select_related("staff__user")

    # Resolve supervisor scoping and team profiles
    from apps.accounts.models import StaffSupervisorAssignment

    supervisee_ids = list(
        StaffSupervisorAssignment.objects.filter(supervisor=sp).values_list(
            "supervisee_id", flat=True
        )
    )
    has_supervisees = bool(supervisee_ids)

    # Team Members on Leave This Week
    today_str = date.today().isoformat()
    team_on_leave_count = (
        Leave.objects.filter(
            staff_id__in=supervisee_ids,
            status="approved",
            start_date__lte=today_str,
            end_date__gte=today_str,
        ).count()
        if has_supervisees
        else 0
    )

    # Active Coverage Assignments in system (scoped)
    coverage_active_count = (
        TemporaryCoverageAssignment.objects.filter(
            status="active", start_datetime__lte=now, end_datetime__gte=now
        )
        .filter(Q(original_staff=sp) | Q(covering_staff=sp))
        .count()
    )

    # 1. Holiday & Blackout Dates
    upcoming_blocks = CalendarBlock.objects.filter(
        is_active=True, end_date__gte=date.today()
    ).order_by("start_date")[:5]

    # 2. Auto-Blocked Conflicts (for the user's activities)
    user_activities = (
        Activity.objects.filter(
            responsible_staff_id=user.id, scheduled_date__isnull=False
        )
        .select_related("school", "cluster")
        .exclude(status__in=["cancelled", "completed"])
    )
    my_conflicts = []
    for act in user_activities:
        avail = PlanningAvailabilityService.check(user, act.scheduled_date)
        if avail["status"] == "blocked":
            my_conflicts.append(
                {
                    "id": act.id,
                    "type": act.activity_type.replace("_", " ").title(),
                    "school": act.school.name
                    if act.school
                    else (act.cluster.name if act.cluster else "General"),
                    "date": act.scheduled_date.date().isoformat(),
                    "blockers": avail["blockers"],
                }
            )

    # Stats variables
    pending_requests_count = sum(leave["status"] == "pending" for leave in leaves_data)
    upcoming_conflicts_count = len(my_conflicts)

    total_team_count = len(supervisee_ids) + 1
    team_available_count = total_team_count - team_on_leave_count
    avg_team_availability = round(
        (team_available_count / max(total_team_count, 1)) * 100
    )

    # 3. Team Availability Heatmap Preview (Next 4 weeks)
    availability_preview = TeamAvailabilityService.get_4week_heatmap(
        sp, country_scope=False, limit=10
    )

    # Leave Impact Preview for latest request
    latest_leave = leaves[0] if leaves else None
    impact_preview = None
    if latest_leave:
        impact_preview = LeaveImpactPreviewService.preview_impact(
            sp, latest_leave.start_date, latest_leave.end_date
        )
        impact_preview["start_date"] = latest_leave.start_date
        impact_preview["end_date"] = latest_leave.end_date

    # Team Leave Tracker table data
    if role in {"ADMIN", "HR"}:
        tracker_leaves_qs = Leave.objects.all()
    elif role == "CD":
        tracker_leaves_qs = Leave.objects.filter(staff__country=sp.country)
    elif has_supervisees:
        tracker_leaves_qs = Leave.objects.filter(staff_id__in=supervisee_ids)
    else:
        supervisor_assignment = StaffSupervisorAssignment.objects.filter(
            supervisee=sp
        ).first()
        if supervisor_assignment:
            peer_ids = StaffSupervisorAssignment.objects.filter(
                supervisor=supervisor_assignment.supervisor
            ).values_list("supervisee_id", flat=True)
            tracker_leaves_qs = Leave.objects.filter(staff_id__in=peer_ids)
        else:
            tracker_leaves_qs = Leave.objects.filter(staff=sp)

    tracker_leaves = list(
        tracker_leaves_qs.select_related(
            "staff__user", "covering_staff__user"
        ).order_by("-created_at")[:15]
    )

    tracker_reviewer_ids = {
        leave.reviewed_by_user_id
        for leave in tracker_leaves
        if leave.reviewed_by_user_id and leave.reviewed_by_user_id not in reviewer_map
    }
    if tracker_reviewer_ids:
        reviewer_map.update(
            {
                reviewer.id: reviewer.name
                for reviewer in User.objects.filter(id__in=tracker_reviewer_ids)
            }
        )

    tracker_balance_map = {
        (balance.staff_id, balance.leave_type): balance.remaining
        for balance in LeaveBalance.objects.filter(
            staff_id__in={leave.staff_id for leave in tracker_leaves},
            leave_type__in={leave.type for leave in tracker_leaves},
            year=year,
        )
    }

    # Enrich tracker leaves with remaining balance
    tracker_leaves_data = []
    for tl in tracker_leaves:
        balance_key = (tl.staff_id, tl.type)
        tracker_leaves_data.append(
            {
                "id": tl.id,
                "staff_name": tl.staff.user.name,
                "role": tl.staff.user.active_role,
                "supervisor_name": reviewer_map.get(tl.reviewed_by_user_id, "System")
                if tl.reviewed_by_user_id
                else "Pending Review",
                "type_label": policy_map.get(
                    tl.type, tl.type.replace("_", " ").title()
                ),
                "start_date": tl.start_date,
                "end_date": tl.end_date,
                "days_charged": tl.days_charged
                if tl.days_charged is not None
                else tl.days,
                "remaining_days": tracker_balance_map.get(balance_key, 0),
                "balance_available": balance_key in tracker_balance_map,
                "covering_person": tl.covering_staff.user.name
                if tl.covering_staff
                else "None",
                "status": tl.status,
            }
        )

    context = {
        "balances": balances_data,
        "leaves": leaves_data,
        "upcoming_requests_count": upcoming_requests_count,
        "past_requests_count": past_requests_count,
        "my_coverages": my_coverages,
        "delegations_for_me": delegations_for_me,
        "pending_coverages": pending_coverages,
        "upcoming_blocks": upcoming_blocks,
        "my_conflicts": my_conflicts,
        "availability_preview": availability_preview,
        "profile": sp,
        "role": role,
        "pto_remaining": pto_remaining,
        "pto_entitlement": pto_entitlement,
        "pto_used": pto_used,
        "pto_usage_pct": pto_usage_pct,
        "pending_requests_count": pending_requests_count,
        "team_on_leave_count": team_on_leave_count,
        "team_total_count": total_team_count,
        "team_available_count": team_available_count,
        "coverage_active_count": coverage_active_count,
        "upcoming_conflicts_count": upcoming_conflicts_count,
        "avg_team_availability": avg_team_availability,
        "impact_preview": impact_preview,
        "tracker_leaves": tracker_leaves_data,
    }
    return render(request, "pages/leave/personal_time_off.html", context)


@require_page_permission("personal_time_off")
def request_leave_drawer_view(request):
    """Drawer partial for creating a leave request."""
    user = request.user
    sp = getattr(user, "staff_profile", None)

    if request.method == "POST":
        try:
            attachment_file = request.FILES.get("attachment")
            leave = LeaveRequestService.request_leave(sp, request.POST, attachment_file)
            messages.success(
                request,
                f"Leave request for {leave.days_charged} working days submitted successfully.",
            )

            # Send notifications — notify supervisor + HR that approval is needed
            LeaveNotificationService.notify_leave_requested(leave)

            # Detect conflicts post request and alert
            conflicts = LeaveConflictDetectionService.detect(
                sp, leave.start_date, leave.end_date, leave.covering_staff
            )
            if conflicts:
                msg = f"{len(conflicts)} scheduling conflicts detected for your requested leave period. Please reschedule them."
                LeaveNotificationService.notify_conflict_detected(
                    user.id, msg, leave.id
                )
                messages.warning(request, msg)

        except Exception as e:
            messages.error(request, f"Failed to submit leave request: {e}")
        return redirect("frontend:personal_time_off")

    policies = LeaveTypePolicy.objects.all()
    tomorrow = (date.today() + timezone.timedelta(days=1)).isoformat()
    candidates = CoverageAssignmentService.get_eligible_coverage_staff(
        sp, tomorrow, tomorrow
    )

    context = {
        "policies": policies,
        "candidates": candidates,
        "tomorrow": tomorrow,
    }
    return render(request, "partials/leave/request_leave_drawer.html", context)


@require_page_permission("personal_time_off")
def eligible_cover_api(request):
    """API endpoint to get eligible cover staff and calculate leave period metrics."""
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")
    sp = request.user.staff_profile

    if not start_date or not end_date:
        return JsonResponse({"error": "Dates missing"}, status=400)

    try:
        candidates = CoverageAssignmentService.get_eligible_coverage_staff(
            sp, start_date, end_date
        )

        # Calculate detailed preview metrics using the preview service
        metrics = LeaveImpactPreviewService.preview_impact(sp, start_date, end_date)

        year = int(start_date[:4])
        leave_type = request.GET.get("type", "personal_time_off")
        remaining = (
            LeaveBalance.objects.filter(staff=sp, leave_type=leave_type, year=year)
            .values_list("remaining", flat=True)
            .first()
            or 0
        )

        # Check policy blocks (e.g. if blackout dates block leave requests completely)
        has_blackout = metrics["blackout_dates_skipped"] > 0
        blackout_blocked = False
        reason = ""

        # Check if the requested range overlaps any blackout dates
        if has_blackout:
            reason = "Requested period includes a blocked organizational date. Leave can still be recorded, but planning and coverage will treat this period as unavailable."
            # Optionally block if organizational policy dictates:
            # blackout_blocked = True

        return JsonResponse(
            {
                "candidates": candidates,
                "days_charged": metrics["working_days_charged"],
                "hours_covered": metrics["working_days_charged"] * 8,
                "calendar_days": metrics["calendar_days"],
                "weekends_skipped": metrics["weekends_skipped"],
                "public_holidays_skipped": metrics["public_holidays_skipped"],
                "blackout_dates_skipped": metrics["blackout_dates_skipped"],
                "staff_conference_overlap": metrics["staff_conference_overlap"],
                "affected_activities_count": metrics["affected_activities_count"],
                "balance_remaining": remaining,
                "insufficient_balance": remaining < metrics["working_days_charged"],
                "has_blackout": has_blackout,
                "blackout_blocked": blackout_blocked,
                "blackout_reason": reason,
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@require_page_permission("leave_tracker")
def leave_tracker_view(request):
    """HR, PL, and CD view of team balances and current coverages."""
    user = request.user
    role = get_user_role_slug(user)

    qs = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")
    if role == "PL":
        from apps.accounts.models import StaffSupervisorAssignment

        supervisee_ids = StaffSupervisorAssignment.objects.filter(
            supervisor__user=user
        ).values_list("supervisee_id", flat=True)
        qs = qs.filter(id__in=supervisee_ids)

    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(user__name__icontains=q)
            | Q(user__email__icontains=q)
            | Q(title__icontains=q)
        )

    year = timezone.now().year
    team_data = []

    # Was a severe N+1: initialize_balances_for_staff() alone ran up to ~7
    # queries per staff member (LeaveTypePolicy lookup + a get_or_create per
    # policy), plus 4 more queries per staff for balances/leaves — all
    # unbounded (no pagination, org-wide for HR/CD). Batch every lookup once
    # for the whole team instead.
    staff_list = list(qs)
    staff_ids = [sp.id for sp in staff_list]

    LeaveBalanceService.bulk_initialize_balances_for_staff(staff_ids, year)

    balances_by_staff: dict[str, dict[str, int]] = {}
    if staff_ids:
        for row in LeaveBalance.objects.filter(
            staff_id__in=staff_ids,
            year=year,
            leave_type__in=["personal_time_off", "sick_leave"],
        ).values("staff_id", "leave_type", "remaining"):
            balances_by_staff.setdefault(row["staff_id"], {})[row["leave_type"]] = row[
                "remaining"
            ]

    now_str = date.today().isoformat()
    active_leave_by_staff: dict[str, Leave] = {}
    next_leave_by_staff: dict[str, Leave] = {}
    if staff_ids:
        active_leave_by_staff = {
            leave.staff_id: leave
            for leave in Leave.objects.filter(
                staff_id__in=staff_ids,
                status="approved",
                start_date__lte=now_str,
                end_date__gte=now_str,
            )
            .select_related("covering_staff__user")
            .order_by("staff_id", "start_date")
            .distinct("staff_id")
        }
        next_leave_by_staff = {
            leave.staff_id: leave
            for leave in Leave.objects.filter(
                staff_id__in=staff_ids, status="approved", start_date__gt=now_str
            )
            .order_by("staff_id", "start_date")
            .distinct("staff_id")
        }

    for sp in staff_list:
        pto_remaining = balances_by_staff.get(sp.id, {}).get("personal_time_off", 21)
        sick_remaining = balances_by_staff.get(sp.id, {}).get("sick_leave", 14)
        active_leave = active_leave_by_staff.get(sp.id)
        next_leave = next_leave_by_staff.get(sp.id)

        team_data.append(
            {
                "id": sp.id,
                "name": sp.user.name,
                "role": sp.user.active_role,
                "title": sp.title or "Staff",
                "pto_remaining": pto_remaining,
                "sick_remaining": sick_remaining,
                "status": "On Leave" if active_leave else "Active",
                "active_leave": active_leave,
                "next_leave": next_leave,
                "covering_person": active_leave.covering_staff.user.name
                if active_leave and active_leave.covering_staff
                else "None",
            }
        )

    # Current coverage assignments. status="active" alone doesn't mean the
    # window is still open — nothing ever transitions the row to "expired" —
    # so require the datetime bounds too, matching apps/core/permissions.py.
    coverage_now = timezone.now()
    coverages = (
        TemporaryCoverageAssignment.objects.filter(
            status="active",
            start_datetime__lte=coverage_now,
            end_datetime__gte=coverage_now,
        )
        .select_related("original_staff__user", "covering_staff__user", "leave_request")
        .order_by("start_datetime")
    )

    if role == "PL":
        sp_id = user.staff_profile.id
        coverages = coverages.filter(
            Q(original_staff_id=sp_id) | Q(covering_staff_id=sp_id)
        )

    # Next 4 weeks availability preview
    availability_preview = TeamAvailabilityService.get_4week_heatmap(
        getattr(user, "staff_profile", None),
        country_scope=(role in ["CD", "HR", "ADMIN"]),
        limit=10,
    )

    context = {
        "team": team_data,
        "coverages": coverages,
        "availability_preview": availability_preview,
        "search_q": q,
        "role": role,
        "topbar_search": {
            "placeholder": "Search team member…",
            "value": q,
            "action": reverse("frontend:leave_tracker"),
        },
    }
    return render(request, "pages/leave/leave_tracker.html", context)


@require_page_permission("leave_approvals")
def leave_approvals_view(request):
    """Queue of leave requests awaiting review with comprehensive KPI metrics."""
    user = request.user
    role = get_user_role_slug(user)

    # Apply search and filters
    q = request.GET.get("q", "").strip()
    leave_type_filter = request.GET.get("type", "").strip()
    status_filter = request.GET.get("status", "").strip()

    qs = (
        Leave.objects.all()
        .select_related("staff__user", "covering_staff__user")
        .order_by("-created_at")
    )

    if status_filter:
        qs = qs.filter(status=status_filter)
    else:
        # Default show pending
        qs = qs.filter(status="pending")

    if leave_type_filter:
        qs = qs.filter(type=leave_type_filter)

    if q:
        qs = qs.filter(Q(staff__user__name__icontains=q) | Q(reason__icontains=q))

    # Filter strictly by authorized approver hierarchy
    authorized_leaves = []
    for lv in qs:
        if LeaveApprovalService.is_authorized_approver(user, lv):
            authorized_leaves.append(lv)

    # The headline queue remains stable when the reviewer changes a display
    # filter.  Metrics are calculated from the full authorized scope rather
    # than the currently filtered slice shown in the left rail.
    pending_scope = list(
        Leave.objects.filter(status="pending")
        .select_related("staff__user", "covering_staff__user")
        .order_by("created_at")
    )
    authorized_pending = [
        lv
        for lv in pending_scope
        if LeaveApprovalService.is_authorized_approver(user, lv)
    ]

    # 1. KPI Pending Approvals
    pending_count = len(authorized_pending)

    # 2. Approved this week (last 7 days reviewed by reviewer or generally if Admin)
    seven_days_ago = timezone.now() - timedelta(days=7)
    approved_this_week = Leave.objects.filter(
        status="approved", reviewed_at__gte=seven_days_ago
    )
    previous_window_start = seven_days_ago - timedelta(days=7)
    approved_previous_week = Leave.objects.filter(
        status="approved",
        reviewed_at__gte=previous_window_start,
        reviewed_at__lt=seven_days_ago,
    )
    if role != "Admin":
        approved_this_week = approved_this_week.filter(reviewed_by_user_id=user.id)
        approved_previous_week = approved_previous_week.filter(
            reviewed_by_user_id=user.id
        )
    approved_this_week_count = approved_this_week.count()
    approved_previous_week_count = approved_previous_week.count()
    approved_delta = approved_this_week_count - approved_previous_week_count

    # 3. Coverage Assigned (in the authorized list)
    coverage_assigned_count = sum(
        1
        for lv in authorized_pending
        if lv.covering_staff and lv.coverage_status in {"Accepted", "Approved"}
    )
    coverage_rate = (
        round((coverage_assigned_count / pending_count) * 100)
        if pending_count
        else None
    )

    # 4. Conflicts Detected
    conflicts_detected_count = 0
    for lv in authorized_pending:
        conflicts = LeaveConflictDetectionService.detect(
            lv.staff, lv.start_date, lv.end_date, lv.covering_staff
        )
        if any(c["severity"] == "Critical" for c in conflicts):
            conflicts_detected_count += 1

    # 5. Staff on Leave This Week
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    approved_in_week = Leave.objects.filter(
        status="approved",
        start_date__lte=week_end.isoformat(),
        end_date__gte=week_start.isoformat(),
    ).select_related("staff__user")
    staff_on_leave_this_week = sum(
        1
        for lv in approved_in_week
        if LeaveApprovalService.is_authorized_approver(user, lv)
    )

    # 6. Leave Balance Alerts (remaining PTO < 5)
    balance_scope = LeaveBalance.objects.filter(
        leave_type="personal_time_off", remaining__lt=5, year=timezone.now().year
    )
    reviewer_profile = getattr(user, "staff_profile", None)
    if role != "Admin":
        if reviewer_profile is None:
            balance_scope = balance_scope.none()
        elif role in {"CD", "RVP"}:
            balance_scope = balance_scope.filter(
                staff__country=reviewer_profile.country
            )
        else:
            direct_report_ids = StaffSupervisorAssignment.objects.filter(
                supervisor=reviewer_profile
            ).values_list("supervisee_id", flat=True)
            balance_scope = balance_scope.filter(staff_id__in=direct_report_ids)
    leave_balance_alerts = balance_scope.count()

    if approved_delta > 0:
        approved_helper = f"{approved_delta} more than previous 7 days"
    elif approved_delta < 0:
        approved_helper = f"{abs(approved_delta)} fewer than previous 7 days"
    else:
        approved_helper = "Same as previous 7 days"

    leave_kpi_items = [
        {
            "label": "Pending Approvals",
            "value": str(pending_count),
            "helper": "Authorized requests awaiting a decision",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Approved · 7 Days",
            "value": str(approved_this_week_count),
            "helper": approved_helper,
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Coverage Ready",
            "value": str(coverage_assigned_count),
            "helper": (
                f"{coverage_rate}% of pending requests"
                if coverage_rate is not None
                else "No pending requests"
            ),
            "icon": "users",
            "variant": "info",
        },
        {
            "label": "Critical Conflicts",
            "value": str(conflicts_detected_count),
            "helper": "Detected in the pending queue",
            "icon": "warning",
            "variant": "danger" if conflicts_detected_count else "success",
        },
        {
            "label": "Away This Week",
            "value": str(staff_on_leave_this_week),
            "helper": "Approved leave overlapping this week",
            "icon": "calendar",
            "variant": "primary",
        },
        {
            "label": "Balance Alerts",
            "value": str(leave_balance_alerts),
            "helper": "PTO balances below five days",
            "icon": "warning",
            "variant": "warning" if leave_balance_alerts else "success",
        },
    ]

    # Recent approval activities list
    recent_activities = (
        Leave.objects.filter(reviewed_by_user_id__isnull=False)
        .select_related("staff__user")
        .order_by("-reviewed_at")[:10]
    )
    recent_activity_data = []
    for ra in recent_activities:
        reviewer_name = "System"
        if ra.reviewed_by_user_id:
            reviewer = User.objects.filter(id=ra.reviewed_by_user_id).first()
            if reviewer:
                reviewer_name = reviewer.name
        recent_activity_data.append(
            {
                "datetime": ra.reviewed_at,
                "staff": ra.staff.user,
                "action": ra.status.title(),
                "leave_type": ra.type.replace("_", " ").title(),
                "dates": f"{ra.start_date} → {ra.end_date}",
                "duration": f"{ra.days_charged or ra.days} days",
                "by": reviewer_name,
            }
        )

    # Find selected leave request details
    selected_leave = None
    selected_leave_impact = None
    selected_leave_conflicts = []
    eligible_cover_staff = []

    if authorized_leaves:
        selected_leave = authorized_leaves[0]
        req_id = request.GET.get("id")
        if req_id:
            match = next((lv for lv in authorized_leaves if lv.id == req_id), None)
            if match:
                selected_leave = match

        # Fetch initial details
        selected_leave_impact = LeaveImpactAnalysisService.analyze_impact(
            selected_leave.staff,
            selected_leave.start_date,
            selected_leave.end_date,
            selected_leave.type,
        )
        selected_leave_conflicts = LeaveConflictDetectionService.detect(
            selected_leave.staff,
            selected_leave.start_date,
            selected_leave.end_date,
            selected_leave.covering_staff,
        )
        eligible_cover_staff = CoverageAssignmentService.get_eligible_coverage_staff(
            selected_leave.staff, selected_leave.start_date, selected_leave.end_date
        )

    # Heatmap matrix
    heatmap = []
    reviewer_profile = getattr(user, "staff_profile", None)
    if reviewer_profile:
        try:
            heatmap = TeamAvailabilityService.get_4week_heatmap(
                reviewer_profile, country_scope=(role in ["CD", "HR", "ADMIN"])
            )
        except Exception:
            pass

    # Upcoming holidays & blackouts
    holidays = PublicHoliday.objects.all().order_by("date")[:5]
    blackouts = CalendarBlock.objects.filter(
        block_type="BLACKOUT_DATE", is_active=True
    ).order_by("start_date")[:5]

    context = {
        "requests": authorized_leaves,
        "selected_leave": selected_leave,
        "selected_leave_impact": selected_leave_impact,
        "selected_leave_conflicts": selected_leave_conflicts,
        "eligible_cover_staff": eligible_cover_staff,
        "heatmap": heatmap,
        "holidays": holidays,
        "blackouts": blackouts,
        "role": role,
        "kpis": {
            "pending": pending_count,
            "approved_this_week": approved_this_week_count,
            "coverage_assigned": coverage_assigned_count,
            "conflicts_detected": conflicts_detected_count,
            "staff_on_leave": staff_on_leave_this_week,
            "balance_alerts": leave_balance_alerts,
        },
        "leave_kpi_items": leave_kpi_items,
        "recent_activity": recent_activity_data,
        "search_q": q,
        "selected_type": leave_type_filter,
        "selected_status": status_filter,
    }
    # One persistent search: the top bar, attached to the page filter form.
    context["topbar_search"] = {
        "placeholder": "Search staff or reason…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "attach_to": "leave-approvals-filters",
        "autosubmit": True,
    }
    return render(request, "pages/leave/leave_approvals.html", context)


@require_page_permission("leave_approvals")
def leave_impact_partial(request, leave_id):
    """Partial HTMX view showing leave impact metrics, overlaps, and conflicts."""
    leave = get_object_or_404(Leave, id=leave_id)
    # The panel renders the employee's email, leave type and free-text reason —
    # medical and family detail. Every other action on this object checks the
    # approver predicate; this read had none, so holding the page permission
    # was enough to walk any leave id in any country.
    if not LeaveApprovalService.is_authorized_approver(request.user, leave):
        return render_access_denied(
            request, "You are not the authorized approver for this leave request."
        )
    impact = LeaveImpactAnalysisService.analyze_impact(
        leave.staff, leave.start_date, leave.end_date, leave.type
    )

    # Run full conflict detection service
    conflicts = LeaveConflictDetectionService.detect(
        leave.staff, leave.start_date, leave.end_date, leave.covering_staff
    )

    # Extract overlaps and schedule conflicts from detected list
    overlaps = [
        c
        for c in conflicts
        if c["conflict_type"]
        in ["public_holiday", "blackout_date", "staff_conference", "cover_unavailable"]
    ]
    act_conflicts = [
        c for c in conflicts if c["conflict_type"] == "activity_during_leave"
    ]

    context = {
        "leave": leave,
        "impact": impact,
        "overlaps": overlaps,
        "act_conflicts": act_conflicts,
        "conflicts_count": len(conflicts),
    }
    return render(request, "partials/leave/impact_panel.html", context)


@require_POST
@require_page_permission("leave_approvals")
def leave_approve_action(request, leave_id):
    """Approve a leave request, initiate coverage access and trigger notifications."""
    try:
        leave = Leave.objects.get(id=leave_id)

        # Authorization: PL can only approve their own supervisees' leave.
        # HR/CD/RVP/ADMIN have org-wide authority.
        if request.user.active_role == "Program Lead":
            from apps.accounts.models import StaffSupervisorAssignment

            is_supervisor = StaffSupervisorAssignment.objects.filter(
                supervisee=leave.staff,
                supervisor=request.user.staff_profile,
            ).exists()
            if not is_supervisor:
                messages.error(
                    request, "You can only approve leave for your own team members."
                )
                return redirect("frontend:leave_approvals")

        LeaveApprovalService.approve_request(leave_id, request.user)
        leave.refresh_from_db()

        # Trigger notifications
        LeaveNotificationService.notify_leave_approved(leave)
        messages.success(
            request, "Leave approved. Coverage notifications sent to the team."
        )
    except Exception as e:
        messages.error(request, f"Failed to approve request: {e}")
    return redirect("frontend:leave_approvals")


@require_POST
@require_page_permission("leave_approvals")
def leave_reject_action(request, leave_id):
    """Reject a leave request."""
    reason = request.POST.get("reason", "").strip()
    try:
        LeaveApprovalService.reject_request(leave_id, request.user, reason)
        leave = Leave.objects.get(id=leave_id)
        LeaveNotificationService.notify_leave_rejected(leave, request.user.name, reason)
        messages.success(request, "Leave request rejected. Staff member notified.")
    except Exception as e:
        messages.error(request, f"Failed to reject request: {e}")
    return redirect("frontend:leave_approvals")


@require_POST
@require_page_permission("leave_approvals")
def leave_return_action(request, leave_id):
    """Return request for updates / better handover notes."""
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Feedback reason is required to return a request.")
        return redirect("frontend:leave_approvals")

    try:
        LeaveApprovalService.return_request(leave_id, request.user, reason)
        leave = Leave.objects.get(id=leave_id)
        LeaveNotificationService.notify_leave_returned(leave, request.user.name, reason)
        messages.success(
            request,
            "Leave request returned to submitter for changes. Staff member notified.",
        )
    except Exception as e:
        messages.error(request, f"Failed to return request: {e}")
    return redirect("frontend:leave_approvals")


@require_page_permission("leave_coverage")
def leave_coverage_view(request):
    """Manage coverage assignments - view scope, extend dates, or revoke access."""
    coverages = (
        TemporaryCoverageAssignment.objects.all()
        .select_related("original_staff__user", "covering_staff__user", "leave_request")
        .order_by("-created_at")
    )

    role = get_user_role_slug(request.user)
    if role == "PL":
        sp_id = request.user.staff_profile.id
        coverages = coverages.filter(
            Q(original_staff_id=sp_id) | Q(covering_staff_id=sp_id)
        )

    context = {
        "coverages": coverages,
        "role": role,
    }
    return render(request, "pages/leave/leave_coverage.html", context)


@require_POST
@require_page_permission("leave_coverage")
def revoke_coverage_action(request, assignment_id):
    """Manually revoke temporary delegated access.

    The "leave_coverage" page ACL is broad ({CCEO, PL, CD, RVP, HR,
    Accountant, IA, Admin}) since many roles legitimately need to SEE
    coverage state, but revoking one is a real access-delegation change and
    must not be doable by an arbitrary role with no relationship to the
    original staff member's leave — audit found any CCEO/RVP/Accountant/IA
    could revoke ANY org-wide coverage assignment by id. Mirror the same
    ownership check leave_reassign_coverage_action/leave_escalate_action
    already use, with an explicit HR carve-out (HR has org-wide people-ops
    oversight by design, but is_authorized_approver's hierarchy rules don't
    grant HR-as-reviewer blanket rights the way they do CD/RVP).
    """
    from apps.core.navigation import get_user_role_slug

    cov = get_object_or_404(TemporaryCoverageAssignment, id=assignment_id)
    authorized = get_user_role_slug(request.user) == "HR" or (
        LeaveApprovalService.is_authorized_approver(request.user, cov.leave_request)
    )
    if not authorized:
        messages.error(
            request, "You are not authorized to revoke this coverage assignment."
        )
        return redirect("frontend:leave_coverage")

    cov.status = "revoked"
    cov.revoked_at = timezone.now()
    cov.revoked_by_user_id = request.user.id
    cov.save(update_fields=["status", "revoked_at", "revoked_by_user_id", "updated_at"])

    from apps.audit.services import log as audit_log

    audit_log(
        action="hr.coverage_revoked",
        subject_kind="temporary_coverage_assignment",
        subject_id=cov.id,
        actor_id=request.user.id,
        actor_role=getattr(request.user, "active_role", None),
        payload={
            "originalStaffId": cov.original_staff_id,
            "coveringStaffId": cov.covering_staff_id,
        },
    )
    messages.success(
        request,
        f"Delegated access for {cov.covering_staff.user.name} has been revoked.",
    )
    return redirect("frontend:leave_coverage")


@require_page_permission("leave_calendar")
def leave_calendar_view(request):
    """Visual view of team leave periods using FullCalendar.js.

    The leave_calendar page permission is granted to ALL_ROLES, which includes
    external Partner users, so this previously rendered every employee's name
    and leave type to anyone who could log in. Who is off sick, and when, is
    not information a delivery partner needs.

    The roles that approve leave must be able to see it, so entitlement keys
    off the same permission the approval queue uses (leave_approvals: PL, CD,
    RVP, HR, Admin). Everyone else sees their own leave and the leave of
    whoever they are covering for -- enough to plan around, without publishing
    the whole organisation's absence record.
    """
    from apps.core.navigation import PAGE_PERMISSIONS, get_user_role_slug

    approves_leave = get_user_role_slug(request.user) in PAGE_PERMISSIONS.get(
        "leave_approvals", set()
    )

    approved = Leave.objects.filter(status="approved").select_related(
        "staff__user", "covering_staff__user"
    )
    pending = Leave.objects.filter(status="pending").select_related(
        "staff__user", "covering_staff__user"
    )
    if not approves_leave:
        own = request.user.staff_profile_id
        mine = Q(staff_id=own) | Q(covering_staff_id=own) if own else Q(pk__in=[])
        approved = approved.filter(mine)
        pending = pending.filter(mine)
    # `status="active"` alone is not "live" — nothing ever writes "expired",
    # so that filter matched every assignment ever created. The window is the
    # real test, and it is what the five authority checks already apply.
    _now = timezone.now()
    coverages = TemporaryCoverageAssignment.objects.filter(
        status="active", start_datetime__lte=_now, end_datetime__gte=_now
    ).select_related("original_staff__user", "covering_staff__user")

    # 4. Public Holidays & Blackout Calendar Blocks
    blocks = CalendarBlock.objects.filter(is_active=True)

    events = []

    # Approved leaves (green/teal)
    for leave in approved:
        events.append(
            {
                "title": f"Leave: {leave.staff.user.name} - {leave.type.replace('_', ' ').title()}",
                "start": leave.start_date,
                "end": (
                    datetime.strptime(leave.end_date, "%Y-%m-%d")
                    + timezone.timedelta(days=1)
                )
                .date()
                .isoformat(),
                "color": "#10b981",  # Teal/Green
                "textColor": "#ffffff",
                "extendedProps": {
                    "type": "Approved Leave",
                    "staff": leave.staff.user.name,
                    "cover": leave.covering_staff.user.name
                    if leave.covering_staff
                    else "None",
                },
            }
        )

    # Pending leaves (yellow)
    for leave in pending:
        events.append(
            {
                "title": f"⏳ Pending: {leave.staff.user.name}",
                "start": leave.start_date,
                "end": (
                    datetime.strptime(leave.end_date, "%Y-%m-%d")
                    + timezone.timedelta(days=1)
                )
                .date()
                .isoformat(),
                "color": "#f59e0b",  # Yellow/Amber
                "textColor": "#ffffff",
                "extendedProps": {
                    "type": "Pending Leave",
                    "staff": leave.staff.user.name,
                },
            }
        )

    # Active coverage assignments
    for c in coverages:
        events.append(
            {
                "title": f"Cover: {c.covering_staff.user.name}",
                "start": c.start_datetime.isoformat(),
                "end": c.end_datetime.isoformat(),
                "color": "#6366f1",
                "textColor": "#ffffff",
                "extendedProps": {
                    "type": "Coverage Assignment",
                    "staff": c.original_staff.user.name,
                    "cover": c.covering_staff.user.name,
                },
            }
        )

    # Calendar Blocks (Holidays = red/pink, Blackouts = gray, Conferences = purple)
    for b in blocks:
        color = "#94a3b8"  # gray default
        if b.block_type == "PUBLIC_HOLIDAY":
            color = "#f43f5e"  # red/pink
        elif b.block_type == "BLACKOUT_DATE":
            color = "#475569"  # dark slate
        elif b.block_type == "STAFF_CONFERENCE":
            color = "#a855f7"  # purple

        events.append(
            {
                "title": f"{b.title} [{b.block_type.replace('_', ' ').title()}]",
                "start": b.start_date.isoformat(),
                "end": (b.end_date + timezone.timedelta(days=1)).isoformat(),
                "color": color,
                "textColor": "#ffffff",
                "extendedProps": {
                    "type": b.block_type,
                    "description": b.description or "",
                },
            }
        )

    context = {"events": events}
    return render(request, "pages/leave/leave_calendar.html", context)


def _audit_leave_policy(request, action: str, subject, before: dict) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="leave_policy",
        subject_id=getattr(subject, "id", None),
        actor_id=request.user.id,
        actor_role=getattr(request.user, "active_role", None),
        payload={"before": before, "label": str(subject)},
    )


def _add_public_holiday(request):
    """POST-only. Adding and deleting public holidays ran on bare GET query
    parameters — `href="?delete_holiday=<id>"` — so a link prefetcher, a
    crawler or a mis-click could remove one with no CSRF token in play. That
    is not cosmetic: WorkingDayCalculator subtracts holidays from the days
    charged, so losing one silently bills every subsequent leave request an
    extra day and unblocks field visits on a national holiday.
    """
    name = (request.POST.get("holiday_name") or "").strip()
    date_val = (request.POST.get("holiday_date") or "").strip()
    if not name or not date_val:
        messages.error(request, "A holiday name and date are both required.")
        return redirect("frontend:leave_policies")
    try:
        holiday, created = PublicHoliday.objects.get_or_create(
            date=date_val, defaults={"name": name}
        )
        if created:
            _audit_leave_policy(request, "hr.public_holiday_added", holiday, {})
            messages.success(request, f"Public holiday '{name}' added.")
        else:
            messages.info(request, f"A holiday already exists on {date_val}.")
    except Exception as e:
        messages.error(request, f"Failed to add public holiday: {e}")
    return redirect("frontend:leave_policies")


def _delete_public_holiday(request):
    holiday_id = (request.POST.get("holiday_id") or "").strip()
    holiday = PublicHoliday.objects.filter(id=holiday_id).first()
    if not holiday:
        messages.error(request, "That public holiday no longer exists.")
        return redirect("frontend:leave_policies")
    _audit_leave_policy(
        request,
        "hr.public_holiday_removed",
        holiday,
        {"name": holiday.name, "date": str(holiday.date)},
    )
    holiday.delete()
    messages.success(request, "Public holiday removed.")
    return redirect("frontend:leave_policies")


@require_page_permission("leave_policies")
def leave_policies_view(request):
    """Policies dashboard - configure entitlements, required documents, and approvals."""
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_holiday":
            return _add_public_holiday(request)
        if action == "delete_holiday":
            return _delete_public_holiday(request)
        policy_id = request.POST.get("policy_id")
        policy = get_object_or_404(LeaveTypePolicy, id=policy_id)
        try:
            entitlement = int(request.POST.get("entitlement", 21))
            if entitlement < 0 or entitlement > 365:
                raise ValueError("Entitlement must be between 0 and 365 days.")
            before = {
                "annual_entitlement": policy.annual_entitlement,
                "requires_attachment": policy.requires_attachment,
                "approver_role": policy.approver_role,
                "weekends_count": policy.weekends_count,
                "public_holidays_count": policy.public_holidays_count,
            }
            policy.annual_entitlement = entitlement
            policy.requires_attachment = (
                request.POST.get("requires_attachment") == "yes"
            )
            policy.approver_role = request.POST.get("approver_role", "Program Lead")
            policy.weekends_count = request.POST.get("weekends_count") == "yes"
            policy.public_holidays_count = (
                request.POST.get("public_holidays_count") == "yes"
            )
            policy.save()
            # Entitlement is the input to every future balance-sufficiency
            # check; a silent edit with no record of who made it is not
            # acceptable on a control of that reach.
            _audit_leave_policy(request, "hr.leave_policy_updated", policy, before)
            messages.success(
                request, f"Leave policy for '{policy.label}' updated successfully."
            )
        except Exception as e:
            messages.error(request, f"Failed to update policy: {e}")
        return redirect("frontend:leave_policies")

    policies = LeaveTypePolicy.objects.all()
    if not policies.exists():
        LeaveBalanceService.seed_default_policies()
        policies = LeaveTypePolicy.objects.all()

    holidays = PublicHoliday.objects.all().order_by("date")

    context = {
        "policies": policies,
        "holidays": holidays,
        "approver_roles": [
            "Program Lead",
            "CountryDirector",
            "RegionalVicePresident",
            "HumanResources",
            "Admin",
        ],
    }
    return render(request, "pages/leave/leave_policies.html", context)


@require_page_permission("public_holidays")
def public_holidays_view(request):
    """View and manage Public Holidays, Blackout Dates, and Conference Weeks."""
    user = request.user
    role = get_user_role_slug(user)
    is_editor = role in ["CD", "HR", "ADMIN"]

    if request.method == "POST" and is_editor:
        action = request.POST.get("action")
        if action == "create":
            try:
                # Parse and create CalendarBlock
                data = {
                    "title": request.POST.get("title"),
                    "description": request.POST.get("description", ""),
                    "block_type": request.POST.get("block_type"),
                    "start_date": request.POST.get("start_date"),
                    "end_date": request.POST.get("end_date"),
                    "country": request.POST.get("country", "Uganda"),
                    "applies_to_all_roles": request.POST.get("applies_to_all_roles")
                    == "yes",
                }
                CalendarBlockService.create_block(data, user.id)
                messages.success(request, "Calendar Block added successfully.")
            except Exception as e:
                messages.error(request, f"Failed to create block: {e}")
        elif action == "delete":
            block_id = request.POST.get("block_id")
            CalendarBlock.objects.filter(id=block_id).delete()
            messages.success(request, "Calendar Block removed.")
        return redirect("frontend:public_holidays")

    # Handle Seeding Action
    if request.GET.get("action") == "seed" and is_editor:
        # Seed standard Uganda holidays
        holidays_data = [
            ("New Year's Day", "2026-01-01", "PUBLIC_HOLIDAY"),
            ("Archbishop Janani Luwum Day", "2026-02-16", "PUBLIC_HOLIDAY"),
            ("Women's Day", "2026-03-08", "PUBLIC_HOLIDAY"),
            ("Good Friday", "2026-04-03", "PUBLIC_HOLIDAY"),
            ("Easter Monday", "2026-04-06", "PUBLIC_HOLIDAY"),
            ("Labor Day", "2026-05-01", "PUBLIC_HOLIDAY"),
            ("Martyrs' Day", "2026-06-03", "PUBLIC_HOLIDAY"),
            ("Heroes' Day", "2026-06-09", "PUBLIC_HOLIDAY"),
            ("Independence Day", "2026-10-09", "PUBLIC_HOLIDAY"),
            ("Christmas Day", "2026-12-25", "PUBLIC_HOLIDAY"),
            ("Boxing Day", "2026-12-26", "PUBLIC_HOLIDAY"),
            ("Staff Conference Week", "2026-07-20", "STAFF_CONFERENCE", "2026-07-24"),
            ("Q3 Planning Blackout", "2026-09-01", "BLACKOUT_DATE", "2026-09-04"),
        ]
        for h in holidays_data:
            end = h[3] if len(h) > 3 else h[1]
            CalendarBlock.objects.get_or_create(
                title=h[0],
                start_date=h[1],
                end_date=end,
                defaults={
                    "block_type": h[2],
                    "country": "Uganda",
                    "applies_to_all_roles": True,
                    "created_by": user.id,
                },
            )
        messages.success(
            request, "Default Uganda holidays and calendar blocks seeded successfully."
        )
        return redirect("frontend:public_holidays")

    # Fetch and group blocks
    blocks = CalendarBlock.objects.filter(is_active=True).order_by("start_date")

    upcoming_holidays = blocks.filter(
        block_type="PUBLIC_HOLIDAY", end_date__gte=date.today()
    )
    blackout_dates = blocks.filter(block_type="BLACKOUT_DATE")
    conferences = blocks.filter(block_type="STAFF_CONFERENCE")
    regional_events = blocks.filter(block_type="REGIONAL_EVENT")
    custom_blocks = blocks.filter(block_type="CUSTOM_BLOCK")

    context = {
        "upcoming_holidays": upcoming_holidays,
        "blackout_dates": blackout_dates,
        "conferences": conferences,
        "regional_events": regional_events,
        "custom_blocks": custom_blocks,
        "is_editor": is_editor,
        "role": role,
    }
    return render(request, "pages/leave/public_holidays.html", context)


@require_page_permission("team_availability")
def team_availability_view(request):
    """Full Team Availability heatmap grid report for CD/PL/HR."""
    user = request.user
    role = get_user_role_slug(user)

    sp = getattr(user, "staff_profile", None)

    country_scope = role in ["CD", "HR", "ADMIN"]
    # Widened from a fixed four weeks so "who is away next month" is actually
    # answerable — the previous window stopped short of it.
    try:
        week_count = max(4, min(12, int(request.GET.get("weeks", 8))))
    except (TypeError, ValueError):
        week_count = 8

    matrix = TeamAvailabilityService.get_4week_heatmap(
        supervisor_profile=sp,
        country_scope=country_scope,
        week_count=week_count,
    )
    # Absence set against field work still booked in the same week. The
    # heatmap's own status label hides this: "On Leave" overwrites the
    # workload cell, so stranded school visits were invisible at team level.
    collisions = TeamAvailabilityService.collision_report(
        supervisor_profile=sp, country_scope=country_scope, weeks=week_count
    )

    # Generate list of header weeks labels
    today = date.today()
    weeks_headers = []
    for i in range(week_count):
        start = (
            today
            + timezone.timedelta(weeks=i)
            - timezone.timedelta(days=today.weekday())
        )
        end = start + timezone.timedelta(days=6)
        weeks_headers.append(
            f"Wk {i+1} ({start.strftime('%d %b')} - {end.strftime('%d %b')})"
        )

    context = {
        "matrix": matrix,
        "weeks_headers": weeks_headers,
        "role": role,
        "collisions": collisions,
        "week_count": week_count,
        "week_options": [4, 8, 12],
    }
    return render(request, "pages/leave/team_availability.html", context)


@require_POST
@require_page_permission("personal_time_off")
def leave_coverage_accept_action(request, leave_id):
    """Action for covering employee to accept coverage assignment."""
    try:
        LeaveApprovalService.accept_coverage(leave_id, request.user)
        messages.success(
            request,
            "You have accepted the coverage assignment. The supervisor is notified.",
        )
    except Exception as e:
        messages.error(request, f"Failed to accept coverage: {e}")
    return redirect("frontend:personal_time_off")


@require_POST
@require_page_permission("personal_time_off")
def leave_coverage_decline_action(request, leave_id):
    """Action for covering employee to decline coverage assignment."""
    try:
        LeaveApprovalService.decline_coverage(leave_id, request.user)
        messages.warning(
            request,
            "You have declined the coverage assignment. The request has been updated.",
        )
    except Exception as e:
        messages.error(request, f"Failed to decline coverage: {e}")
    return redirect("frontend:personal_time_off")


@require_POST
@require_page_permission("leave_approvals")
def leave_reassign_coverage_action(request, leave_id):
    """Supervisor action to override or reassign the coverage employee."""
    covering_staff_id = request.POST.get("covering_staff", "").strip()
    leave = get_object_or_404(Leave, id=leave_id)

    # Verify reviewer is authorized to modify this leave request
    if not LeaveApprovalService.is_authorized_approver(request.user, leave):
        messages.error(request, "You are not authorized to modify this leave request.")
        return redirect("frontend:leave_approvals")

    try:
        covering_staff = None
        if covering_staff_id:
            covering_staff = get_object_or_404(StaffProfile, id=covering_staff_id)

        old_covering_staff_id = leave.covering_staff_id
        leave.covering_staff = covering_staff
        leave.coverage_status = (
            "Awaiting Acceptance" if covering_staff else "Not Required"
        )
        leave.save(update_fields=["covering_staff", "coverage_status", "updated_at"])

        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.coverage_reassigned",
            subject_kind="leave",
            subject_id=leave.id,
            actor_id=request.user.id,
            actor_role=getattr(request.user, "active_role", None),
            payload={
                "oldCoveringStaffId": old_covering_staff_id,
                "newCoveringStaffId": covering_staff.id if covering_staff else None,
            },
        )

        # Trigger notification
        if covering_staff:
            LeaveNotificationService.notify_leave_coverage_assigned(leave)

        messages.success(
            request,
            f"Coverage reassigned to {covering_staff.user.name if covering_staff else 'None'}.",
        )
    except Exception as e:
        messages.error(request, f"Failed to reassign coverage: {e}")

    return redirect(f"/leave/approvals?id={leave_id}")


@require_POST
@require_page_permission("leave_approvals")
def leave_escalate_action(request, leave_id):
    """Escalate a leave request to HR."""
    leave = get_object_or_404(Leave, id=leave_id)
    if not LeaveApprovalService.is_authorized_approver(request.user, leave):
        messages.error(request, "You are not authorized to modify this leave request.")
        return redirect("frontend:leave_approvals")

    try:
        leave.status = "hr_review"
        leave.save(update_fields=["status", "updated_at"])
        # Escalating used to make the request LESS visible, not more: nothing
        # notified HR, the To-Do generator filtered on status="pending" so the
        # item vanished from every queue, the approvals page defaults to
        # pending so it left the default view, and no audit row was written.
        # It sat until the leave dates passed.
        LeaveApprovalService.escalate_to_hr(leave, request.user)
        messages.success(request, "Leave request escalated to HR.")
    except Exception as e:
        messages.error(request, f"Failed to escalate: {e}")

    return redirect("frontend:leave_approvals")
