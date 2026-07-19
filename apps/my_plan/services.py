"""My-plan — the caller's own plan feed (week/month/quarter/fy)."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from django.db.models import Q
from apps.activities.models import Activity
from apps.geography.models import District
from apps.accounts.models import User
from apps.partners.models import Partner
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import resolve_user_scope


def get_weeks_for_month(year: int, month: int) -> list[dict]:
    """Helper to generate week choices within a month."""
    last_day = calendar.monthrange(year, month)[1]
    month_name = date(year, month, 1).strftime("%b")
    weeks_list = []
    for w in range(1, 6):
        start_day = (w - 1) * 7 + 1
        end_day = last_day if w == 5 else min(last_day, w * 7)
        label = f"{month_name} {start_day} – {month_name} {end_day}"
        weeks_list.append({"val": w, "label": label})
    return weeks_list


def get_week_date_range(year: int, month: int, week: int) -> tuple[date, date]:
    """Helper to resolve range bounds for a 1-5 week division."""
    last_day = calendar.monthrange(year, month)[1]
    start_day = (week - 1) * 7 + 1
    if week == 5:
        end_day = last_day
    else:
        end_day = min(last_day, week * 7)
    return date(year, month, start_day), date(year, month, end_day)


def _scheduled_in_range(start: date, end: date) -> Q:
    """Match an activity by its real planned date, with a legacy fallback.

    ``planned_month`` and ``planned_week`` are convenience fields.  They were
    missing on some older scheduled rows, which made a real dated activity
    disappear from My Plan.  The date is the source of truth; the timestamp
    fallback keeps imported legacy records visible until they are repaired.
    """
    return Q(planned_date__range=(start, end)) | Q(
        planned_date__isnull=True,
        scheduled_date__date__range=(start, end),
    )


def get_activity_status_label_and_class(activity, today) -> tuple[str, str]:
    """Resolves operational status pill color and text for row tables."""
    status = activity.status
    planned_date = activity.planned_date
    rescheduled = activity.reschedule_count > 0
    sf_id = activity.salesforce_activity_id
    ia = activity.ia_verification_status

    if status == "completed":
        return "Completed", "bg-emerald-50 text-emerald-700 border-emerald-200"

    if status in (
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "accountant_confirmed",
    ):
        if not sf_id:
            return "Activity ID Missing", "bg-amber-50 text-amber-700 border-amber-200"
        if ia == "pending":
            return (
                "IA Pending",
                "edify-primary-soft edify-primary-text edify-primary-border",
            )
        if ia == "confirmed":
            return "IA Verified", "bg-emerald-50 text-emerald-700 border-emerald-200"
        return (
            "Accounts Pending",
            "edify-primary-soft edify-primary-text edify-primary-border",
        )

    if status in (
        "returned",
        "returned_by_pl",
        "returned_by_ia",
    ):
        return "Returned for Correction", "bg-rose-50 text-rose-700 border-rose-200"

    if planned_date == today:
        return "Due Today", "bg-amber-50 text-amber-700 border-amber-200"

    if rescheduled:
        return "Rescheduled", "bg-orange-50 text-orange-700 border-orange-200"

    if planned_date and today < planned_date <= today + timedelta(days=7):
        return "This Week", "bg-emerald-50 text-emerald-700 border-emerald-200"

    return "Scheduled", "edify-primary-soft edify-primary-text edify-primary-border"


def get(principal, query: dict) -> dict:
    """The caller's own plan feed. Legacy REST API schema:
    • week    → planned_week (and optional month) in the FY
    • month   → planned_month in the FY
    • quarter → quarter in the FY
    • fy      → the whole fiscal year (no period narrowing)"""
    period = query.get("period", "month")
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)

    # The active My Plan feed excludes terminal activities — a closed activity
    # leaves the active queue and lives in Completed Activities instead
    # (previously they leaked into the "upcoming" bucket).
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy).exclude(
        status__in=["closed", "cancelled", "rejected"]
    )
    if scope.partner_ids:
        qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
    else:
        # Match the identifier space that activities.services.create writes.
        # create() prefers the StaffProfile CUID (== scope.staff_ids) and falls
        # back to the User CUID. Cover BOTH when scope.staff_ids is empty so a
        # user without a StaffProfile still sees their scheduled activities.
        staff_ids = scope.staff_ids or [
            principal.staff_profile_id or principal.id,
            principal.id,
        ]
        staff_ids = [s for s in staff_ids if s]
        qs = qs.filter(
            Q(responsible_staff_id__in=staff_ids)
            | Q(monitored_by_staff_id__in=staff_ids, delivery_type="partner")
        )

    # Period narrowing
    if period == "week":
        w_val = query.get("week")
        m_val = query.get("month")
        if w_val and m_val:
            month_int = int(m_val)
            year_int = int(fy) - 1 if month_int >= 10 else int(fy)
            start, end = get_week_date_range(year_int, month_int, int(w_val))
            qs = qs.filter(_scheduled_in_range(start, end))
        elif w_val:
            qs = qs.filter(planned_week=int(w_val))
        elif m_val:
            qs = qs.filter(planned_month=int(m_val))
    elif period == "month":
        m_val = query.get("month")
        if m_val:
            month_int = int(m_val)
            year_int = int(fy) - 1 if month_int >= 10 else int(fy)
            last_day = calendar.monthrange(year_int, month_int)[1]
            qs = qs.filter(
                _scheduled_in_range(
                    date(year_int, month_int, 1), date(year_int, month_int, last_day)
                )
            )
    elif period == "quarter":
        q_val = query.get("quarter")
        if q_val:
            qs = qs.filter(quarter=q_val)

    items = []
    for a in qs.select_related("school", "school__district", "cluster").order_by(
        "planned_month", "planned_week"
    ):
        items.append(
            {
                "id": a.id,
                "activityType": a.activity_type,
                "status": a.status,
                "scheduledDate": a.planned_date.isoformat() if a.planned_date else None,
                "schoolId": a.school.school_id if a.school else None,
                "schoolName": a.school.name if a.school else None,
                "school": {
                    "id": a.school.id,
                    "schoolId": a.school.school_id,
                    "name": a.school.name,
                }
                if a.school
                else None,
                "clusterId": a.cluster_id,
                "cluster": {
                    "id": a.cluster.id,
                    "name": a.cluster.name,
                }
                if a.cluster
                else None,
                "fy": a.fy,
                "quarter": a.quarter,
                "plannedMonth": a.planned_month,
                "plannedWeek": a.planned_week,
                "month": a.planned_month,
                "week": a.planned_week,
                "responsibleStaffId": a.responsible_staff_id,
                "assignedPartnerId": a.assigned_partner_id,
                "deliveryType": a.delivery_type,
                "evidenceStatus": a.evidence_status,
                "paymentStatus": a.payment_status,
                "salesforceActivityId": a.salesforce_activity_id,
                "rescheduleCount": a.reschedule_count,
                "lastReason": a.last_reason,
                "estCostCents": a.est_cost_cents,
                "costCents": a.est_cost_cents,
                "costMissing": a.cost_missing,
            }
        )

    total_cost = sum(i["estCostCents"] for i in items)
    partner_planned = qs.filter(delivery_type="partner").count()

    return {
        "live": True,
        "period": period,
        "fy": fy,
        "currentKey": str(query.get("month") or ""),
        "summary": {
            "total": len(items),
            "costCents": total_cost,
            "partnerPlanned": partner_planned,
        },
        "groups": [],
        "items": items,
        "total": len(items),
    }


def compute_next_action(a, today) -> dict:
    """Computes the single primary action and its properties for a given activity."""
    # 1. Returned by IA or PL -> Fix and Resubmit
    if a.status in (
        "returned",
        "returned_by_pl",
        "returned_by_ia",
    ):
        return {
            "text": "Fix and Resubmit",
            "action": "fix",
            "url": f"/activities/{a.id}/complete",
            "description": "Returned for correction",
        }

    # 2. Due today and not started -> Start
    if a.status == "scheduled" and a.planned_date == today:
        return {
            "text": "Start",
            "action": "start",
            "url": f"/activities/{a.id}/start",
            "description": "Due today",
        }

    # 3. Started but not completed -> Complete Activity
    if a.status == "in_progress":
        return {
            "text": "Complete Activity",
            "action": "complete",
            "url": f"/activities/{a.id}/complete",
            "description": "In Progress",
        }

    # 4. Completed but no evidence -> Upload Evidence
    if a.evidence_status == "none" and a.status == "completed":
        return {
            "text": "Upload Evidence",
            "action": "evidence",
            "url": f"/activities/{a.id}/evidence",
            "description": "Evidence missing",
        }

    # 5. Evidence uploaded but no Activity SF ID -> Enter Activity SF ID
    if (
        a.status == "completed"
        and a.evidence_status == "uploaded"
        and not a.salesforce_activity_id
    ):
        return {
            "text": "Enter Activity SF ID",
            "action": "sf_id",
            "url": f"/activities/{a.id}/salesforce-id",
            "description": "Salesforce ID missing",
        }

    # 5.5 Ready to Submit for Review
    if (
        a.status == "completed"
        and a.evidence_status == "uploaded"
        and a.salesforce_activity_id
    ):
        ssa_done = True
        if a.activity_type in [
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
            "partner_ssa_collection",
            "cluster_training_ssa_collection",
        ]:
            if a.school and a.school.current_fy_ssa_status != "done":
                ssa_done = False
        participants_done = True
        if a.activity_type in [
            "training",
            "cluster_training",
            "cluster_meeting",
            "core_training",
        ]:
            participants_done = (a.teachers_attended or 0) + (
                a.leaders_attended or 0
            ) > 0

        if ssa_done and participants_done:
            return {
                "text": "Submit",
                "action": "submit",
                "url": f"/activities/{a.id}/submit",
                "description": "Ready for PL/IA review",
            }

    # 6. SSA expected but not uploaded -> Upload SSA
    if a.activity_type in [
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "cluster_training_ssa_collection",
    ]:
        if a.school and a.school.current_fy_ssa_status != "done":
            return {
                "text": "Upload SSA",
                "action": "ssa",
                "url": f"/activities/{a.id}/complete",
                "description": "SSA expected but not uploaded",
            }

    # 7. Submitted but not verified -> View Verification Status
    if a.status == "awaiting_ia_verification" and a.ia_verification_status == "pending":
        return {
            "text": "View Status",
            "action": "view_status",
            "url": f"/my-plan/{a.id}",
            "description": "Waiting for IA Verification",
        }

    # 8. IA verified but finance pending -> View Accounts Status.
    # Pre-clearance states only ("pending" was never a real PaymentStatus
    # value — it matched nothing); "disbursed" is deliberately excluded so
    # branch 9's Submit Accountability CTA below still wins for funded work.
    if (
        a.status == "ia_verified"
        and a.ia_verification_status == "confirmed"
        and a.payment_status in ("none", "pending_ia", "ia_confirmed")
    ):
        return {
            "text": "View Accounts Status",
            "action": "view_status",
            "url": f"/my-plan/{a.id}",
            "description": "Accounts clearance pending",
        }

    # 9. Disbursed but accountability not yet submitted — the RESPONSIBLE USER
    # submits accountability (receipts, actual spend, variance, NetSuite Code
    # as proof the expense entered NetSuite). The Accountant then reviews and
    # clears — see advance_service.submit_accountability/approve_accountability.
    wfr_line = (
        a.schedule_cost_lines.first() if hasattr(a, "schedule_cost_lines") else None
    )
    if wfr_line:
        adv = wfr_line.advance_requests.first()
        if adv and adv.status == "disbursed" and not adv.accountability_netsuite_id:
            return {
                "text": "Submit Accountability",
                "action": "accountability",
                "url": f"/my-plan/{a.id}/accountability",
                "description": "Disbursed — submit spend, receipts & NetSuite Code",
            }
        if adv and adv.status == "accountability_pending":
            return {
                "text": "Awaiting Finance Clearance",
                "action": "view_status",
                "url": f"/my-plan/{a.id}",
                "description": "Accountability submitted — Accountant review pending",
            }

    # 10. Default
    return {
        "text": "View Details",
        "action": "view",
        "url": f"/my-plan/{a.id}",
        "description": "Scheduled / Waiting",
    }


def get_frontend_context(principal, query: dict) -> dict:
    """Consolidated planning dashboard feed resolver for the HTML frontend."""
    today = date.today()

    # 1. Resolve User Scope
    scope = resolve_user_scope(principal)

    # 2. Extract selected filters
    fy = query.get("fy") or get_operational_fy(today)
    quarter = query.get("quarter") or get_quarter_for_date(today)
    month = query.get("month") or str(today.month)
    week = query.get("week") or str(min(5, (today.day - 1) // 7 + 1))

    # Convert parameters to integers where needed
    month_int = int(month) if month else today.month
    week_int = int(week) if week else min(5, (today.day - 1) // 7 + 1)

    # Handle Year calculations for the operational FY (Starts Oct 1st)
    fy_year = int(fy)
    if month_int >= 10:
        year_int = fy_year - 1
    else:
        year_int = fy_year

    district_id = query.get("district")
    staff_id = query.get("staff")
    activity_type = query.get("activity_type")
    status = query.get("status")
    period = query.get("period", "week")

    # 3. Base queryset constrained by user scope. Terminal activities leave
    # the active feed and live in Completed Activities — unless the caller
    # explicitly filters for one of those statuses.
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if status not in ("closed", "cancelled", "rejected"):
        qs = qs.exclude(status__in=["closed", "cancelled", "rejected"])
    if scope.partner_ids:
        qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
    else:
        staff_ids = list(scope.staff_ids or [])
        if scope.supervised_staff_ids:
            staff_ids.extend(scope.supervised_staff_ids)
        if not staff_ids:
            # Match the identifier space that activities.services.create writes
            # (StaffProfile CUID preferred, User CUID fallback). Cover BOTH so
            # users without a StaffProfile still see their scheduled activities.
            staff_ids = [principal.staff_profile_id or principal.id, principal.id]
        staff_ids = [s for s in staff_ids if s]
        qs = qs.filter(
            Q(responsible_staff_id__in=staff_ids)
            | Q(monitored_by_staff_id__in=staff_ids, delivery_type="partner")
        )

    # 4. Filter options collections for UI
    districts = [
        {"id": d.id, "name": d.name} for d in District.objects.all().order_by("name")
    ]
    staff_users = [
        {"id": u.id, "name": u.name}
        for u in User.objects.filter(status="active", deleted_at__isnull=True).order_by(
            "name"
        )
    ]

    months = [
        {"val": 10, "label": "October"},
        {"val": 11, "label": "November"},
        {"val": 12, "label": "December"},
        {"val": 1, "label": "January"},
        {"val": 2, "label": "February"},
        {"val": 3, "label": "March"},
        {"val": 4, "label": "April"},
        {"val": 5, "label": "May"},
        {"val": 6, "label": "June"},
        {"val": 7, "label": "July"},
        {"val": 8, "label": "August"},
        {"val": 9, "label": "September"},
    ]

    weeks_list = get_weeks_for_month(year_int, month_int)

    # 5. Apply selected filters to the query
    if district_id and district_id != "All" and district_id != "all":
        qs = qs.filter(
            Q(school__district_id=district_id) | Q(cluster__district_id=district_id)
        )
    if staff_id and staff_id != "All" and staff_id != "all":
        qs = qs.filter(responsible_staff_id=staff_id)
    if activity_type and activity_type != "All" and activity_type != "all":
        qs = qs.filter(activity_type=activity_type)
    if status and status != "All" and status != "all":
        # The status filter dropdown offers two friendly umbrella values that
        # are not themselves real ActivityStatus members: "submitted" (sent
        # onward for review, anywhere in the PL/IA/accounts pipeline) and
        # "returned_for_correction" (kicked back at any stage). Translate
        # them to the real workflow states here rather than filtering on a
        # status value that no Activity ever actually has.
        if status == "submitted":
            qs = qs.filter(
                status__in=[
                    "submitted_to_pl",
                    "awaiting_ia_verification",
                    "ia_verified",
                    "accountant_confirmed",
                ]
            )
        elif status == "returned_for_correction":
            qs = qs.filter(status__in=["returned", "returned_by_pl", "returned_by_ia"])
        else:
            qs = qs.filter(status=status)

    # 6. Compute period-specific ranges and filter qs_period
    w_start, w_end = get_week_date_range(year_int, month_int, week_int)

    if period == "week":
        period_label = f"{w_start.strftime('%B %-d')} – {w_end.strftime('%B %-d, %Y')}"
        qs_period = qs.filter(_scheduled_in_range(w_start, w_end))
    elif period == "month":
        month_name = date(year_int, month_int, 1).strftime("%B")
        period_label = f"{month_name} {year_int}"
        month_end = date(
            year_int, month_int, calendar.monthrange(year_int, month_int)[1]
        )
        qs_period = qs.filter(
            _scheduled_in_range(date(year_int, month_int, 1), month_end)
        )
    elif period == "quarter":
        period_label = f"{quarter} FY{fy}"
        qs_period = qs.filter(quarter=quarter)
    else:  # period == "fy"
        period_label = f"FY{fy}"
        qs_period = qs

    # 7. Compute KPI values
    current_week_start, current_week_end = get_week_date_range(
        today.year, today.month, min(5, (today.day - 1) // 7 + 1)
    )
    planned_this_week = qs.filter(
        _scheduled_in_range(current_week_start, current_week_end)
    ).count()
    planned_this_month = qs.filter(
        _scheduled_in_range(
            date(today.year, today.month, 1),
            date(
                today.year, today.month, calendar.monthrange(today.year, today.month)[1]
            ),
        )
    ).count()
    planned_this_quarter = qs.filter(quarter=get_quarter_for_date(today)).count()
    planned_this_fy = qs.count()

    visits_scheduled = qs_period.filter(
        activity_type__in=[
            "school_visit",
            "follow_up_visit",
            "coaching_visit",
            "in_school_support",
            "donor_visit",
            "story_gathering_visit",
            "school_invitation",
            "social_visit",
            "training_follow_up_visit",
            "in_school_coaching_visit",
            "core_visit",
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
            "partner_ssa_collection",
            "core_assessment_visit",
        ]
    ).count()
    trainings_scheduled = qs_period.filter(
        activity_type__in=[
            "cluster_training",
            "core_training",
            "training",
            "in_school_training",
            "school_improvement_training",
            "cluster_training_ssa_collection",
        ]
    ).count()
    meetings_scheduled = qs_period.filter(
        activity_type__in=["cluster_meeting", "cluster_meeting_ssa_review"]
    ).count()

    total_period_count = qs_period.count()
    completed_period_count = qs_period.filter(status="completed").count()
    completion_readiness = (
        int(completed_period_count / total_period_count * 100)
        if total_period_count > 0
        else 0
    )

    kpis = {
        "planned_this_week": planned_this_week,
        "planned_this_month": planned_this_month,
        "planned_this_quarter": planned_this_quarter,
        "planned_this_fy": planned_this_fy,
        "visits_scheduled": visits_scheduled,
        "trainings_scheduled": trainings_scheduled,
        "meetings_scheduled": meetings_scheduled,
        "completion_readiness": completion_readiness,
    }

    # Construct unified KPI strip items
    kpi_strip_items = [
        {
            "label": "Planned This Week",
            "value": str(planned_this_week),
            "raw_value": planned_this_week,
            "helper": "activities",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "Planned This Month",
            "value": str(planned_this_month),
            "raw_value": planned_this_month,
            "helper": "activities",
            "icon": "chart",
            "variant": "blue",
        },
        {
            "label": "Planned This Quarter",
            "value": str(planned_this_quarter),
            "raw_value": planned_this_quarter,
            "helper": "activities",
            "icon": "calendar",
            "variant": "purple",
        },
        {
            "label": "Planned This FY",
            "value": str(planned_this_fy),
            "raw_value": planned_this_fy,
            "helper": "activities",
            "icon": "calendar",
            "variant": "warning",
        },
        {
            "label": "Visits Scheduled",
            "value": str(visits_scheduled),
            "raw_value": visits_scheduled,
            "helper": "schools",
            "icon": "school",
            "variant": "blue",
        },
        {
            "label": "Trainings Scheduled",
            "value": str(trainings_scheduled),
            "raw_value": trainings_scheduled,
            "helper": "clusters",
            "icon": "target",
            "variant": "purple",
        },
        {
            "label": "Meetings Scheduled",
            "value": str(meetings_scheduled),
            "raw_value": meetings_scheduled,
            "helper": "clusters",
            "icon": "users",
            "variant": "warning",
        },
        {
            "label": "Completion Readiness",
            "value": f"{completion_readiness}%",
            "raw_value": completion_readiness,
            "helper": "on track",
            "icon": "check",
            "variant": "success",
        },
    ]

    # 8. Main Lists for the three categories and 7 sections by urgency
    partners_map = {p.id: p.name for p in Partner.objects.all()}
    # Activity.responsible_staff_id dominantly holds a StaffProfile CUID
    # (activities.services.create(): principal.staff_profile_id or user_id),
    # with a raw User id only for principals lacking a StaffProfile — key
    # the display-name map by BOTH id spaces so owner/assigned-by lookups
    # resolve the real name instead of falling back to the generic "Staff".
    from apps.accounts.models import StaffProfile

    users_map = {u.id: u.name for u in User.objects.all()}
    users_map.update(
        {
            sp.id: sp.user.name
            for sp in StaffProfile.objects.select_related("user")
            if sp.user_id and sp.user.name
        }
    )
    from apps.schools.models import School

    school_visits_list = []
    cluster_trainings_list = []
    cluster_meetings_list = []

    waiting_on_me_list = []
    due_today_list = []
    this_week_list = []
    partner_monitoring_list = []
    returned_needs_correction_list = []
    waiting_on_approval_list = []
    upcoming_list = []
    finance_pending_list = []

    activities = (
        qs_period.select_related(
            "school",
            "school__district",
            "school__sub_county",
            "cluster",
            "cluster__district",
        )
        .prefetch_related("schedule_cost_lines")
        .order_by("planned_date", "created_at")
    )

    for a in activities:
        status_label, status_class = get_activity_status_label_and_class(a, today)
        next_act = compute_next_action(a, today)

        # Budget status and badges
        badges = []
        first_line = (
            a.schedule_cost_lines.first() if hasattr(a, "schedule_cost_lines") else None
        )

        if first_line:
            wfr_line = first_line.weekly_request_lines.first()
            if wfr_line:
                wfr = wfr_line.weekly_fund_request
                if wfr.status == "pending_responsible_confirmation":
                    badges.append(("Included in Weekly Request", "amber"))
                elif wfr.status == "submitted_to_pl":
                    badges.append(("Awaiting PL Approval", "amber"))
                elif wfr.status == "submitted_to_cd":
                    badges.append(("Awaiting CD Approval", "amber"))
                elif wfr.status in (
                    "returned_by_pl",
                    "returned_by_cd",
                    "returned_by_accountant",
                ):
                    badges.append(("Request Returned", "red"))
                elif wfr.status == "confirmed_for_advance":
                    badges.append(("Approved — Ready for Disbursement", "green"))
                elif wfr.status == "disbursed":
                    badges.append(("Disbursed", "green"))
                else:
                    badges.append(("Included in Request", "blue"))
            else:
                badges.append(("Budget Created", "blue"))
        else:
            badges.append(("No Budget", "slate"))

        # Evidence status
        if a.status == "completed":
            if a.evidence_status == "uploaded":
                badges.append(("Evidence Uploaded", "green"))
            else:
                badges.append(("Evidence Pending", "amber"))

        # SF ID status
        if a.status in [
            "completed",
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
        ]:
            if a.salesforce_activity_id:
                badges.append(("SF ID Entered", "green"))
            else:
                badges.append(("SF ID Missing", "red"))

        # IA status
        if a.ia_verification_status == "pending":
            badges.append(("IA Pending", "purple"))
        elif a.ia_verification_status == "confirmed":
            badges.append(("IA Verified", "green"))
        elif a.ia_verification_status == "returned":
            badges.append(("Returned", "red"))

        # Accounts status
        if a.payment_status in ("pending", "pending_ia"):
            badges.append(("Accounts Pending", "amber"))
        elif a.payment_status in ("cleared", "accountant_cleared"):
            badges.append(("Cleared", "green"))
        elif a.payment_status in ("disbursed", "netsuite_accountability"):
            badges.append(("Accountability Pending", "amber"))
        elif a.payment_status == "paid":
            badges.append(("Paid", "green"))

        # Core details
        is_core = a.school and a.school.school_type == "core"
        visit_number = ""
        training_number = ""
        core_progress = ""
        if is_core:
            if a.activity_type == "core_visit":
                prev_visits = Activity.objects.filter(
                    school=a.school,
                    activity_type="core_visit",
                    fy=a.fy,
                    planned_date__lt=a.planned_date if a.planned_date else date.today(),
                ).count()
                visit_number = f"V{prev_visits + 1}"
            elif a.activity_type == "core_training":
                prev_trainings = Activity.objects.filter(
                    school=a.school,
                    activity_type="core_training",
                    fy=a.fy,
                    planned_date__lt=a.planned_date if a.planned_date else date.today(),
                ).count()
                training_number = f"T{prev_trainings + 1}"

            completed_core = Activity.objects.filter(
                school=a.school,
                activity_type__in=["core_visit", "core_training"],
                status="completed",
                fy=a.fy,
            ).count()
            core_progress = f"{completed_core}/8 Completed"

        # Partner details
        partner_name = ""
        assigned_by = ""
        partner_schedule_status = ""
        staff_monitoring_status = ""
        if a.delivery_type == "partner":
            partner_name = partners_map.get(a.assigned_partner_id, "Partner")
            assigned_by = users_map.get(a.responsible_staff_id, "Staff")
            partner_schedule_status = (
                "Scheduled" if a.planned_date else "Pending Partner Scheduling"
            )
            staff_monitoring_status = "Monitoring"

        # Return details
        return_reason = ""
        returned_by = ""
        if a.status in (
            "returned",
            "returned_by_pl",
            "returned_by_ia",
        ):
            return_reason = a.last_reason or "Correction required"
            if a.ia_verification_status == "returned":
                returned_by = "Internal Auditor"
            else:
                returned_by = "Project Leader"

        # Budget Total — always the real scheduled budget, never invented rates.
        # est_cost_cents stores whole UGX (despite the name; the costing engine
        # writes cost.amount straight into it), so no /100. Zero means the
        # activity genuinely has no budget lines yet.
        budget_total = a.est_cost_cents or sum(
            line.amount or 0 for line in a.schedule_cost_lines.all()
        )

        # Construct final dict
        activity_data = {
            "id": a.id,
            "activity_type": a.activity_type,
            "activity_type_label": a.get_activity_type_display(),
            "status": a.status,
            "planned_date": a.planned_date,
            # School details
            "school_id": a.school.school_id if a.school else "",
            "school_name": a.school.name if a.school else "Unknown School",
            "school_district": a.school.district.name if a.school else "Unknown",
            "school_sub_county": a.school.sub_county.name
            if a.school and a.school.sub_county
            else "",
            "school_cluster_name": a.cluster.name
            if a.cluster
            else (a.school.cluster_id or ""),
            "school_ssa_status": a.school.get_current_fy_ssa_status_display()
            if a.school
            else "No SSA",
            # Cluster details
            "cluster_name": a.cluster.name if a.cluster else "Unknown Cluster",
            "cluster_district": a.cluster.district.name if a.cluster else "Unknown",
            "cluster_school_count": School.objects.filter(
                cluster_id=a.cluster.id
            ).count()
            if a.cluster
            else 0,
            "expected_participants": (a.teachers_attended or 0)
            + (a.leaders_attended or 0)
            + (a.other_participants or 0)
            or a.expected_participants
            or 20,
            # Core details
            "is_core": is_core,
            "visit_number": visit_number,
            "training_number": training_number,
            "core_progress": core_progress,
            # Partner details
            "partner_name": partner_name,
            "assigned_by": assigned_by,
            "partner_schedule_status": partner_schedule_status,
            "staff_monitoring_status": staff_monitoring_status,
            # Return details
            "return_reason": return_reason,
            "returned_by": returned_by,
            # General details
            "purpose": a.activity_purpose_text or a.get_activity_type_display(),
            "focus_intervention": a.get_focus_intervention_display()
            if a.focus_intervention
            else "General",
            "owner": users_map.get(a.responsible_staff_id, "Staff"),
            "execution_role": "Staff" if a.delivery_type == "staff" else "Partner",
            "budget_total": budget_total,
            "salesforce_activity_id": a.salesforce_activity_id,
            "evidence_status": a.evidence_status,
            "ia_verification_status": a.ia_verification_status,
            "payment_status": a.payment_status,
            # Next Action & Badges
            "next_action": next_act,
            "badges": badges,
            "status_label": status_label,
            "status_class": status_class,
        }

        # Legacy lists for compatibility
        if a.activity_type in [
            "school_visit",
            "follow_up_visit",
            "coaching_visit",
            "in_school_support",
            "donor_visit",
            "story_gathering_visit",
            "school_invitation",
            "social_visit",
            "training_follow_up_visit",
            "in_school_coaching_visit",
            "core_visit",
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
            "partner_ssa_collection",
            "core_assessment_visit",
        ]:
            school_visits_list.append(activity_data)
        elif a.activity_type in [
            "cluster_training",
            "core_training",
            "training",
            "in_school_training",
            "school_improvement_training",
            "cluster_training_ssa_collection",
        ]:
            cluster_trainings_list.append(activity_data)
        elif a.activity_type in ["cluster_meeting", "cluster_meeting_ssa_review"]:
            cluster_meetings_list.append(activity_data)

        # Finance / Accountability pending — advance disbursed but accountability
        # (NetSuite expense ID) still outstanding, or payment mid-flight.
        # ("disbursed" is written by fund_requests.finance_services; the enum
        # value for the accountability stage is "netsuite_accountability".)
        if a.payment_status in ("disbursed", "netsuite_accountability"):
            finance_pending_list.append(activity_data)

        # Classification into 7 Urgency Sections
        if a.status in (
            "returned",
            "returned_by_pl",
            "returned_by_ia",
        ):
            returned_needs_correction_list.append(activity_data)
        elif a.delivery_type == "partner":
            partner_monitoring_list.append(activity_data)
        elif next_act["action"] in [
            "evidence",
            "sf_id",
            "ssa",
            "fix",
            "accountability",
        ]:
            waiting_on_me_list.append(activity_data)
        elif a.planned_date == today and a.status in ["scheduled", "in_progress"]:
            due_today_list.append(activity_data)
        elif (
            a.planned_date
            and today < a.planned_date <= today + timedelta(days=7)
            and a.status in ["scheduled", "in_progress"]
        ):
            this_week_list.append(activity_data)
        elif (
            a.status
            in (
                "submitted_to_pl",
                "awaiting_ia_verification",
                "ia_verified",
                "accountant_confirmed",
            )
            or next_act["action"] == "view_status"
        ):
            waiting_on_approval_list.append(activity_data)
        else:
            upcoming_list.append(activity_data)

    # 9. Right Rail: Planning Insights
    today_activities = (
        qs.filter(planned_date=today)
        .select_related("school", "school__district", "cluster")
        .order_by("created_at")
    )
    upcoming_today = []
    for a in today_activities:
        assigned_partner = "None"
        if a.delivery_type == "partner" and a.assigned_partner_id:
            assigned_partner = partners_map.get(a.assigned_partner_id, "Partner")
        elif a.responsible_staff_id:
            assigned_partner = users_map.get(a.responsible_staff_id, "Staff")

        upcoming_today.append(
            {
                "id": a.id,
                "time": "08:30 AM",
                "title": a.school.name
                if a.school
                else (a.cluster.name if a.cluster else "Activity"),
                "purpose": a.activity_purpose_text or a.get_activity_type_display(),
                "district": a.school.district.name
                if a.school
                else (a.cluster.district.name if a.cluster else "Unknown"),
                "assigned_partner": assigned_partner,
            }
        )

    attention_needed = []

    # 1. Rescheduled Activities
    rescheduled_acts = qs.filter(reschedule_count__gt=0).select_related(
        "school", "cluster"
    )[:3]
    for r in rescheduled_acts:
        attention_needed.append(
            {
                "id": r.id,
                "type": "Rescheduled",
                "badge_class": "bg-orange-50 text-orange-700 border-orange-200",
                "title": r.school.name
                if r.school
                else (r.cluster.name if r.cluster else "Activity"),
                "issue": f"Rescheduled {r.reschedule_count} times.",
                "detail": f"New date: {r.planned_date.strftime('%b %d, %Y') if r.planned_date else 'N/A'}",
            }
        )

    # 2. Awaiting Evidence
    awaiting_evidence_acts = qs.filter(
        status="completed", evidence_status="none"
    ).select_related("school", "school__district", "cluster")[:3]
    for ae in awaiting_evidence_acts:
        attention_needed.append(
            {
                "id": ae.id,
                "type": "Awaiting Evidence",
                "badge_class": "bg-amber-50 text-amber-700 border-amber-200",
                "title": ae.school.name
                if ae.school
                else (ae.cluster.name if ae.cluster else "Activity"),
                "issue": "Completion submitted without uploading required files.",
                "detail": f"Evidence due: {ae.planned_date.strftime('%b %d, %Y') if ae.planned_date else 'N/A'}",
            }
        )

    # 3. SF ID Missing
    sf_missing_acts = qs.filter(
        status="completed", salesforce_activity_id__isnull=True
    ).select_related("school", "school__district", "cluster")[:3]
    for sf in sf_missing_acts:
        attention_needed.append(
            {
                "id": sf.id,
                "type": "Activity SF ID Missing",
                "badge_class": "bg-red-50 text-red-700 border-red-200",
                "title": sf.school.name
                if sf.school
                else (sf.cluster.name if sf.cluster else "Activity"),
                "issue": "Activity lacks a Salesforce confirmation ID.",
                "detail": "Action: Add Salesforce Activity ID.",
            }
        )

    next_recommended_action = {
        "title": "You're on track!",
        "message": "Your plans are well aligned with district priorities.",
        "badge_class": "bg-emerald-50 border-emerald-100 text-emerald-800",
        "action_text": "View Weekly Recommendations",
        "action_url": "#",
    }
    if attention_needed:
        first_alert = attention_needed[0]
        if first_alert["type"] == "Awaiting Evidence":
            next_recommended_action = {
                "title": "Upload evidence",
                "message": f"Upload files/documents for {first_alert['title']}.",
                "badge_class": "bg-amber-50 border-amber-100 text-amber-800",
                "action_text": "Upload Evidence",
                "action_url": f"/my-plan/{first_alert['id']}",
            }
        elif first_alert["type"] == "Activity SF ID Missing":
            next_recommended_action = {
                "title": "Enter Activity SF ID",
                "message": f"Add Salesforce Activity ID for {first_alert['title']}.",
                "badge_class": "bg-red-50 border-red-100 text-red-800",
                "action_text": "Enter SF ID",
                "action_url": f"/my-plan/{first_alert['id']}",
            }

    breakdown = {
        "week": planned_this_week,
        "month": planned_this_month,
        "quarter": planned_this_quarter,
        "fy": planned_this_fy,
    }

    return {
        "live": True,
        "period": period,
        "fy": fy,
        "selected_month": month_int,
        "selected_week": week_int,
        "selected_quarter": quarter,
        "period_label": period_label,
        "weeks": weeks_list,
        "months": months,
        "quarters": ["Q1", "Q2", "Q3", "Q4"],
        "districts": districts,
        "selected_district": district_id,
        "staff_users": staff_users,
        "selected_staff": staff_id,
        "selected_activity_type": activity_type,
        "selected_status": status,
        "kpis": kpis,
        "kpi_strip_items": kpi_strip_items,
        "school_visits": school_visits_list,
        "cluster_trainings": cluster_trainings_list,
        "cluster_meetings": cluster_meetings_list,
        "waiting_on_me": waiting_on_me_list,
        "due_today": due_today_list,
        "this_week": this_week_list,
        "partner_monitoring": partner_monitoring_list,
        "returned_needs_correction": returned_needs_correction_list,
        "waiting_on_approval": waiting_on_approval_list,
        "upcoming": upcoming_list,
        "finance_pending": finance_pending_list,
        "viewer_is_partner": bool(scope.partner_ids),
        "upcoming_today": upcoming_today,
        "attention_needed": attention_needed,
        "next_recommended_action": next_recommended_action,
        "breakdown": breakdown,
    }
