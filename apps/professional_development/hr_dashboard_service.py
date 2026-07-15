"""HRPDDashboardService — the HR-facing Professional Development command
center (§16 of the PD mandate).

Read-mostly aggregation over ProfessionalDevelopmentRequest +
ProfessionalDevelopmentAllocation — everything here is derived live, exactly
like the employee-facing StaffPDService it sits beside. The one write path
("Adjust Allocation") edits a PDRoleAllocation template and, on request,
bulk-applies it to individual staff `ProfessionalDevelopmentAllocation` rows;
it never touches balances directly.

Scope is resolved from the principal's role — HR/Admin see every country
(the Country filter narrows further); CountryDirector is locked to their own
country; Program Lead is locked to their supervised staff (their team). This
matches the page's existing PAGE_PERMISSIONS grant (HR, PL, CD, Admin) — no
role sees PD data outside these bounds.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone

from apps.core.fy import fy_options, get_operational_fy

from apps.professional_development.models import (
    COMMITTED_STATUSES,
    FUNDED_TYPES,
    PDStatus,
    PDRoleAllocation,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentRequest,
)

PD_ELIGIBLE_ROLES = [
    ("CCEO", "CCEO"),
    ("Program Lead", "Program Lead"),
    ("CountryDirector", "Country Director"),
    ("RegionalVicePresident", "Regional VP"),
    ("ImpactAssessment", "IA Advisor"),
    ("Accountant", "Accountant"),
    ("HumanResources", "HR Officer"),
    ("ProjectCoordinator", "Project Coordinator"),
    ("Admin", "Admin"),
]
ROLE_LABELS = dict(PD_ELIGIBLE_ROLES)

NOT_STARTED_STATUSES = (
    PDStatus.SUBMITTED_TO_SUPERVISOR,
    PDStatus.SUBMITTED_TO_HR,
    PDStatus.PENDING_EXCEPTION,
    PDStatus.APPROVED_PENDING_FUNDING,
    PDStatus.APPROVED_UNFUNDED,
    PDStatus.DISBURSED,
    PDStatus.ENROLLMENT_PENDING,
)
IN_PROGRESS_STATUSES = (PDStatus.ENROLLMENT_CONFIRMED, PDStatus.IN_PROGRESS)
PENDING_CERT_STATUSES = (PDStatus.ENDED, PDStatus.MARKED_COMPLETE)
EMPLOYEE_DONE_STATUSES = (
    PDStatus.CERTIFICATE_UPLOADED,
    PDStatus.BAMBOOHR_CONFIRMED,
    PDStatus.ACCOUNTABILITY_SUBMITTED,
    PDStatus.ACCOUNTABILITY_CLEARED,
    PDStatus.AWAITING_HR_SIGNOFF,
)
SIGNED_OFF_STATUSES = (PDStatus.COMPLETED_CLOSED,)
INACTIVE_STATUSES = (
    PDStatus.RETURNED_BY_SUPERVISOR,
    PDStatus.RETURNED_BY_HR,
    PDStatus.REJECTED,
    PDStatus.CANCELLED,
    PDStatus.DEFERRED,
    PDStatus.WITHDRAWN,
)
PENDING_ACCOUNTABILITY_STATUSES = (
    PDStatus.BAMBOOHR_CONFIRMED,
    PDStatus.ACCOUNTABILITY_SUBMITTED,
)

STATUS_BUCKET_OPTIONS = [
    ("not_started", "Not Started"),
    ("in_progress", "In Progress"),
    ("pending_certificate", "Pending Certificate"),
    ("completed", "Completed"),
    ("signed_off", "Signed Off"),
    ("inactive", "Inactive / Returned"),
]
REMINDER_OPTIONS = [("due", "Due Soon"), ("overdue", "Overdue")]


def _bucket(status: str) -> str:
    if status in NOT_STARTED_STATUSES:
        return "not_started"
    if status in IN_PROGRESS_STATUSES:
        return "in_progress"
    if status in PENDING_CERT_STATUSES:
        return "pending_certificate"
    if status in EMPLOYEE_DONE_STATUSES:
        return "completed"
    if status in SIGNED_OFF_STATUSES:
        return "signed_off"
    return "inactive"


def _scoped_staff_ids(principal):
    """Resolve which StaffProfile ids this principal may see PD data for.
    Returns (queryset_of_ids_or_None, locked_country_or_None). None means
    "no staff-id restriction" (HR/Admin); locked_country pins the Country
    filter for CountryDirector."""
    from apps.accounts.models import StaffProfile

    role = getattr(principal, "active_role", "")
    if role in ("HumanResources", "Admin"):
        return None, None
    if role == "CountryDirector":
        sp = StaffProfile.objects.filter(user=principal).first()
        country = sp.country if sp else None
        ids = (
            list(
                StaffProfile.objects.filter(country=country).values_list(
                    "id", flat=True
                )
            )
            if country
            else []
        )
        return ids, country
    if role == "Program Lead":
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(principal)
        return list(scope.supervised_staff_ids), None
    # Any other role reaching this view (shouldn't happen — permission-gated) sees nothing.
    return [], None


class HRPDDashboardService:
    @staticmethod
    def get_dashboard(principal, params: dict) -> dict:
        fy = (params.get("fy") or "").strip() or get_operational_fy()
        country_filter = (params.get("country") or "").strip()
        role_filter = (params.get("role") or "").strip()
        status_filter = (params.get("status") or "").strip()
        reminder_filter = (params.get("reminder") or "").strip()
        search = (params.get("q") or "").strip()
        page = max(1, int(params.get("page") or 1))

        from apps.accounts.models import StaffProfile

        scoped_ids, locked_country = _scoped_staff_ids(principal)
        country = locked_country or country_filter
        country_scope_qs = StaffProfile.objects.all()
        if scoped_ids is not None:
            country_scope_qs = country_scope_qs.filter(id__in=scoped_ids)
        country_options = sorted(
            c
            for c in country_scope_qs.values_list("country", flat=True).distinct()
            if c
        )

        alloc_qs = ProfessionalDevelopmentAllocation.objects.filter(fy=fy)
        req_qs = ProfessionalDevelopmentRequest.objects.filter(fy=fy).exclude(
            status=PDStatus.DRAFT
        )
        if scoped_ids is not None:
            alloc_qs = alloc_qs.filter(staff_id__in=scoped_ids)
            req_qs = req_qs.filter(staff_id__in=scoped_ids)
        if country:
            alloc_qs = alloc_qs.filter(country=country)
            req_qs = req_qs.filter(country=country)
        if role_filter:
            from apps.accounts.models import StaffProfile

            role_staff_ids = list(
                StaffProfile.objects.filter(user__active_role=role_filter).values_list(
                    "id", flat=True
                )
            )
            alloc_qs = alloc_qs.filter(staff_id__in=role_staff_ids)
            req_qs = req_qs.filter(staff_id__in=role_staff_ids)
        if search:
            req_qs = req_qs.filter(
                Q(staff_name__icontains=search) | Q(course_name__icontains=search)
            )

        all_rows = list(req_qs.order_by("-updated_at"))
        today = date.today()

        # ── KPI strip (8) ────────────────────────────────────────────────────
        total_allocation = sum(a.annual_allocation for a in alloc_qs)
        committed = sum(
            r.requested_amount_cents for r in all_rows if r.status in COMMITTED_STATUSES
        )
        accounted = sum(r.accounted_amount or 0 for r in all_rows)
        staff_enrolled = len({r.staff_id for r in all_rows})
        courses_in_progress = sum(
            1 for r in all_rows if r.status in IN_PROGRESS_STATUSES
        )
        pending_certificate = sum(
            1 for r in all_rows if r.status in PENDING_CERT_STATUSES
        )
        pending_accountability = sum(
            1
            for r in all_rows
            if r.status in PENDING_ACCOUNTABILITY_STATUSES
            and r.funding_type in FUNDED_TYPES
        )
        signoff_pending = sum(
            1 for r in all_rows if r.status == PDStatus.AWAITING_HR_SIGNOFF
        )
        currency = alloc_qs.first().currency if alloc_qs.exists() else "UGX"

        kpis = [
            {
                "key": "allocation",
                "label": "Total Annual PD Allocation",
                "icon": "currency",
                "variant": "primary",
                "value": f"{currency} {total_allocation/100:,.0f}",
                "helper": f"FY {fy}",
            },
            {
                "key": "committed",
                "label": "Funds Committed",
                "icon": "chart",
                "variant": "default",
                "value": f"{currency} {committed/100:,.0f}",
                "helper": f"{round(committed/total_allocation*100) if total_allocation else 0}% of allocation",
            },
            {
                "key": "accounted",
                "label": "Funds Accounted For",
                "icon": "accountability",
                "variant": "default",
                "value": f"{currency} {accounted/100:,.0f}",
                "helper": f"{round(accounted/total_allocation*100) if total_allocation else 0}% of allocation",
            },
            {
                "key": "enrolled",
                "label": "Staff Enrolled",
                "icon": "users",
                "variant": "primary",
                "value": str(staff_enrolled),
                "helper": f"FY {fy}",
            },
            {
                "key": "in_progress",
                "label": "Courses In Progress",
                "icon": "graduation",
                "variant": "primary",
                "value": str(courses_in_progress),
                "helper": "Active now",
            },
            {
                "key": "pending_cert",
                "label": "Pending Certificate Uploads",
                "icon": "certificate",
                "variant": "warning" if pending_certificate else "success",
                "value": str(pending_certificate),
                "helper": "Course ended, no certificate yet",
            },
            {
                "key": "pending_acct",
                "label": "Pending Accountability",
                "icon": "expense",
                "variant": "warning" if pending_accountability else "success",
                "value": str(pending_accountability),
                "helper": "Funded, not yet cleared",
            },
            {
                "key": "signoff",
                "label": "HR Sign-Off Pending",
                "icon": "signoff",
                "variant": "warning" if signoff_pending else "success",
                "value": str(signoff_pending),
                "helper": "Ready for review",
            },
        ]

        # ── Reminder-status derived tag per row (for filter + display) ──────
        def _reminder_tag(r):
            if r.status in PENDING_CERT_STATUSES:
                overdue = (today - r.end_date).days
                if overdue >= 7:
                    return "overdue"
                return "due"
            if (
                r.status == PDStatus.ENROLLMENT_CONFIRMED
                and 0 <= (r.start_date - today).days <= 7
            ):
                return "due"
            if (
                r.status in PENDING_ACCOUNTABILITY_STATUSES
                and r.funding_type in FUNDED_TYPES
            ):
                overdue = (today - r.updated_at.date()).days
                return "overdue" if overdue >= 14 else "due"
            return "none"

        tracker_rows = []
        for r in all_rows:
            bucket = _bucket(r.status)
            tag = _reminder_tag(r)
            if status_filter and bucket != status_filter:
                continue
            if reminder_filter and tag != reminder_filter:
                continue
            tracker_rows.append(
                {
                    "id": r.id,
                    "staff_name": r.staff_name,
                    "role": r.position or "—",
                    "supervisor": r.supervisor_name or "—",
                    "course_name": r.course_name,
                    "course_type": r.get_course_type_display(),
                    "start_date": r.start_date,
                    "end_date": r.end_date,
                    "allocation": f"{r.currency} {r.requested_amount_cents/100:,.0f}",
                    "fund_used": f"{r.currency} {(r.accounted_amount or 0)/100:,.0f}",
                    "remaining": f"{r.currency} {max(0, r.requested_amount_cents - (r.accounted_amount or 0))/100:,.0f}",
                    "status": r.get_status_display(),
                    "bucket": bucket,
                    "certificate_status": "Uploaded"
                    if r.status
                    not in NOT_STARTED_STATUSES
                    + IN_PROGRESS_STATUSES
                    + PENDING_CERT_STATUSES
                    else "Pending",
                    "accountability_status": (
                        "N/A"
                        if r.funding_type not in FUNDED_TYPES
                        else "Cleared"
                        if r.accountability_reviewed_at
                        else "Submitted"
                        if r.accountability_submitted_at
                        else "Pending"
                    ),
                    "signoff_status": "Signed Off"
                    if r.status == PDStatus.COMPLETED_CLOSED
                    else "Pending"
                    if r.status == PDStatus.AWAITING_HR_SIGNOFF
                    else "—",
                    "reminder_tag": tag,
                    "next_action": _next_action_label(r),
                }
            )

        total_entries = len(tracker_rows)
        per_page = 10
        pages = max(1, (total_entries + per_page - 1) // per_page)
        page = min(page, pages)
        page_rows = tracker_rows[(page - 1) * per_page : page * per_page]

        # ── HR Action Center (5 groups) ──────────────────────────────────────
        action_center = []
        for key, label, bucket_name in (
            ("not_started", "Not Yet Started", "not_started"),
            ("in_progress", "In Progress", "in_progress"),
            (
                "pending_certificate",
                "Pending Certificate Upload",
                "pending_certificate",
            ),
            ("pending_accountability", "Pending Funds Accountability", None),
            ("ready_signoff", "Ready for HR Sign-Off", "signed_off_pending"),
        ):
            if key == "pending_accountability":
                items = [
                    r
                    for r in all_rows
                    if r.status in PENDING_ACCOUNTABILITY_STATUSES
                    and r.funding_type in FUNDED_TYPES
                ]
            elif key == "ready_signoff":
                items = [
                    r for r in all_rows if r.status == PDStatus.AWAITING_HR_SIGNOFF
                ]
            else:
                items = [r for r in all_rows if _bucket(r.status) == bucket_name]
            sample = items[:3]
            action_center.append(
                {
                    "key": key,
                    "label": label,
                    "count": len(items),
                    "items": [
                        {
                            "id": r.id,
                            "staff_name": r.staff_name,
                            "course_name": r.course_name,
                            "due_label": _due_label(r, key, today),
                            "action": "sign_off"
                            if key == "ready_signoff"
                            else "send_reminder",
                            "action_label": "Sign Off"
                            if key == "ready_signoff"
                            else "Send Reminder",
                        }
                        for r in sample
                    ],
                }
            )

        # ── Role-based allocation settings ───────────────────────────────────
        role_settings = HRPDDashboardService._role_allocation_settings(
            fy, country, scoped_ids
        )

        # ── Compliance donuts ────────────────────────────────────────────────
        bucket_counts = {
            "not_started": 0,
            "in_progress": 0,
            "pending_certificate": 0,
            "completed": 0,
            "signed_off": 0,
            "inactive": 0,
        }
        for r in all_rows:
            bucket_counts[_bucket(r.status)] += 1
        status_distribution = [
            {"label": lbl, "count": bucket_counts[key]}
            for key, lbl in (
                ("not_started", "Not Started"),
                ("in_progress", "In Progress"),
                ("pending_certificate", "Pending Certificate"),
                ("completed", "Completed"),
                ("signed_off", "Signed Off"),
            )
            if bucket_counts[key] or True
        ]
        uncommitted = max(0, total_allocation - committed - accounted)
        fund_utilization = {
            "accounted": accounted,
            "committed_not_accounted": max(0, committed - accounted),
            "uncommitted": uncommitted,
            "total": total_allocation,
            "accounted_pct": round(accounted / total_allocation * 100)
            if total_allocation
            else 0,
        }

        # ── Completed / sign-off snapshot ────────────────────────────────────
        completed_this_fy = sum(
            1 for r in all_rows if r.status == PDStatus.COMPLETED_CLOSED
        )
        certs_verified = sum(
            1
            for r in all_rows
            if r.status == PDStatus.COMPLETED_CLOSED
            and r.certificates.filter(status="uploaded").exists()
        )
        bamboo_confirmed = sum(
            1
            for r in all_rows
            if r.status == PDStatus.COMPLETED_CLOSED and r.bamboohr_uploaded
        )
        eligible_for_signoff = sum(
            1
            for r in all_rows
            if r.status in EMPLOYEE_DONE_STATUSES + SIGNED_OFF_STATUSES
        )
        signoff_rate = (
            round(completed_this_fy / eligible_for_signoff * 100)
            if eligible_for_signoff
            else 0
        )

        # ── Upcoming / overdue ───────────────────────────────────────────────
        upcoming_30d = [
            r
            for r in all_rows
            if r.status in NOT_STARTED_STATUSES + IN_PROGRESS_STATUSES
            and r.start_date
            and 0 <= (r.start_date - today).days <= 30
        ]
        overdue_no_cert = [
            r
            for r in all_rows
            if r.status in PENDING_CERT_STATUSES and (today - r.end_date).days > 0
        ]
        overdue_accountability = [
            r
            for r in all_rows
            if r.status in PENDING_ACCOUNTABILITY_STATUSES
            and r.funding_type in FUNDED_TYPES
            and (today - r.updated_at.date()).days > 7
        ]

        return {
            "fy": fy,
            "fy_options": fy_options(),
            "country": country,
            "locked_country": locked_country,
            "country_options": country_options,
            "role_filter": role_filter,
            "status_filter": status_filter,
            "reminder_filter": reminder_filter,
            "search": search,
            "eligible_roles": PD_ELIGIBLE_ROLES,
            "status_options": STATUS_BUCKET_OPTIONS,
            "reminder_options": REMINDER_OPTIONS,
            "kpis": kpis,
            "currency": currency,
            "tracker_rows": page_rows,
            "tracker_total": total_entries,
            "tracker_page": page,
            "tracker_pages": pages,
            "action_center": action_center,
            "role_settings": role_settings,
            "status_distribution": status_distribution,
            "status_distribution_total": len(all_rows),
            "fund_utilization": fund_utilization,
            "completed_this_fy": completed_this_fy,
            "certs_verified": certs_verified,
            "bamboo_confirmed": bamboo_confirmed,
            "signoff_rate": signoff_rate,
            "upcoming_30d": upcoming_30d[:8],
            "upcoming_30d_count": len(upcoming_30d),
            "overdue_no_cert": overdue_no_cert[:8],
            "overdue_no_cert_count": len(overdue_no_cert),
            "overdue_accountability": overdue_accountability[:8],
            "overdue_accountability_count": len(overdue_accountability),
            "last_refreshed": timezone.now(),
        }

    @staticmethod
    def _role_allocation_settings(fy: str, country: str, scoped_ids) -> dict:
        from apps.accounts.models import StaffProfile

        country = country or "Uganda"
        defaults = {
            pra.role: pra
            for pra in PDRoleAllocation.objects.filter(fy=fy, country=country)
        }
        rows = []
        total_staff = 0
        total_allocated = 0
        for role, label in PD_ELIGIBLE_ROLES:
            staff_qs = StaffProfile.objects.filter(
                user__active_role=role, country=country
            )
            if scoped_ids is not None:
                staff_qs = staff_qs.filter(id__in=scoped_ids)
            staff_count = staff_qs.count()
            if staff_count == 0 and role not in defaults:
                continue
            default = defaults.get(role)
            per_staff = default.annual_allocation_cents if default else 0
            row_total = per_staff * staff_count
            currency = default.currency if default else "UGX"
            rows.append(
                {
                    "role": role,
                    "label": label,
                    "per_staff": f"{currency} {per_staff/100:,.0f}",
                    "staff_count": staff_count,
                    "total_allocated": f"{currency} {row_total/100:,.0f}",
                    "currency": currency,
                }
            )
            total_staff += staff_count
            total_allocated += row_total
        return {
            "rows": rows,
            "total_staff": total_staff,
            "total_allocated": f"{total_allocated/100:,.0f}",
        }

    @staticmethod
    def adjust_role_allocation(
        principal,
        *,
        role: str,
        fy: str,
        country: str,
        amount_major: float,
        currency: str = "UGX",
        apply_to_existing: bool = False,
    ) -> PDRoleAllocation:
        """HR sets (or updates) the default annual PD allocation for a role.
        Optionally bulk-applies it to every current staff member in that
        role/country's own ProfessionalDevelopmentAllocation row for this FY —
        an explicit, opt-in action, never automatic."""
        from apps.core.exceptions import BadRequest, Forbidden

        if getattr(principal, "active_role", "") not in ("HumanResources", "Admin"):
            raise Forbidden(
                "Only HR may adjust Professional Development role allocations."
            )
        if role not in dict(PD_ELIGIBLE_ROLES):
            raise BadRequest("Unknown role.")
        amount_cents = int(round(amount_major * 100))
        pra, _ = PDRoleAllocation.objects.update_or_create(
            role=role,
            fy=fy,
            country=country,
            defaults={
                "annual_allocation_cents": amount_cents,
                "currency": currency,
                "set_by": principal.user_id,
            },
        )
        if apply_to_existing:
            from apps.accounts.models import StaffProfile

            for sp in StaffProfile.objects.filter(
                user__active_role=role, country=country
            ):
                ProfessionalDevelopmentAllocation.objects.update_or_create(
                    staff_id=sp.id,
                    fy=fy,
                    defaults={
                        "country": country,
                        "currency": currency,
                        "annual_allocation": amount_cents,
                    },
                )
        return pra


def _next_action_label(r: ProfessionalDevelopmentRequest) -> str:
    from apps.professional_development.services import NEXT_ACTION_BY_STATUS

    label, _ = NEXT_ACTION_BY_STATUS.get(r.status, ("—", None))
    return label


def _due_label(r: ProfessionalDevelopmentRequest, key: str, today: date) -> str:
    if key == "not_started" and r.start_date:
        days = (r.start_date - today).days
        return (
            f"Start by {r.start_date:%d %b %Y}"
            if days >= 0
            else f"Was due {r.start_date:%d %b %Y}"
        )
    if key == "in_progress" and r.end_date:
        return f"Due {r.end_date:%d %b %Y}"
    if key in ("pending_certificate",) and r.end_date:
        return f"Ended {r.end_date:%d %b %Y}"
    if key == "ready_signoff" and r.marked_complete_at:
        return f"Completed on {r.marked_complete_at:%d %b %Y}"
    return "—"
