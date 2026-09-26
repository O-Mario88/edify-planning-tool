"""My-plan — the caller's own plan feed (week/month/quarter/fy)."""

from __future__ import annotations

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    PROGRAMME_EVENT_TYPES,
    VISIT_TYPES,
    TRAINING_TYPES,
)
import calendar
from datetime import date, timedelta
from django.db.models import Count, Q
from apps.activities.models import Activity
from apps.activities.services import is_partner_ssa_support_activity
from apps.geography.models import District
from apps.accounts.models import User
from apps.partners.models import Partner
from apps.core.fy import fy_options, get_operational_fy, get_quarter_for_date
from apps.core.metrics import MetricValue, render_metric, render_strip
from apps.core.scoping import owner_ids, resolve_user_scope
from apps.partners.purposes import visit_purpose_label

# A visit request that the school owner has not yet approved is not on the
# requester's plan: it takes effect there only once approved (owner,
# 2026-09-03; apps.planning.visit_requests). Pending ones are tracked on the
# Visit Requests page, and stay reachable here through the status filter.
#
# Deferred and never-planned rows are released work everywhere else — the
# visit gate, Today, work-plan health, the coordinator's My Plan and every
# oversight page read them as not work — but this list let them through, so a
# dead row sat on My Plan labelled "Scheduled" and no supervisor could see it:
# My Plan and oversight disagreed about what a person's plan held (owner,
# 2026-09-24: oversight must mirror My Plan). An explicit status filter still
# reaches them, as it reaches the other exclusions.
ACTIVE_MY_PLAN_EXCLUDED_STATUSES = (
    "closed",
    "cancelled",
    "rejected",
    "awaiting_owner_approval",
    "deferred",
    "not_planned",
)

#: The calendar month a quarter opens on. The fiscal year starts in October,
#: so Q1 is October–December. Mirrors `_QUARTER_START_MONTH` in apps.core.fy,
#: which is private to that module.
QUARTER_FIRST_MONTH = {"Q1": 10, "Q2": 1, "Q3": 4, "Q4": 7}

#: Slot statuses that mean the package activity actually happened. The slot
#: mirrors the activity's workflow status, but in mixed case ("Scheduled",
#: "IA Verified"), so compare on a normalised value rather than on the raw one.
_COMPLETE_SLOT_STATUSES = frozenset(
    {status.replace("_", " ") for status in COMPLETED_WORK_STATUSES}
    | set(COMPLETED_WORK_STATUSES)
)


def _slot_status_is_complete(status: str | None) -> bool:
    return (status or "").strip().lower() in _COMPLETE_SLOT_STATUSES


#: What the filter selects say for "no narrowing". An unselected filter arrives
#: as "all" from the form and as None from a URL that simply omits it; both mean
#: the same thing and neither is a month.
_UNSET_FILTER_VALUES = {"", "all", "any", "none"}


def _unset(value) -> bool:
    """True when a filter value means "not narrowed"."""
    return value is None or str(value).strip().lower() in _UNSET_FILTER_VALUES


def _widened(previous, current) -> bool:
    """True when the caller just moved a filter off the value it was rendered with.

    Only a submitted form carries `previous`; without it nothing is cleared, so
    a hand-written URL means exactly what it says.
    """
    if previous is None or current is None:
        return False
    return str(previous) != str(current)


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


def status_tone(status_class: str) -> str:
    """The badge palette key behind a status pill's legacy class string.

    The row tables now colour-code status rather than outlining it, but the
    label/class helper is shared with older surfaces — so the tone is derived
    here instead of rewriting every caller."""
    c = status_class or ""
    if "emerald" in c:
        return "green"
    if "amber" in c:
        return "amber"
    if "rose" in c:
        return "red"
    if "primary" in c:
        return "purple"
    return "slate"


def get_activity_status_label_and_class(activity, today) -> tuple[str, str]:
    """Resolves operational status pill color and text for row tables."""
    status = activity.status
    planned_date = activity.planned_date
    rescheduled = activity.reschedule_count > 0
    sf_id = activity.salesforce_activity_id
    ia = activity.ia_verification_status

    # "closed" was missing here and fell through every branch to the default
    # "Scheduled" — so a finished, financially closed activity was labelled as
    # still upcoming, in the My Plan tables and on its own detail page, where
    # it sat next to a timeline that correctly called it complete.
    if status in ("completed", "closed"):
        return "Activity complete", "bg-emerald-50 text-emerald-700 border-emerald-200"

    if status == "awaiting_owner_approval":
        return "Awaiting owner approval", "bg-amber-50 text-amber-700 border-amber-200"

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
            return "IA complete", "bg-emerald-50 text-emerald-700 border-emerald-200"
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


def staff_my_plan_q(staff_ids, principal=None) -> Q:
    """Which activities are this staff member's own executable work.

    My Plan is the detailed execution list of the activities the reader OWNS
    AND DELIVERS (owner, 2026-09-23): the activity owner, the delivery channel
    and the workflow state decide membership — never a school-level "Partner
    Support" label. A Partner-delivered activity is the Partner's to execute:
    it appears on the Partner's My Plan once scheduled and is monitored by
    staff on Partner Monitoring, so it is not put on the monitoring staff
    member's list as work they could start, complete or reschedule.

    This no longer waits on the Partner-supported school rollout flag (owner,
    2026-09-26): "leave the My Plan page with only activities planned by the
    staff". Readers outside the pilot used to get monitored Partner work back,
    in a "Partner Planned — Monitoring" card. Every school assigned to a
    Partner and everything a Partner schedules now lives on Partner
    Monitoring, for every reader. The two statuses only a Partner's work
    carries are excluded as well, so a legacy row with a staff delivery type
    cannot bring it back.
    """
    owned = Q(responsible_staff_id__in=staff_ids)
    return (
        owned
        & ~Q(delivery_type="partner")
        & ~Q(status__in=("assigned_to_partner", "partner_scheduled"))
    )


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
        status__in=ACTIVE_MY_PLAN_EXCLUDED_STATUSES
    )
    if scope.partner_ids:
        qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
    else:
        # BOTH identifier spaces, always — not just when the scope is empty.
        # `Activity.responsible_staff_id` holds a StaffProfile id when the row
        # came through activities.services.create and a User id when it came
        # from the seeder or an older path; `owner_ids` is the one helper that
        # knows this, and its docstring records what happens without it —
        # "silently disowns most of a field worker's activities". Filtering on
        # scope.staff_ids alone reproduced that bug on the field officer's
        # primary daily surface (2026-08 audit).
        staff_ids = [s for s in owner_ids(principal) if s]
        qs = qs.filter(staff_my_plan_q(staff_ids, principal))

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

    from apps.budget.costing_service import planned_minimum_amounts

    activities = list(
        qs.select_related("school", "school__district", "cluster").order_by(
            "planned_month", "planned_week"
        )
    )
    minimum_amounts = planned_minimum_amounts(activities)
    items = []
    for a in activities:
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
                "estCostCents": minimum_amounts.get(a.id),
                "costCents": minimum_amounts.get(a.id),
                "costMissing": minimum_amounts.get(a.id) is None,
            }
        )

    total_cost = (
        None
        if any(i["costMissing"] for i in items)
        else sum(i["estCostCents"] for i in items)
    )
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


