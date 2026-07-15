"""StaffPDService — the single shared engine behind My Professional Development.

Every eligible employee (CCEO, PL, CD, RVP, IA, Accountant, HR, Project
Coordinator, Admin) reads and writes through this one service — no
role-specific PD calculation logic exists anywhere else. Allocation balances
are always DERIVED from the employee's own requests at read time; nothing is
cached, so there is no manual or drifting remaining-fund number.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.core.fy import get_operational_fy

from apps.professional_development.models import (
    ACTIVE_COURSE_STATUSES,
    CLOSED_STATUSES,
    COMMITTED_STATUSES,
    FUNDED_TYPES,
    PDStatus,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentRequest,
)

# Ordered lifecycle for the Course Progress Tracker timeline. Each tuple is
# (status_reached_at_or_after, label). The UI marks every step up to and
# including the current status as done, the current step as active, and the
# rest as pending — a straight lookup, no cross-table joins.
TIMELINE_STEPS = [
    ("submitted", "Request Submitted"),
    ("supervisor", "Approved by Supervisor"),
    ("hr", "Approved by HR"),
    ("funds", "Funds Disbursed"),
    ("enrolled", "Enrollment Confirmed"),
    ("in_progress", "Course In Progress"),
    ("certificate", "Upload Certificate"),
    ("bamboohr", "BambooHR Upload Confirmation"),
    ("accountability", "Accountability & Expense ID"),
    ("signoff", "HR Sign Off"),
    ("closed", "Completed & Closed"),
]

# Map each PDStatus to the TIMELINE_STEPS index it is CURRENTLY WAITING ON
# (not the last thing that happened) — steps before this index are "done",
# this index is "active". E.g. SUBMITTED_TO_HR means the supervisor stage is
# already behind us and HR's decision (index 2) is what's pending now.
_STEP_INDEX = {
    PDStatus.DRAFT: -1,
    PDStatus.SUBMITTED_TO_SUPERVISOR: 1,
    PDStatus.RETURNED_BY_SUPERVISOR: 1,
    PDStatus.SUBMITTED_TO_HR: 2,
    PDStatus.RETURNED_BY_HR: 2,
    PDStatus.PENDING_EXCEPTION: 2,
    PDStatus.APPROVED_PENDING_FUNDING: 3,
    PDStatus.APPROVED_UNFUNDED: 4,
    PDStatus.DISBURSED: 4,
    PDStatus.ENROLLMENT_PENDING: 4,
    PDStatus.ENROLLMENT_CONFIRMED: 5,
    PDStatus.IN_PROGRESS: 5,
    PDStatus.ENDED: 6,
    PDStatus.MARKED_COMPLETE: 6,
    PDStatus.CERTIFICATE_UPLOADED: 7,
    PDStatus.BAMBOOHR_CONFIRMED: 8,
    PDStatus.ACCOUNTABILITY_SUBMITTED: 8,
    PDStatus.ACCOUNTABILITY_CLEARED: 9,
    PDStatus.AWAITING_HR_SIGNOFF: 9,
    PDStatus.COMPLETED_CLOSED: 10,
    PDStatus.REJECTED: 2,
    PDStatus.CANCELLED: 0,
    PDStatus.DEFERRED: 5,
    PDStatus.WITHDRAWN: 5,
}

NEXT_ACTION_BY_STATUS = {
    PDStatus.DRAFT: ("Continue Draft", "draft"),
    PDStatus.RETURNED_BY_SUPERVISOR: ("Fix Returned Request", "fix_supervisor"),
    PDStatus.RETURNED_BY_HR: ("Fix Returned Request", "fix_hr"),
    PDStatus.SUBMITTED_TO_SUPERVISOR: ("Awaiting Supervisor", None),
    PDStatus.SUBMITTED_TO_HR: ("Awaiting HR", None),
    PDStatus.PENDING_EXCEPTION: ("Awaiting Exception Approval", None),
    PDStatus.APPROVED_PENDING_FUNDING: ("Awaiting Disbursement", None),
    PDStatus.APPROVED_UNFUNDED: ("Confirm Enrollment", "confirm_enrollment"),
    PDStatus.DISBURSED: ("Confirm Fund Receipt", "confirm_enrollment"),
    PDStatus.ENROLLMENT_PENDING: ("Confirm Enrollment", "confirm_enrollment"),
    PDStatus.ENROLLMENT_CONFIRMED: ("Open Course", None),
    PDStatus.IN_PROGRESS: ("Open Course", None),
    PDStatus.ENDED: ("Mark Course Complete", "mark_complete"),
    PDStatus.MARKED_COMPLETE: ("Upload Certificate", "upload_certificate"),
    PDStatus.CERTIFICATE_UPLOADED: ("Confirm BambooHR Upload", "bamboohr"),
    PDStatus.BAMBOOHR_CONFIRMED: ("Submit Accountability", "accountability"),
    PDStatus.ACCOUNTABILITY_SUBMITTED: ("Awaiting Finance Clearance", None),
    PDStatus.ACCOUNTABILITY_CLEARED: ("Awaiting HR Sign-Off", None),
    PDStatus.AWAITING_HR_SIGNOFF: ("View HR Sign-Off", None),
    PDStatus.COMPLETED_CLOSED: ("Completed", None),
}


def _staff(user) -> StaffProfile | None:
    return getattr(user, "staff_profile", None)


def staff_display_info(user) -> dict:
    sp = _staff(user)
    supervisor_sp = None
    if sp:
        link = (
            StaffSupervisorAssignment.objects.filter(supervisee=sp)
            .select_related("supervisor__user")
            .first()
        )
        supervisor_sp = link.supervisor if link else None
    return {
        "staff_id": sp.id if sp else None,
        "staff_name": user.name,
        "position": sp.title if sp else None,
        "country": sp.country if sp else "Uganda",
        "department": sp.department if sp else None,
        "supervisor_staff_id": supervisor_sp.id if supervisor_sp else None,
        "supervisor_name": supervisor_sp.user.name if supervisor_sp else None,
    }


class StaffPDService:
    """Everything the My Professional Development page renders, strictly
    scoped to request.user — no other employee's PD file is ever visible."""

    # ── Allocation + derived balances ───────────────────────────────────────
    @staticmethod
    def get_or_create_allocation(user, fy: str) -> ProfessionalDevelopmentAllocation:
        sp = _staff(user)
        alloc, _ = ProfessionalDevelopmentAllocation.objects.get_or_create(
            staff_id=sp.id,
            fy=fy,
            defaults={"country": sp.country or "Uganda", "annual_allocation": 0},
        )
        return alloc

    @staticmethod
    def balances(user, fy: str) -> dict:
        """Remaining Available Fund = Annual Allocation − Active Committed
        − Accounted Used (mandate §4). Derived live from the requests."""
        sp = _staff(user)
        alloc = StaffPDService.get_or_create_allocation(user, fy)
        rows = ProfessionalDevelopmentRequest.objects.filter(staff_id=sp.id, fy=fy)

        committed = sum(
            r.requested_amount_cents for r in rows if r.status in COMMITTED_STATUSES
        )
        disbursed = sum(
            r.requested_amount_cents
            for r in rows
            if r.status
            in (
                PDStatus.DISBURSED,
                PDStatus.ENROLLMENT_PENDING,
                PDStatus.ENROLLMENT_CONFIRMED,
                PDStatus.IN_PROGRESS,
                PDStatus.ENDED,
                PDStatus.MARKED_COMPLETE,
                PDStatus.CERTIFICATE_UPLOADED,
                PDStatus.BAMBOOHR_CONFIRMED,
                PDStatus.ACCOUNTABILITY_SUBMITTED,
                PDStatus.ACCOUNTABILITY_CLEARED,
                PDStatus.AWAITING_HR_SIGNOFF,
                PDStatus.COMPLETED_CLOSED,
            )
        )
        accounted = sum(r.accounted_amount or 0 for r in rows)
        returned = sum(r.returned_amount or 0 for r in rows)
        remaining = alloc.annual_allocation - committed - accounted
        return {
            "allocation": alloc,
            "annual_allocation": alloc.annual_allocation,
            "committed": committed,
            "disbursed": disbursed,
            "accounted": accounted,
            "returned": returned,
            "remaining": max(0, remaining),
            "remaining_raw": remaining,
            "currency": alloc.currency,
        }

    # ── Allocation History (Quick Action drawer) — read-only, no side effects
    @staticmethod
    def allocation_history(user) -> list[dict]:
        sp = _staff(user)
        if not sp:
            return []
        fys = set(
            ProfessionalDevelopmentAllocation.objects.filter(
                staff_id=sp.id
            ).values_list("fy", flat=True)
        ) | set(
            ProfessionalDevelopmentRequest.objects.filter(staff_id=sp.id).values_list(
                "fy", flat=True
            )
        )
        allocs = {
            a.fy: a
            for a in ProfessionalDevelopmentAllocation.objects.filter(staff_id=sp.id)
        }
        rows = []
        for fy in sorted(fys, reverse=True):
            alloc = allocs.get(fy)
            reqs = ProfessionalDevelopmentRequest.objects.filter(staff_id=sp.id, fy=fy)
            committed = sum(
                r.requested_amount_cents for r in reqs if r.status in COMMITTED_STATUSES
            )
            accounted = sum(r.accounted_amount or 0 for r in reqs)
            annual = alloc.annual_allocation if alloc else 0
            rows.append(
                {
                    "fy": fy,
                    "currency": alloc.currency if alloc else "UGX",
                    "annual_allocation": annual,
                    "committed": committed,
                    "accounted": accounted,
                    "remaining": max(0, annual - committed - accounted),
                    "request_count": reqs.count(),
                    "completed_count": reqs.filter(
                        status=PDStatus.COMPLETED_CLOSED
                    ).count(),
                }
            )
        return rows

    # ── Page payload ─────────────────────────────────────────────────────────
    @staticmethod
    def get_page(user, fy: str | None = None) -> dict:
        sp = _staff(user)
        fy = fy or get_operational_fy()
        bal = StaffPDService.balances(user, fy)
        today = date.today()

        rows = list(
            ProfessionalDevelopmentRequest.objects.filter(
                staff_id=sp.id, fy=fy
            ).order_by("-created_at")
        )
        active = [r for r in rows if r.status in ACTIVE_COURSE_STATUSES]
        # "Current course" = the active one soonest to need employee action,
        # else the one currently in progress, else the most recent.
        current = None
        for r in rows:
            if r.status in (
                PDStatus.IN_PROGRESS,
                PDStatus.ENDED,
                PDStatus.MARKED_COMPLETE,
                PDStatus.CERTIFICATE_UPLOADED,
                PDStatus.BAMBOOHR_CONFIRMED,
                PDStatus.ACCOUNTABILITY_SUBMITTED,
                PDStatus.AWAITING_HR_SIGNOFF,
            ):
                current = r
                break
        if current is None and active:
            current = active[0]
        if current is None:
            # Still show the tracker while a request is in the approval
            # pipeline (submitted/pending exception/returned/approved and
            # awaiting funding) — the reference design's "Request Submitted"
            # step should appear as soon as a non-draft request exists, not
            # only once it becomes an "active" course.
            pipeline = [
                r
                for r in rows
                if r.status != PDStatus.DRAFT and r.status not in CLOSED_STATUSES
            ]
            if pipeline:
                current = pipeline[0]

        certs_pending = sum(
            1 for r in rows if r.status in (PDStatus.ENDED, PDStatus.MARKED_COMPLETE)
        )
        accountability_pending = sum(
            1
            for r in rows
            if r.funding_type in FUNDED_TYPES
            and r.status in (PDStatus.BAMBOOHR_CONFIRMED,)
        )
        completed = sum(1 for r in rows if r.status == PDStatus.COMPLETED_CLOSED)

        kpis = [
            {
                "key": "allocation",
                "label": "Annual PD Allocation",
                "icon": "currency",
                "variant": "primary",
                "value": f"{bal['currency']} {bal['annual_allocation']/100:,.0f}",
                "helper": f"FY {fy}",
            },
            {
                "key": "committed",
                "label": "Committed Amount",
                "icon": "chart",
                "variant": "default",
                "value": f"{bal['currency']} {bal['committed']/100:,.0f}",
                "helper": f"{round(bal['committed']/bal['annual_allocation']*100) if bal['annual_allocation'] else 0}% of allocation",
            },
            {
                "key": "used",
                "label": "Funds Used (Accounted)",
                "icon": "accountability",
                "variant": "default",
                "value": f"{bal['currency']} {bal['accounted']/100:,.0f}",
                "helper": f"{round(bal['accounted']/bal['annual_allocation']*100) if bal['annual_allocation'] else 0}% of allocation",
            },
            {
                "key": "remaining",
                "label": "Remaining Fund",
                "icon": "shield",
                "variant": "danger" if bal["remaining"] <= 0 else "success",
                "value": f"{bal['currency']} {bal['remaining']/100:,.0f}",
                "helper": f"{round(bal['remaining']/bal['annual_allocation']*100) if bal['annual_allocation'] else 0}% of allocation",
            },
            {
                "key": "active",
                "label": "Active Courses",
                "icon": "graduation",
                "variant": "primary",
                "value": str(len(active)),
                "helper": "In progress",
            },
            {
                "key": "cert_pending",
                "label": "Certificates Pending",
                "icon": "certificate",
                "variant": "warning" if certs_pending else "success",
                "value": str(certs_pending),
                "helper": "All up to date" if not certs_pending else "Action required",
            },
            {
                "key": "accountability_pending",
                "label": "Accountability Pending",
                "icon": "expense",
                "variant": "warning" if accountability_pending else "success",
                "value": str(accountability_pending),
                "helper": "All up to date"
                if not accountability_pending
                else "Action required",
            },
            {
                "key": "completed",
                "label": "Completed Courses",
                "icon": "signoff",
                "variant": "success",
                "value": str(completed),
                "helper": "This FY",
            },
        ]

        return {
            "fy": fy,
            "today": today,
            "kpis": kpis,
            "balances": bal,
            "current_course": StaffPDService._course_card(current, today)
            if current
            else None,
            "timeline": StaffPDService._timeline(current) if current else None,
            "next_actions": StaffPDService._next_actions(rows),
            "reminders": StaffPDService._upcoming_reminders(rows, today),
            "hr_messages": StaffPDService._recent_messages(user),
            "courses": [StaffPDService._course_row(r) for r in rows],
            "in_progress_count": sum(
                1
                for r in rows
                if r.status not in CLOSED_STATUSES and r.status != PDStatus.DRAFT
            ),
            "completed_count": completed,
            "cancelled_count": sum(
                1
                for r in rows
                if r.status
                in (PDStatus.REJECTED, PDStatus.CANCELLED, PDStatus.WITHDRAWN)
            ),
            "staff_info": staff_display_info(user),
            "last_refreshed": timezone.now(),
        }

    # ── Upcoming Reminders panel (§19 — derived live, never stored) ─────────
    @staticmethod
    def _upcoming_reminders(
        rows: list[ProfessionalDevelopmentRequest], today: date
    ) -> list[dict]:
        items = []

        def _add(r, tone, label, ref_date, days_left):
            items.append(
                {
                    "id": r.id,
                    "course_name": r.course_name,
                    "tone": tone,
                    "label": label,
                    "date": ref_date,
                    "days_left": days_left,
                }
            )

        for r in rows:
            if r.status in (PDStatus.RETURNED_BY_SUPERVISOR, PDStatus.RETURNED_BY_HR):
                since = (today - r.updated_at.date()).days
                _add(
                    r,
                    "warning",
                    f"“{r.course_name}” was returned — fix and resubmit",
                    r.updated_at.date(),
                    -since,
                )
            elif r.status == PDStatus.ENROLLMENT_CONFIRMED and r.start_date:
                days = (r.start_date - today).days
                if 0 <= days <= 7:
                    _add(
                        r,
                        "warning" if days <= 1 else "info",
                        f"“{r.course_name}” starts in {days} day{'s' if days != 1 else ''}",
                        r.start_date,
                        days,
                    )
            elif r.status == PDStatus.IN_PROGRESS and r.end_date:
                days = (r.end_date - today).days
                if 0 <= days <= 14:
                    _add(
                        r,
                        "neutral",
                        f"“{r.course_name}” ends in {days} day{'s' if days != 1 else ''}",
                        r.end_date,
                        days,
                    )
            elif r.status == PDStatus.ENDED:
                overdue = (today - r.end_date).days
                _add(
                    r,
                    "warning" if overdue < 14 else "danger",
                    f"Mark “{r.course_name}” complete — {overdue} day{'s' if overdue != 1 else ''} overdue",
                    r.end_date,
                    -overdue,
                )
            elif r.status == PDStatus.MARKED_COMPLETE:
                since_date = (
                    r.marked_complete_at.date() if r.marked_complete_at else r.end_date
                )
                overdue = (today - since_date).days
                if overdue >= 3:
                    _add(
                        r,
                        "warning" if overdue < 14 else "danger",
                        f"Upload certificate for “{r.course_name}” — {overdue} days since completion",
                        since_date,
                        -overdue,
                    )
            elif r.status == PDStatus.CERTIFICATE_UPLOADED:
                overdue = (today - r.updated_at.date()).days
                if overdue >= 3:
                    _add(
                        r,
                        "warning" if overdue < 14 else "danger",
                        f"Confirm BambooHR upload for “{r.course_name}” — {overdue} days pending",
                        r.updated_at.date(),
                        -overdue,
                    )
            elif (
                r.status == PDStatus.BAMBOOHR_CONFIRMED
                and r.funding_type in FUNDED_TYPES
            ):
                overdue = (today - r.updated_at.date()).days
                if overdue >= 3:
                    _add(
                        r,
                        "warning" if overdue < 14 else "danger",
                        f"Submit accountability for “{r.course_name}” — {overdue} days pending",
                        r.updated_at.date(),
                        -overdue,
                    )
        items.sort(key=lambda x: x["days_left"])
        return items[:6]

    # ── Messages from HR panel (real thread data, empty until HR replies) ───
    @staticmethod
    def _recent_messages(user, limit: int = 6) -> list[dict]:
        from apps.accounts.models import User
        from apps.messaging.models import Message

        msgs = list(
            Message.objects.filter(
                recipient_id=user.id, category="professional_development"
            ).order_by("-created_at")[:limit]
        )
        sender_ids = {
            m.sender_id for m in msgs if m.sender_id and m.sender_id != "system"
        }
        names = dict(User.objects.filter(id__in=sender_ids).values_list("id", "name"))
        return [
            {
                "id": m.id,
                "sender_name": names.get(m.sender_id, "Edify System"),
                "body": m.body,
                "created_at": m.created_at,
                "unread": m.status == "unread",
                "context_id": m.context_id,
            }
            for m in msgs
        ]

    @staticmethod
    def _course_card(r: ProfessionalDevelopmentRequest, today: date) -> dict:
        total_days = max(1, (r.end_date - r.start_date).days)
        elapsed = max(0, min(total_days, (today - r.start_date).days))
        pct = (
            round(elapsed / total_days * 100)
            if r.status
            in (
                PDStatus.IN_PROGRESS,
                PDStatus.ENDED,
                PDStatus.MARKED_COMPLETE,
                PDStatus.CERTIFICATE_UPLOADED,
                PDStatus.BAMBOOHR_CONFIRMED,
                PDStatus.ACCOUNTABILITY_SUBMITTED,
                PDStatus.AWAITING_HR_SIGNOFF,
                PDStatus.COMPLETED_CLOSED,
            )
            else 0
        )
        pct = min(100, pct)
        label, action = NEXT_ACTION_BY_STATUS.get(r.status, ("View", None))
        return {
            "id": r.id,
            "course_name": r.course_name,
            "institution": r.institution,
            "course_type": r.get_course_type_display(),
            "start_date": r.start_date,
            "end_date": r.end_date,
            "duration_days": total_days,
            "category": r.course_category,
            "status": r.get_status_display(),
            "status_key": r.status,
            "pct": pct,
            "next_action_label": label,
            "next_action": action,
        }

    @staticmethod
    def _timeline(r: ProfessionalDevelopmentRequest) -> dict:
        idx = _STEP_INDEX.get(r.status, -1)
        steps = []
        dates = {
            0: r.submitted_at,
            1: r.supervisor_reviewed_at,
            2: r.hr_reviewed_at,
            4: r.enrollment_confirmed_at,
            6: r.certificates.filter(status="uploaded")
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first(),
            7: r.bamboohr_uploaded_at,
            8: r.accountability_submitted_at,
            9: r.signed_off_at,
            10: r.signed_off_at,
        }
        for i, (_key, label) in enumerate(TIMELINE_STEPS):
            if (
                r.status
                in (
                    PDStatus.RETURNED_BY_SUPERVISOR,
                    PDStatus.RETURNED_BY_HR,
                    PDStatus.REJECTED,
                    PDStatus.CANCELLED,
                )
                and i >= idx
            ):
                state = "blocked"
            elif i < idx or (i == idx and r.status == PDStatus.COMPLETED_CLOSED):
                state = "done"
            elif i == idx:
                state = "active"
            else:
                state = "pending"
            steps.append({"label": label, "state": state, "date": dates.get(i)})
        return {"steps": steps, "current_index": idx}

    @staticmethod
    def _next_actions(rows: list[ProfessionalDevelopmentRequest]) -> list[dict]:
        """§6 — the four action tiles on the reference page: certificate,
        BambooHR, accountability, NetSuite ID — one row per outstanding item."""
        actions = []
        for r in rows:
            if r.status in (PDStatus.RETURNED_BY_SUPERVISOR, PDStatus.RETURNED_BY_HR):
                actions.append(
                    {
                        "key": f"returned-{r.id}",
                        "request_id": r.id,
                        "icon": "warning",
                        "title": "Fix Returned Request",
                        "description": f"{r.course_name} was returned — review the note and resubmit.",
                        "action": "draft",
                        "button": "Review & Fix",
                    }
                )
            if r.status == PDStatus.ENDED or r.status == PDStatus.MARKED_COMPLETE:
                if r.status == PDStatus.MARKED_COMPLETE:
                    actions.append(
                        {
                            "key": f"cert-{r.id}",
                            "request_id": r.id,
                            "icon": "certificate",
                            "title": "Upload Certificate",
                            "description": f"Upload your completion certificate for {r.course_name}.",
                            "action": "upload_certificate",
                            "button": "Upload Now",
                        }
                    )
            if r.status == PDStatus.CERTIFICATE_UPLOADED:
                actions.append(
                    {
                        "key": f"bamboo-{r.id}",
                        "request_id": r.id,
                        "icon": "bamboo",
                        "title": "BambooHR Upload",
                        "description": f"Upload certificate to BambooHR and confirm here for {r.course_name}.",
                        "action": "bamboohr",
                        "button": "Confirm Upload",
                    }
                )
            if (
                r.status == PDStatus.BAMBOOHR_CONFIRMED
                and r.funding_type in FUNDED_TYPES
            ):
                actions.append(
                    {
                        "key": f"acct-{r.id}",
                        "request_id": r.id,
                        "icon": "accountability",
                        "title": "Submit Accountability",
                        "description": f"Submit receipts and accountability for {r.course_name}.",
                        "action": "accountability",
                        "button": "Submit Now",
                    }
                )
            elif r.status == PDStatus.BAMBOOHR_CONFIRMED:
                actions.append(
                    {
                        "key": f"signoff-{r.id}",
                        "request_id": r.id,
                        "icon": "signoff",
                        "title": "Awaiting HR Sign-Off",
                        "description": f"{r.course_name} is ready for HR sign-off.",
                        "action": None,
                        "button": "View",
                    }
                )
            if (
                r.status == PDStatus.ACCOUNTABILITY_SUBMITTED
                and not r.accountability_netsuite_id
            ):
                actions.append(
                    {
                        "key": f"netsuite-{r.id}",
                        "request_id": r.id,
                        "icon": "expense",
                        "title": "Enter Expense ID",
                        "description": f"Enter NetSuite Expense ID after accountability for {r.course_name}.",
                        "action": "accountability",
                        "button": "Enter ID",
                    }
                )
        return actions[:4]

    @staticmethod
    def _course_row(r: ProfessionalDevelopmentRequest) -> dict:
        label, action = NEXT_ACTION_BY_STATUS.get(r.status, ("View", None))
        return {
            "id": r.id,
            "course_name": r.course_name,
            "institution": r.institution,
            "course_type": r.get_course_type_display(),
            "start_date": r.start_date,
            "end_date": r.end_date,
            "status": r.get_status_display(),
            "status_key": r.status,
            "funding_used": f"{r.currency} {r.requested_amount_cents/100:,.0f}"
            if r.requested_amount_cents
            else (
                "Self-Funded" if r.funding_type == "self_funded" else f"{r.currency} 0"
            ),
            "next_action_label": label,
            "next_action": action,
            "bucket": (
                "completed"
                if r.status == PDStatus.COMPLETED_CLOSED
                else "cancelled"
                if r.status
                in (PDStatus.REJECTED, PDStatus.CANCELLED, PDStatus.WITHDRAWN)
                else "in_progress"
            ),
        }

    # ── Workload/calendar conflict check (§14) ──────────────────────────────
    @staticmethod
    def check_conflict(user, start_date: date, end_date: date) -> dict:
        from apps.accounts.models import CalendarBlock, Leave
        from apps.activities.models import Activity

        sp = _staff(user)
        ids = [sp.id, user.id] if sp else [user.id]
        activities = (
            Activity.objects.filter(
                responsible_staff_id__in=ids,
                deleted_at__isnull=True,
                planned_date__gte=start_date,
                planned_date__lt=end_date,
            )
            .exclude(status__in=["cancelled", "rejected", "not_planned"])
            .count()
        )

        leave_overlap = (
            Leave.objects.filter(
                staff_id=sp.id,
                status="approved",
                start_date__lt=end_date.isoformat(),
                end_date__gte=start_date.isoformat(),
            ).count()
            if sp
            else 0
        )

        blocks = CalendarBlock.objects.filter(
            is_active=True,
            start_date__lt=end_date,
            end_date__gte=start_date,
        ).count()

        if activities >= 8 or leave_overlap:
            status, detail_bits = "major_conflict", []
            if leave_overlap:
                detail_bits.append(
                    f"{leave_overlap} approved leave period(s) overlap this course"
                )
            if activities >= 8:
                detail_bits.append(
                    f"{activities} planned activities fall within the course dates"
                )
        elif activities >= 3:
            status, detail_bits = (
                "supervisor_review_required",
                [f"{activities} planned activities fall within the course dates"],
            )
        elif activities >= 1 or blocks:
            status, detail_bits = (
                "minor_conflict",
                [
                    f"{activities} planned activit{'y' if activities == 1 else 'ies'}, {blocks} calendar block(s)"
                ],
            )
        else:
            status, detail_bits = "no_conflict", []
        return {
            "status": status,
            "detail": "; ".join(detail_bits) or "No scheduling conflicts detected.",
            "activities": activities,
            "leave_overlap": leave_overlap,
            "blocks": blocks,
        }

    @staticmethod
    def create_calendar_block(request_obj: "ProfessionalDevelopmentRequest") -> str:
        """§14 — approval creates a PD calendar block, never a school Activity
        or ActivityBudgetLine."""
        from apps.accounts.models import CalendarBlock

        # CalendarBlock has no single-owner field (it's designed for
        # org-wide holidays/blackouts) — `created_by` + the description
        # carry the personal-ownership signal instead of misusing
        # `applies_to_roles` (a role list) to hold one staff id.
        block = CalendarBlock.objects.create(
            title=f"PD: {request_obj.course_name}",
            description=f"{request_obj.staff_name} — {request_obj.institution}",
            block_type="CUSTOM_BLOCK",
            start_date=request_obj.start_date,
            end_date=request_obj.end_date,
            country=request_obj.country,
            applies_to_all_roles=False,
            created_by=request_obj.staff_id,
        )
        return block.id

    # ── Action-required queue (§27 To-Dos + sidebar attention badge) ────────
    @staticmethod
    def action_required(user) -> dict:
        """Every PD item needing THIS principal's action right now — their own
        outstanding steps plus anything they are the authorized reviewer for.
        The single source for both the global To-Do queue and the sidebar
        badge — reuses each service's own `can_review`/`can_signoff_review`
        check rather than re-deriving routing rules here."""
        from apps.professional_development.approval_service import (
            PDApprovalRoutingService,
        )
        from apps.professional_development.fund_service import PDFundRequestService
        from apps.professional_development.completion_service import (
            PDCourseTrackingService,
        )

        sp_id = getattr(user, "staff_profile_id", None)
        own = []
        if sp_id:
            own_action_statuses = (
                PDStatus.RETURNED_BY_SUPERVISOR,
                PDStatus.RETURNED_BY_HR,
                PDStatus.DISBURSED,
                PDStatus.APPROVED_UNFUNDED,
                PDStatus.ENROLLMENT_PENDING,
                PDStatus.ENDED,
                PDStatus.MARKED_COMPLETE,
                PDStatus.CERTIFICATE_UPLOADED,
            )
            own = list(
                ProfessionalDevelopmentRequest.objects.filter(
                    staff_id=sp_id, status__in=own_action_statuses
                )
            )
            own += list(
                ProfessionalDevelopmentRequest.objects.filter(
                    staff_id=sp_id,
                    status=PDStatus.BAMBOOHR_CONFIRMED,
                    funding_type__in=FUNDED_TYPES,
                )
            )

        candidates = ProfessionalDevelopmentRequest.objects.exclude(
            staff_id=sp_id or ""
        ).filter(
            status__in=(
                PDStatus.SUBMITTED_TO_SUPERVISOR,
                PDStatus.SUBMITTED_TO_HR,
                PDStatus.PENDING_EXCEPTION,
                PDStatus.APPROVED_PENDING_FUNDING,
                PDStatus.ACCOUNTABILITY_SUBMITTED,
                PDStatus.AWAITING_HR_SIGNOFF,
            )
        )
        reviewing = [
            r
            for r in candidates
            if PDApprovalRoutingService.can_review(r, user)
            or PDFundRequestService.can_review(r, user)
            or PDCourseTrackingService.can_signoff_review(r, user)
        ]
        return {"own": own, "reviewing": reviewing, "count": len(own) + len(reviewing)}