# Statuses meaning "the visit happened and the paperwork is in progress".
# `start_completion` writes `completion_started`, but the evidence / SF-ID /
# submit branches below only ever tested `completed` — a status the canonical
# CCEO path never produces. That mismatch silently withheld every one of those
# next actions (and therefore every To-Do) from the people doing the work.
_WORKED_STATUSES = (
    "completed",
    "completion_started",
    "in_progress",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
)


def compute_next_action(a, today) -> dict:
    """Computes the single primary action and its properties for a given activity."""
    # 0. Asked, not yet granted. Nothing to do here but wait; the request
    # page shows who was asked and what they said.
    if a.status == "awaiting_owner_approval":
        return {
            "text": "Waiting for owner approval",
            "action": "await_owner",
            "url": "/planning/visit-requests",
            "description": "The school's owner has been asked to approve this visit",
        }
    # 1. Returned by IA or PL -> Fix and Resubmit
    if a.status in (
        "returned",
        "returned_by_pl",
        "returned_by_ia",
    ):
        return {
            "text": (
                "Correct Returned Evidence"
                if a.delivery_type == "partner"
                else "Fix and Resubmit"
            ),
            "action": "fix",
            "url": (
                f"/partner/activities/{a.id}/evidence"
                if a.delivery_type == "partner"
                else f"/activities/{a.id}/complete"
            ),
            "description": "Returned for correction",
        }

    # 1.5 Partner evidence goes DIRECTLY to IA (§10) — there is no staff
    # acceptance step. Evidence uploaded but not yet submitted means the
    # partner's next move is the submission itself, from their evidence page.
    if (
        a.delivery_type == "partner"
        and a.evidence_status == "uploaded"
        and a.status
        not in (
            "closed",
            "cancelled",
            "rejected",
            "ia_verified",
            "returned_by_ia",
            "awaiting_ia_verification",
        )
    ):
        return {
            "text": "Submit Evidence to IA",
            "action": "submit_evidence",
            "url": f"/partner/activities/{a.id}/evidence",
            "description": "Evidence uploaded — submit it to IA for verification",
        }

    # 2. Due today and not started -> Start
    #
    # `partner_scheduled` counts. It is a dated, committed activity exactly
    # like `scheduled` — whether the partner picked the date themselves or
    # Edify booked a certified agency onto it. Omitting it meant a partner
    # opened My Plan on the morning of their own training and were offered
    # "View Details", while start_completion would have accepted them all
    # along (see STARTABLE_STATUSES).
    if a.status in ("scheduled", "partner_scheduled") and a.planned_date == today:
        return {
            "text": "Start",
            "action": "start",
            "url": (
                f"/partner/activities/{a.id}/evidence"
                if a.delivery_type == "partner"
                else f"/activities/{a.id}/start"
            ),
            "description": "Due today",
        }

    # 2.5 A dated partner booking that has not arrived yet -> Prepare.
    #
    # A certified agency booked by Edify has a real obligation from the moment
    # it is created — it is dated, budgeted, and a school is expecting someone.
    # Falling through to the generic "View Details" default meant the To-Do
    # service (which lists only actionable or waiting next actions) produced
    # nothing at all for the agency until the morning of the activity, so the
    # booking notification was the single thing carrying it. Partner-delivered
    # only: a staff member's own scheduled visit already reads correctly.
    if (
        a.status == "partner_scheduled"
        and a.delivery_type == "partner"
        and a.planned_date
        and a.planned_date > today
    ):
        return {
            "text": "Prepare",
            "action": "prepare",
            "url": f"/my-plan/{a.id}",
            "description": "Booked — review the plan and prepare",
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
    if a.evidence_status == "none" and a.status in _WORKED_STATUSES:
        return {
            "text": "Upload Evidence",
            "action": "evidence",
            "url": f"/activities/{a.id}/evidence",
            "description": "Evidence missing",
        }

    # 5. Evidence uploaded but no Activity SF ID -> Enter Activity SF ID
    if (
        a.status in _WORKED_STATUSES
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
        a.status in _WORKED_STATUSES
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
    # .all() rather than .first(): this runs once per activity in the my-plan
    # row loop, and only .all() reads the prefetch cache set up by the caller.
    # .first() re-queried on every row.
    # Every cost line, not just the first: reading `next(iter(...))` alone meant
    # a multi-line activity showed no accountability action once line 1 was
    # settled, even with money outstanding on lines 2+.
    advances = [
        adv
        for line in a.schedule_cost_lines.all()
        for adv in line.advance_requests.all()
    ]
    # Money owed back to the employee outranks everything — they are out of
    # pocket. This branch did not exist, so the drawer and route for it were
    # unreachable and the loop stalled here.
    for adv in advances:
        if (
            adv.status == "reimbursement_disbursed"
            and not adv.reimbursement_receipt_confirmed_at
        ):
            return {
                "text": "Confirm Reimbursement Receipt",
                "action": "reimbursement_receipt",
                "url": f"/my-plan/{a.id}/confirm-reimbursement-receipt",
                "description": "Reimbursement sent — confirm you received it",
            }
    for adv in advances:
        if adv.status == "disbursed" and not adv.accountability_netsuite_id:
            return {
                "text": "Submit Accountability",
                "action": "accountability",
                "url": f"/my-plan/{a.id}/accountability",
                "description": "Disbursed — submit spend, receipts & NetSuite Code",
            }
    for adv in advances:
        if adv.status == "accountability_pending":
            return {
                "text": "Awaiting Finance Clearance",
                "action": "view_status",
                "url": f"/my-plan/{a.id}",
                "description": "Accountability submitted — Accountant review pending",
            }
    # The two PL stages had no branch, so an officer whose accountability or
    # reimbursement claim sat with their Programme Lead fell through to the
    # generic "Scheduled / Waiting" and was told nothing.
    for adv in advances:
        if adv.status == "accountability_pl_pending":
            return {
                "text": "Awaiting PL Accountability Approval",
                "action": "view_status",
                "url": f"/my-plan/{a.id}",
                "description": "Accountability submitted — Programme Lead approval pending",
            }
        if adv.status == "reimbursement_pl_pending":
            return {
                "text": "Awaiting PL Claim Approval",
                "action": "view_status",
                "url": f"/my-plan/{a.id}",
                "description": "Self-funded claim submitted — Programme Lead approval pending",
            }
        if adv.status == "reimbursement_submitted":
            return {
                "text": "Awaiting Reimbursement",
                "action": "view_status",
                "url": f"/my-plan/{a.id}",
                "description": "Claim approved — Accountant reimbursement pending",
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

    # My Plan's period filters nest: a fiscal year holds quarters, a quarter
    # holds months. Widening clears what it contains, so picking FY2027 answers
    # "the whole of FY2027" instead of quietly keeping the October that was
    # selected under the old year. A GET form submits every select, not only
    # the one that changed, so the widening is detected by comparing each value
    # against the one the page was rendered with (the `*_prev` hidden inputs).
    # A URL without them — a deep link, the API, the CSV export — is read
    # exactly as written (owner, 2026-09-17).
    raw_quarter = query.get("quarter")
    raw_month = query.get("month")
    if _widened(query.get("fy_prev"), query.get("fy")):
        raw_quarter = raw_month = None
    elif _widened(query.get("quarter_prev"), raw_quarter):
        raw_month = None

    selected_quarter = None if _unset(raw_quarter) else str(raw_quarter)
    selected_month = None if _unset(raw_month) else int(raw_month)
    # A quarter on its own opens at its first month — October for Q1, January
    # for Q2 — which is the month someone choosing a quarter is looking for.
    if selected_month is None and selected_quarter in QUARTER_FIRST_MONTH:
        selected_month = QUARTER_FIRST_MONTH[selected_quarter]

    week = query.get("week") or str(min(5, (today.day - 1) // 7 + 1))

    # Concrete values for the period slicing below, which always needs a real
    # month and quarter even when the page is showing the whole year.
    quarter = selected_quarter or get_quarter_for_date(today)
    month_int = selected_month if selected_month is not None else today.month
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
    # The fiscal year is the page's resting state: a year with nothing else
    # selected shows every activity in it, oldest first, rather than the one
    # week My Plan used to open on. Narrowing to a month is the filter's job,
    # and an explicit ?period= still wins so the CSV export, the API and links
    # built elsewhere keep asking for the slice they name.
    explicit_period = str(query.get("period") or "").strip()
    if explicit_period:
        period = explicit_period
    elif selected_month is not None:
        period = "month"
    else:
        period = "fy"

    # 3. Base queryset constrained by user scope. Terminal activities leave
    # the active feed and live in Completed Activities — unless the caller
    # explicitly filters for one of those statuses.
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if status not in ACTIVE_MY_PLAN_EXCLUDED_STATUSES:
        qs = qs.exclude(status__in=ACTIVE_MY_PLAN_EXCLUDED_STATUSES)
    if scope.partner_ids:
        qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
    else:
        # Both id spaces for the caller's own work (see owner_ids). Never the
        # supervisees: My Plan is the lead's personal list, and a CCEO's work
        # here offered Complete and Reschedule the lead could not use
        # (Programme Lead walk, 2026-09-14). Team work lives on Team Oversight.
        staff_ids = [s for s in owner_ids(principal) if s]
        qs = qs.filter(staff_my_plan_q(staff_ids, principal))

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

    # 5. Apply selected filters to the query
    # My Plan had no search of any kind — not a control, not a query path — so
    # the only way to find one activity in a week's feed was to read the feed.
    # It runs after the scope constraint above and before the period slicing
    # below, so a query narrows the plan the user already owns.
    #
    # activity_purpose_text is included because it is what the row actually
    # shows a user; matching only structural fields would leave them searching
    # for words they can see on screen and getting nothing back.
    search_q = str(query.get("q") or "").strip()
    if search_q:
        qs = qs.filter(
            Q(school__name__icontains=search_q)
            | Q(school__school_id__icontains=search_q)
            | Q(cluster__name__icontains=search_q)
            | Q(school__district__name__icontains=search_q)
            | Q(activity_purpose_text__icontains=search_q)
        )

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
    # My Plan shows strictly upcoming plans for weekly, monthly, quarterly, and Annual (FY) feeds.
    # Past-due uncompleted plans appear exclusively in "What needs you now" on the Dashboard.
    upcoming_filter = (
        Q(planned_date__gte=today)
        | Q(planned_date__isnull=True, scheduled_date__date__gte=today)
        | Q(planned_date__isnull=True, scheduled_date__isnull=True)
    )
    if status not in ACTIVE_MY_PLAN_EXCLUDED_STATUSES:
        # Work a reviewer sent back stays on the plan whatever its date: it
        # is waiting on this person to fix and resubmit it, and a returned
        # visit dated last week vanished from My Plan along with the reason it
        # was returned (owner, 2026-09-24: "the staff can resubmit after
        # fixing the issue").
        from apps.activities.services import RETURNED_STATUSES

        qs_period = qs_period.filter(
            upcoming_filter
            | Q(status__in=COMPLETED_WORK_STATUSES)
            | Q(status__in=RETURNED_STATUSES)
        )

    # 7. Compute KPI values for upcoming plans
    current_week_start, current_week_end = get_week_date_range(
        today.year, today.month, min(5, (today.day - 1) // 7 + 1)
    )
    period_totals = qs.filter(upcoming_filter).aggregate(
        week=Count(
            "pk", filter=_scheduled_in_range(current_week_start, current_week_end)
        ),
        month=Count(
            "pk",
            filter=_scheduled_in_range(
                date(today.year, today.month, 1),
                date(
                    today.year,
                    today.month,
                    calendar.monthrange(today.year, today.month)[1],
                ),
            ),
        ),
        quarter=Count("pk", filter=Q(quarter=get_quarter_for_date(today))),
        fy=Count("pk"),
    )
    planned_this_week = period_totals["week"]
    planned_this_month = period_totals["month"]
    planned_this_quarter = period_totals["quarter"]
    planned_this_fy = period_totals["fy"]

    # One scoped scan answers all five period metrics instead of five
    # separate database round trips for every person opening My Plan.
    activity_totals = qs_period.aggregate(
        visits=Count(
            "pk",
            filter=Q(
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
            ),
        ),
        trainings=Count(
            "pk",
            filter=Q(
                activity_type__in=[
                    "cluster_training",
                    "core_training",
                    "training",
                    "in_school_training",
                    "school_improvement_training",
                    "cluster_training_ssa_collection",
                ]
            ),
        ),
        meetings=Count(
            "pk",
            filter=Q(
                activity_type__in=["cluster_meeting", "cluster_meeting_ssa_review"]
            ),
        ),
        total=Count("pk"),
        completed=Count("pk", filter=Q(status__in=COMPLETED_WORK_STATUSES)),
    )
    visits_scheduled = activity_totals["visits"]
    trainings_scheduled = activity_totals["trainings"]
    meetings_scheduled = activity_totals["meetings"]
    total_period_count = activity_totals["total"]
    completed_period_count = activity_totals["completed"]
    # An empty period is "nothing was planned", not "0% of it is done". The
    # previous expression returned 0 for both, so a person with no plan and a
    # person who had delivered none of their plan saw the same tile.
    completion_share = MetricValue.ratio(completed_period_count, total_period_count)
    completion_readiness = (
        int(completion_share.value) if completion_share.state.is_measured else 0
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

    # Built through the metric registry so each tile carries its own key,
    # period, scope and drill-down, and so an absent value says why rather than
    # showing a zero. Labels, units and definitions come from
    # apps/core/metrics/registry.py -- not from strings retyped here.
    # (metric key, measured value, icon, variant) -- icon and variant are the
    # only presentation choices left to the caller; everything else comes from
    # the registry.
    my_plan_tiles = (
        (
            "my_plan_activities_planned_week",
            MetricValue.measured(planned_this_week),
            "calendar",
            "info",
        ),
        (
            "my_plan_activities_planned_month",
            MetricValue.measured(planned_this_month),
            "chart",
            "blue",
        ),
        (
            "my_plan_activities_planned_quarter",
            MetricValue.measured(planned_this_quarter),
            "calendar",
            "purple",
        ),
        (
            "my_plan_activities_planned_fy",
            MetricValue.measured(planned_this_fy),
            "calendar",
            "warning",
        ),
        (
            "my_plan_visits_scheduled_period",
            MetricValue.measured(visits_scheduled),
            "school",
            "blue",
        ),
        (
            "my_plan_trainings_scheduled_period",
            MetricValue.measured(trainings_scheduled),
            "target",
            "purple",
        ),
        (
            "my_plan_cluster_meetings_scheduled_period",
            MetricValue.measured(meetings_scheduled),
            "users",
            "warning",
        ),
        (
            "my_plan_completion_readiness_pct",
            completion_share,
            "check",
            "success",
        ),
    )

    # `render_strip` refuses to emit the same metric twice in one strip. The
    # old items also carried `raw_value`; nothing reads it -- no template, no
    # view, no script -- here or on the other 56 tiles that set it, so it is
    # dropped rather than carried forward. `value` is the unformatted number
    # and `display_value` the formatted one.
    kpi_strip_items = render_strip(
        [
            render_metric(key, value, drilldown_url="/my-plan")
            for key, value, _icon, _variant in my_plan_tiles
        ]
    )
    for item, (_key, _value, icon, variant) in zip(kpi_strip_items, my_plan_tiles):
        item["icon"] = icon
        item["variant"] = variant

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
    from apps.planning.visit_gate import PROGRAMME_SCHOOL_TYPES
    from apps.core.enums import SchoolType

    programme_school_work = {kind: [] for kind in PROGRAMME_SCHOOL_TYPES}
    core_school_visits_list = []
    core_school_trainings_list = []
    # Dated non-school programme work (conferences, camps, exhibitions) has no
    # school or cluster, so it matched none of the three category tables above
    # and was invisible on the page even though the urgency buckets held it.
    programme_activities_list = []

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
        .prefetch_related(
            "schedule_cost_lines",
            # The badge block walks cost line -> weekly request line -> weekly
            # fund request for every row, so prefetch the whole chain rather
            # than paying two queries per activity to rediscover it.
            "schedule_cost_lines__weekly_request_lines__weekly_fund_request",
            # advance_requests hangs off the cost line, not the activity --
            # compute_next_action walks it for every row.
            "schedule_cost_lines__advance_requests",
        )
        .order_by("planned_date", "created_at")
    )

    from apps.budget.costing_service import planned_minimum_amounts

    minimum_amounts = planned_minimum_amounts(activities)

    # Core-school sequence numbers (V1..V8 / T1..T8) and the "n/8 Completed"
    # progress used to be three per-row COUNT queries inside the loop below.
    # That made /my-plan O(number of core activities): the scaling gate
    # measured it growing 131 -> 231 queries when the school count merely
    # doubled, which at production scale is tens of thousands of queries for
    # one page load.
    #
    # All three are counts over the same (school, fy) partition, so they
    # collapse into two grouped queries here and pure dict lookups in the loop.
    core_activities = [
        a
        for a in activities
        if a.school_id and a.school and a.school.school_type == "core"
    ]
    # V1..V4 / T1..T4 and the package progress come from the CoreActivitySlot
    # the activity was booked into, not from counting activities of a given
    # type. Two reasons, and the second is a bug this used to have:
    #
    # * The slot IS the package. Its sequence_number is the number the Core
    #   Schools page, the drawer's "First/Second/Third Training" chooser and
    #   assert_can_schedule all speak in, so reading it keeps every surface
    #   saying the same V2 or T3 about the same piece of work.
    # * There is no "core_training" activity. A Core training is delivered by
    #   the standard In-school Training workflow — activity_type
    #   "in_school_training", with the catalogue course naming it — so the old
    #   query matched nothing and every core training on this page was numbered
    #   "" and counted as no progress at all (owner, 2026-09-17: core training
    #   scheduling "is not saving"). The visits half worked, which is why only
    #   trainings looked lost.
    core_slot_by_activity: dict[str, tuple[str, int]] = {}
    core_progress_by_activity: dict[str, str] = {}
    if core_activities:
        from apps.core_schools.models import CoreActivitySlot

        core_school_codes = {
            a.school.school_id for a in core_activities if a.school.school_id
        }
        # NOT filtered by the activities' fiscal year. A package belongs to one
        # FY; its work no longer has to — a partner may date an FY2026
        # assignment into October, which is FY2027 — so matching the plan's fy
        # against the ACTIVITY's finds nothing and the row loses its number
        # and its progress. The activity id is unique, so the school is filter
        # enough.
        slot_rows = CoreActivitySlot.objects.filter(
            core_plan__school_id__in=core_school_codes,
        ).values_list(
            "activity_id",
            "activity_type",
            "sequence_number",
            "status",
            "core_plan__school_id",
            "core_plan__fy",
        )
        plan_of_activity: dict[str, tuple] = {}
        taken: dict[tuple, set] = {}
        done: dict[tuple, set] = {}
        for activity_id, slot_kind, sequence, status, plan_school, plan_fy in slot_rows:
            plan = (plan_school, plan_fy)
            # The package is spoken of as 4 visits + 4 trainings everywhere
            # else, so the onboarding assessment slot is not in the
            # denominator — "1/9" would not match any other surface.
            if slot_kind in ("visit", "training"):
                taken.setdefault(plan, set()).add((slot_kind, sequence))
            if activity_id:
                core_slot_by_activity[activity_id] = (slot_kind, sequence)
                plan_of_activity[activity_id] = plan
            if _slot_status_is_complete(status) and slot_kind in ("visit", "training"):
                done.setdefault(plan, set()).add((slot_kind, sequence))
        # Progress is the row's OWN package: how many of its slots are done,
        # out of how many that package holds. Only a row that occupies a slot
        # gets one — a core school's non-package work is not 1/8 of anything.
        for activity_id, plan in plan_of_activity.items():
            core_progress_by_activity[activity_id] = (
                f"{len(done.get(plan, ()))}/{len(taken.get(plan, ()))} Completed"
            )

    # How many live schools each listed cluster holds — one grouped count for
    # the whole page. This was a COUNT per row inside the loop below: 404 of
    # the 430 queries on a CCEO's My Plan with a production-sized portfolio
    # (performance rescue, 2026-09-23). Same filter, same default manager.
    cluster_ids = {a.cluster.id for a in activities if a.cluster_id and a.cluster}
    cluster_school_counts = (
        dict(
            School.objects.filter(cluster_id__in=cluster_ids)
            .values_list("cluster_id")
            .annotate(n=Count("id"))
            .values_list("cluster_id", "n")
        )
        if cluster_ids
        else {}
    )

    for a in activities:
        status_label, status_class = get_activity_status_label_and_class(a, today)
        next_act = compute_next_action(a, today)
        # Budget status and badges
        badges = []
        # .first() issues a fresh LIMIT 1 query even when the relation is
        # prefetched -- only .all() reads the prefetch cache. Using .first()
        # here (and on the nested relations below) meant three extra queries
        # per row, which is most of the O(n) growth the scaling gate caught.
        first_line = next(iter(a.schedule_cost_lines.all()), None)
        budget_status = "No Budget"
        budget_status_color = "slate"

        if first_line:
            wfr_line = next(iter(first_line.weekly_request_lines.all()), None)
            if wfr_line and getattr(wfr_line, "weekly_fund_request", None):
                wfr = wfr_line.weekly_fund_request
                if wfr.status == "pending_responsible_confirmation":
                    badges.append(("In Weekly Request", "amber"))
                    budget_status = "In Weekly Request"
                    budget_status_color = "blue"
                elif wfr.status == "submitted_to_pl":
                    badges.append(("Awaiting PL Approval", "amber"))
                    budget_status = "Awaiting PL Approval"
                    budget_status_color = "amber"
                elif wfr.status == "submitted_to_cd":
                    badges.append(("Awaiting CD Approval", "amber"))
                    budget_status = "Awaiting CD Approval"
                    budget_status_color = "amber"
                elif wfr.status in (
                    "returned_by_pl",
                    "returned_by_cd",
                    "returned_by_accountant",
                ):
                    badges.append(("Request Returned", "red"))
                    budget_status = "Request Returned"
                    budget_status_color = "red"
                elif wfr.status == "confirmed_for_advance":
                    badges.append(("Approved — Ready for Disbursement", "green"))
                    budget_status = "Approved"
                    budget_status_color = "green"
                elif wfr.status == "disbursed":
                    badges.append(("Disbursed", "green"))
                    budget_status = "Disbursed"
                    budget_status_color = "green"
                else:
                    badges.append(("Included in Request", "blue"))
                    budget_status = "Included in Request"
                    budget_status_color = "blue"
            else:
                badges.append(("Budget Created", "blue"))
                budget_status = "Budget Created"
                budget_status_color = "blue"
        else:
            badges.append(("No Budget", "slate"))
            budget_status = "No Budget"
            budget_status_color = "slate"

        # Verification status: "IA pending for PL and PL pending for CCEO"
        is_pl_viewer = getattr(scope, "active_role", "") in (
            "Program Lead",
            "Country Director",
            "Impact Assessment",
            "Regional Programme Lead",
            "Admin",
        ) or getattr(principal, "active_role", "") in (
            "Program Lead",
            "Country Director",
            "Impact Assessment",
            "Regional Programme Lead",
            "Admin",
        )
        if (
            a.status in ("ia_verified", "accountant_confirmed", "closed")
            or a.ia_verification_status == "confirmed"
        ):
            verification_status = "Verified"
            verification_color = "green"
        elif (
            a.status in ("returned_by_pl", "returned_by_ia")
            or a.ia_verification_status == "returned"
        ):
            verification_status = "Returned"
            verification_color = "red"
        elif is_pl_viewer:
            verification_status = "IA pending"
            verification_color = "purple"
        else:
            verification_status = "PL pending"
            verification_color = "purple"

        is_completed_act = (
            a.status in ("completed", "ia_verified", "accountant_confirmed", "closed")
            or a.status in COMPLETED_WORK_STATUSES
        )

        # A finished stage says so in the same words every time — "<stage>
        # complete" — so a row can be read down its badges without translating
        # "Verified", "Entered", "Uploaded" and "Cleared" into the same idea.
        if a.status in COMPLETED_WORK_STATUSES:
            badges.append(("Activity complete", "green"))

        # Evidence status
        if a.status == "completed":
            if a.evidence_status == "uploaded":
                badges.append(("Evidence complete", "green"))
            else:
                badges.append(("Evidence pending", "amber"))

        # SF ID status
        if a.status in [
            "completed",
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
        ]:
            if a.salesforce_activity_id:
                badges.append(("SF ID complete", "green"))
            else:
                badges.append(("SF ID missing", "red"))

        # IA status
        if a.ia_verification_status == "pending":
            badges.append(("IA pending", "purple"))
        elif a.ia_verification_status == "confirmed":
            badges.append(("IA complete", "green"))
        elif a.ia_verification_status == "returned":
            badges.append(("Returned", "red"))

        # Accounts status
        if a.payment_status in ("pending", "pending_ia"):
            badges.append(("Accounts pending", "amber"))
        elif a.payment_status in ("cleared", "accountant_cleared"):
            badges.append(("Accounts complete", "green"))
        elif a.payment_status in ("disbursed", "netsuite_accountability"):
            badges.append(("Accountability Pending", "amber"))
        elif a.payment_status == "paid":
            badges.append(("Paid", "green"))

        # Core details
        is_core = a.school and a.school.school_type == "core"
        visit_number = ""
        training_number = ""
        core_progress = ""
        core_slot_kind = ""
        if is_core:
            slot = core_slot_by_activity.get(a.id)
            if slot:
                core_slot_kind, num = slot
                if core_slot_kind == "visit":
                    visit_number = f"V{num}"
                elif core_slot_kind == "training":
                    training_number = f"T{num}"
            core_progress = core_progress_by_activity.get(a.id, "")

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
            # The reviewer's own words, from the one field every return path
            # writes (apps.activities.return_notes). ``last_reason`` is the
            # reschedule/cancel note and said nothing about the return.
            from apps.activities import return_notes

            return_reason = return_notes.note_for(a) or "Correction required"
            returned_by = return_notes.returned_by(a)

        cluster_district_name = ""
        if a.cluster and getattr(a.cluster, "district", None):
            cluster_district_name = getattr(a.cluster.district, "name", "") or ""
        elif a.school and getattr(a.school, "district", None):
            cluster_district_name = getattr(a.school.district, "name", "") or ""

        # Staff planning displays the minimum estimate; payment ledgers retain
        # country operational costs and are never rewritten for presentation.
        budget_total = minimum_amounts.get(a.id)

        # Construct final dict
        activity_data = {
            "id": a.id,
            "activity_type": a.activity_type,
            "activity_type_label": a.get_activity_type_display(),
            "status": a.status,
            "planned_date": a.planned_date,
            "quarter": a.quarter,
            # School details. A non-school programme activity (conference,
            # camp, exhibition) legitimately has NO school and NO cluster, so
            # every school/cluster attribute here must tolerate both being
            # absent — `a.school.cluster_id` used to run whenever there was no
            # cluster, which 500'd the whole My Plan page for the responsible
            # person the moment they were given programme work.
            "school_id": a.school.school_id if a.school else "",
            "school_name": (
                a.school.name
                if a.school
                else (a.venue or a.activity_name_snapshot or "Programme activity")
                if (
                    a.planning_source == "manual_work_plan"
                    or a.activity_type in PROGRAMME_EVENT_TYPES
                )
                else (a.cluster.name if a.cluster else "Unknown School")
            ),
            "school_district": (
                a.school.district.name
                if a.school
                else a.event_district.name
                if a.event_district_id
                else "Unknown"
            ),
            "school_sub_county": a.school.sub_county.name
            if a.school and a.school.sub_county
            else "",
            "school_cluster_name": (
                a.cluster.name
                if a.cluster
                else (a.school.cluster_id or "")
                if a.school
                else ""
            ),
            "school_ssa_status": a.school.get_current_fy_ssa_status_display()
            if a.school
            else "No SSA",
            # Cluster details
            # The trainings card lists in-school trainings beside cluster
            # trainings. An in-school training has a school and no cluster; it
            # used to read "Unknown Cluster" there (owner, 2026-09-12), so the
            # place is whichever the work has, with a link to its profile.
            "cluster_name": (
                a.cluster.name
                if a.cluster
                else (a.school.name if a.school else "Unassigned")
            ),
            "place_url": (
                f"/clusters/{a.cluster.id}"
                if a.cluster
                else (f"/schools/{a.school.id}" if a.school else "")
            ),
            "cluster_id": a.cluster.id if a.cluster else "",
            "cluster_district": cluster_district_name or "—",
            "cluster_school_count": cluster_school_counts.get(a.cluster.id, 0)
            if a.cluster
            else 0,
            # Who turned up if the activity has been delivered, otherwise who
            # was planned for — and nothing at all when neither is recorded.
            # This used to fall through to a literal 20, so every school visit
            # and cluster meeting in the platform (all of which store None)
            # reported twenty expected participants that nobody had planned
            # for (owner, 2026-09-17). A made-up number on a planning page is
            # worse than a blank: it is budgeted against.
            "expected_participants": (
                (a.teachers_attended or 0)
                + (a.leaders_attended or 0)
                + (a.other_participants or 0)
            )
            or a.expected_participants
            or None,
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
            "purpose": (
                a.activity_purpose_text
                or (
                    visit_purpose_label(a.purpose_type, fallback="")
                    if a.purpose_type
                    else ""
                )
                or a.get_activity_type_display()
            ),
            "focus_intervention": a.get_focus_intervention_display()
            if a.focus_intervention
            else "General",
            "owner": users_map.get(a.responsible_staff_id, "Staff"),
            "execution_role": "Staff" if a.delivery_type == "staff" else "Partner",
            "is_partner_ssa_support": is_partner_ssa_support_activity(a),
            "budget_total": budget_total,
            "salesforce_activity_id": a.salesforce_activity_id,
            "evidence_status": a.evidence_status,
            "ia_verification_status": a.ia_verification_status,
            "payment_status": a.payment_status,
            "budget_status": budget_status,
            "budget_status_color": budget_status_color,
            "verification_status": verification_status,
            "verification_color": verification_color,
            "is_completed": is_completed_act,
            # Next Action & Badges
            "next_action": next_act,
            "badges": badges,
            "status_label": status_label,
            "status_class": status_class,
            "status_tone": status_tone(status_class),
        }

        # Legacy lists for compatibility
        if a.planning_source == "manual_work_plan" or (
            a.activity_type in PROGRAMME_EVENT_TYPES
        ):
            programme_activities_list.append(activity_data)
        elif (
            a.school
            and a.school.school_type in PROGRAMME_SCHOOL_TYPES
            and a.activity_type in VISIT_TYPES + TRAINING_TYPES
        ):
            programme_school_work[a.school.school_type].append(activity_data)
        elif is_core and (core_slot_kind == "visit" or a.activity_type in VISIT_TYPES):
            core_school_visits_list.append(activity_data)
        elif is_core and (
            core_slot_kind == "training" or a.activity_type in TRAINING_TYPES
        ):
            core_school_trainings_list.append(activity_data)
        elif a.activity_type in [
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

    # ── Cluster invited-school expansion ────────────────────────────────────
    # A cluster training is planned on a cluster, reaching the schools invited
    # or confirmed in that cluster. If a cluster training row is left without a school,
    # it displays with blank School ID and "Unknown School" in the trainings table.
    # We expand each cluster training into its confirmed / invited member schools
    # so every school with training planned is listed with its School ID and Name.
    #
    # A Core School among them is a package training, not a cluster row
    # (owner, 2026-09-21: "the core schools trained through cluster group
    # training or cluster meeting should contribute to the core school
    # training packages ... it should move to core school training planned
    # table"). Its slot already carries the credit
    # (apps.core_schools.cluster_credit); the expansion reads that slot for
    # the T-number and moves the row to the package table, so one session
    # shows as a cluster training for the client schools it reached and as
    # T2 of the package for the Core School that sat in it.
    from collections import defaultdict
    from apps.activities.models import ClusterActivityAttendance
    from apps.schools.models import School as _School
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    _cluster_act_rows = [
        row
        for row in cluster_trainings_list
        if row.get("cluster_id") and not row.get("school_id")
    ]
    if _cluster_act_rows:
        _cluster_act_ids = [r["id"] for r in _cluster_act_rows if r.get("id")]
        _cluster_ids = list(
            {r["cluster_id"] for r in _cluster_act_rows if r.get("cluster_id")}
        )

        # 1. Fetch explicitly invited/attended schools from ClusterActivityAttendance
        _recorded_act_ids = set(
            ClusterActivityAttendance.objects.filter(
                activity_id__in=_cluster_act_ids,
            ).values_list("activity_id", flat=True)
        )
        _att_records = list(
            ClusterActivityAttendance.objects.filter(activity_id__in=_cluster_act_ids)
            .filter(Q(invited=True) | Q(attended=True))
            .values_list("activity_id", "school_id")
        )
        _att_by_act = defaultdict(list)
        _att_school_ids = set()
        for _act_id, _sid in _att_records:
            if _sid not in _att_by_act[_act_id]:
                _att_by_act[_act_id].append(_sid)
            _att_school_ids.add(_sid)

        # 2. Fetch member schools for the clusters involved
        _member_schools = list(
            _School.objects.filter(
                cluster_id__in=_cluster_ids,
                deleted_at__isnull=True,
            ).select_related("district", "sub_county")
        )
        _schools_by_cluster = defaultdict(list)
        _schools_by_cluster_confirmed = defaultdict(list)
        for _s in _member_schools:
            _schools_by_cluster[_s.cluster_id].append(_s)
            if _s.cluster_status == "clustered" and (
                not _s.operational_status or _s.operational_status in OPERATING_STATUSES
            ):
                _schools_by_cluster_confirmed[_s.cluster_id].append(_s)

        # 3a. The Core package slots these very sessions occupy, keyed by
        # (activity, school business id) — one session fills a slot at each
        # Core School that sat in it, so activity id alone cannot answer this.
        from apps.core_schools.models import CoreActivitySlot

        _core_slot_rows = CoreActivitySlot.objects.filter(
            activity_id__in=_cluster_act_ids,
            activity_type="training",
        ).values_list("activity_id", "core_plan__school_id", "sequence_number")
        _cluster_core_slot = {
            (_act, _plan_school): _seq for _act, _plan_school, _seq in _core_slot_rows
        }
        # "n/m Completed" for each of those packages, read the way the rest of
        # this page reads it: over the 4 + 4 slots, with the onboarding
        # assessment slot outside the denominator.
        _cluster_core_progress: dict[str, str] = {}
        _core_plan_schools = {school for _act, school in _cluster_core_slot}
        if _core_plan_schools:
            _package_rows = CoreActivitySlot.objects.filter(
                core_plan__school_id__in=_core_plan_schools,
                activity_type__in=("visit", "training"),
            ).values_list(
                "core_plan__school_id",
                "core_plan__fy",
                "activity_type",
                "sequence_number",
                "status",
            )
            _package_taken: dict[tuple, set] = defaultdict(set)
            _package_done: dict[tuple, set] = defaultdict(set)
            _package_of_school: dict[str, tuple] = {}
            for _sch, _fy, _kind, _seq, _slot_status in _package_rows:
                _key = (_sch, _fy)
                _package_taken[_key].add((_kind, _seq))
                if _slot_status_is_complete(_slot_status):
                    _package_done[_key].add((_kind, _seq))
                _package_of_school.setdefault(_sch, _key)
            for _sch, _key in _package_of_school.items():
                _cluster_core_progress[_sch] = (
                    f"{len(_package_done.get(_key, ()))}/"
                    f"{len(_package_taken.get(_key, ()))} Completed"
                )

        # 3. Lookup for schools (include any attendance schools from other clusters)
        _school_lookup = {_s.id: _s for _s in _member_schools}
        _missing_ids = _att_school_ids - set(_school_lookup.keys())
        if _missing_ids:
            for _s in _School.objects.filter(id__in=_missing_ids).select_related(
                "district", "sub_county"
            ):
                _school_lookup[_s.id] = _s

        # Reconstruct cluster_trainings_list
        _new_cluster_trainings_list = []
        for row in cluster_trainings_list:
            if not (row.get("cluster_id") and not row.get("school_id")):
                # Already a school-specific row
                _new_cluster_trainings_list.append(row)
                continue

            _act_id = row.get("id")
            _target_schools = []
            if _act_id in _att_by_act and _att_by_act[_act_id]:
                _target_schools = [
                    _school_lookup[_sid]
                    for _sid in _att_by_act[_act_id]
                    if _sid in _school_lookup
                ]
            if (
                not _target_schools
                and row.get("cluster_id")
                and _act_id not in _recorded_act_ids
            ):
                _cid = row["cluster_id"]
                _target_schools = (
                    _schools_by_cluster_confirmed.get(_cid)
                    or _schools_by_cluster.get(_cid)
                    or []
                )

            act_obj = next((a for a in activities if a.id == _act_id), None)
            pps = None
            if act_obj:
                pps = getattr(act_obj, "participants_per_school", None) or getattr(
                    act_obj, "teachers_per_school", None
                )
            if not pps:
                total_p = row.get("expected_participants")
                if total_p and _target_schools:
                    pps = max(1, total_p // len(_target_schools))
                else:
                    pps = 2
            per_school_meal_cost = pps * 5000

            if _target_schools:
                for _school in _target_schools:
                    _school_row = dict(row)
                    _school_row["school_id"] = _school.school_id or str(_school.id)
                    _school_row["school_name"] = _school.name
                    _school_row["school_district"] = (
                        _school.district.name if _school.district_id else "Unknown"
                    )
                    _school_row["school_sub_county"] = (
                        _school.sub_county.name if _school.sub_county_id else ""
                    )
                    _school_row["school_cluster_name"] = row.get("cluster_name") or ""
                    _school_row["place_url"] = (
                        f"/schools/{_school.school_id or _school.id}"
                    )
                    _school_row["is_cluster_invited"] = True
                    _school_row["expected_participants"] = pps
                    _school_row["budget_total"] = per_school_meal_cost
                    _slot_seq = _cluster_core_slot.get((_act_id, _school.school_id))
                    if _school.school_type in PROGRAMME_SCHOOL_TYPES:
                        _school_row["core_progress"] = ""
                        _school_row["training_number"] = ""
                        programme_school_work[_school.school_type].append(_school_row)
                    elif _school.school_type == "core":
                        # The package's own record of this session. It leaves
                        # the cluster table entirely: counting it in both
                        # would show one training twice.
                        _school_row["training_number"] = (
                            f"T{_slot_seq}" if _slot_seq else ""
                        )
                        _school_row["core_progress"] = _cluster_core_progress.get(
                            _school.school_id, ""
                        )
                        core_school_trainings_list.append(_school_row)
                    else:
                        _new_cluster_trainings_list.append(_school_row)
            else:
                _fallback_row = dict(row)
                _fallback_row["school_name"] = (
                    row.get("cluster_name") or "Cluster Training"
                )
                _fallback_row["place_url"] = (
                    f"/clusters/{row.get('cluster_id')}"
                    if row.get("cluster_id")
                    else ""
                )
                _fallback_row["expected_participants"] = pps
                _fallback_row["budget_total"] = per_school_meal_cost
                _new_cluster_trainings_list.append(_fallback_row)

        cluster_trainings_list = _new_cluster_trainings_list

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
                else (
                    a.cluster.name
                    if a.cluster
                    else (a.activity_name_snapshot or a.venue or "Activity")
                ),
                "purpose": (
                    a.activity_purpose_text
                    or (
                        visit_purpose_label(a.purpose_type, fallback="")
                        if a.purpose_type
                        else ""
                    )
                    or a.get_activity_type_display()
                ),
                "district": a.school.district.name
                if a.school
                else (
                    a.cluster.district.name
                    if a.cluster
                    else (a.event_district.name if a.event_district_id else "Unknown")
                ),
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
        status__in=COMPLETED_WORK_STATUSES, evidence_status="none"
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
        status__in=COMPLETED_WORK_STATUSES, salesforce_activity_id__isnull=True
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

    from urllib.parse import urlencode

    _base_query = urlencode(
        {
            key: value
            for key, value in (query or {}).items()
            if value and isinstance(value, (str, int))
        }
    )
    if _base_query:
        _base_query += "&"

    # The cards no longer page ten rows at a time. Ten rows out of a year is
    # the shape of a week, and hiding the rest behind "Next" is what made the
    # plan unreadable as a plan. Every row the selected period holds is
    # rendered, oldest first.
    return {
        "live": True,
        "period": period,
        # Only an explicitly requested period rides along with the filter form.
        # Echoing a derived one would pin the page to the month it happens to
        # be showing, and the next filter change could never widen back out.
        "period_param": explicit_period,
        "fy": fy,
        # The selects show what is actually narrowing the feed: None reads as
        # "All" rather than as this month, which is the difference between a
        # year and one of its twelve parts.
        "selected_month": selected_month,
        "selected_quarter": selected_quarter,
        "fy_prev": fy,
        "quarter_prev": selected_quarter or "all",
        "period_label": period_label,
        "months": months,
        "quarters": ["Q1", "Q2", "Q3", "Q4"],
        "districts": districts,
        "selected_district": district_id,
        "staff_users": staff_users,
        "selected_staff": staff_id,
        "selected_activity_type": activity_type,
        "selected_status": status,
        # What the advanced-filter drawer holds, and nothing else — the
        # drawer's "· Applied" badge would otherwise light up for a quarter or
        # month chosen out in the toolbar.
        "advanced_filters_active": any(
            [
                district_id and district_id != "all",
                staff_id and staff_id != "all",
                activity_type and activity_type != "all",
                status and status != "all",
            ]
        ),
        # Whether any filter is narrowing the view — drives Clear Filters, so
        # it answers for the whole toolbar, quarter and month included.
        # Computed server-side because the URL, not Alpine, is authoritative.
        "filters_active": any(
            [
                selected_quarter,
                selected_month is not None,
                district_id and district_id != "all",
                staff_id and staff_id != "all",
                activity_type and activity_type != "all",
                status and status != "all",
            ]
        ),
        "my_plan_base_query": _base_query,
        # The canonical fiscal-year list. The select was hard-coded to
        # FY2023–FY2026, so an October 2026 cluster meeting (FY2027) had no
        # year to be shown under, and a link to it rendered with nothing
        # selected — the next filter change posted FY2023 (2026-09-15).
        "fy_options": fy_options(),
        "kpis": kpis,
        "kpi_strip_items": kpi_strip_items,
        # Each card carries every row of the selected period. `*_all` stays
        # because counts, KPIs and the CSV export read it; it is now the same
        # list as the card's own.
        "programme_school_work": [
            {"kind": kind, "label": dict(SchoolType.choices)[kind], "rows": rows}
            for kind, rows in programme_school_work.items()
            if rows
        ],
        "core_school_visits": core_school_visits_list,
        "core_school_visits_all": core_school_visits_list,
        "core_school_visits_completed": sum(
            1
            for row in core_school_visits_list
            if row["status"] in COMPLETED_WORK_STATUSES
        ),
        "core_school_trainings": core_school_trainings_list,
        "core_school_trainings_all": core_school_trainings_list,
        "core_school_trainings_completed": sum(
            1
            for row in core_school_trainings_list
            if row["status"] in COMPLETED_WORK_STATUSES
        ),
        "school_visits": school_visits_list,
        "school_visits_all": school_visits_list,
        "cluster_trainings": cluster_trainings_list,
        "cluster_trainings_all": cluster_trainings_list,
        "cluster_meetings": cluster_meetings_list,
        "cluster_meetings_all": cluster_meetings_list,
        "programme_activities": programme_activities_list,
        "programme_activities_all": programme_activities_list,
        "waiting_on_me": waiting_on_me_list,
        "due_today": due_today_list,
        "this_week": this_week_list,
        # Rendered as the priority-queue badge; computed here so the template
        # does not have to add two list lengths together.
        "priority_count": len(waiting_on_me_list) + len(due_today_list),
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
