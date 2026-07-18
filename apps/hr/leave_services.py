from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    LeaveTypePolicy,
    LeaveBalance,
    TemporaryCoverageAssignment,
    PublicHoliday,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
    CalendarBlock,
)
from apps.core.rbac import EdifyRole
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.calendar_policy import (
    SchedulingPolicyService as PlanningAvailabilityService,  # noqa: F401 — re-exported for existing `from apps.hr.leave_services import PlanningAvailabilityService` call sites
    activity_owner_ids as _activity_owner_ids,
    scheduled_datetime_window as _scheduled_datetime_window,
)

logger = logging.getLogger("edify.hr.leave")


def check_staff_availability(staff_id: str, check_date) -> bool:
    """Check if the staff member is on approved leave on the given date (accepts user_id or staff_profile_id)."""
    if not check_date:
        return True

    # Resolve staff_profile_id from user_id if needed
    sp = StaffProfile.objects.filter(Q(id=staff_id) | Q(user_id=staff_id)).first()
    if not sp:
        return True

    if isinstance(check_date, datetime):
        d = check_date.date()
    elif isinstance(check_date, date):
        d = check_date
    elif isinstance(check_date, str):
        try:
            if "T" in check_date or " " in check_date:
                d = date.fromisoformat(check_date[:10])
            else:
                d = date.fromisoformat(check_date)
        except ValueError:
            return True
    else:
        return True

    d_str = d.isoformat()
    return not Leave.objects.filter(
        staff=sp, status="approved", start_date__lte=d_str, end_date__gte=d_str
    ).exists()


class WorkingDayCalculator:
    """Calculates leave days charged in working days (Mon-Fri) excluding weekends and public holidays."""

    @staticmethod
    def calculate_working_days(
        start_date_str: str,
        end_date_str: str,
        weekends_count: bool = False,
        public_holidays_count: bool = False,
    ) -> int:
        """Calculate working days between start_date and end_date (inclusive)."""
        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        except (ValueError, TypeError):
            raise BadRequest("Invalid date format. Expected YYYY-MM-DD.")

        if end_date < start_date:
            raise BadRequest("End date cannot be before start date.")

        working_days = 0
        current_date = start_date

        # Get list of public holidays in range if we need to skip them.
        # Must match PublicHolidayService.get_holidays_in_range (the same
        # union of PublicHoliday + CalendarBlock(PUBLIC_HOLIDAY) used by the
        # preview/conflict-detection surface) — otherwise a holiday added
        # only via /public-holidays (CalendarBlock) is shown as excluded in
        # the preview but silently charged against the balance here.
        holidays = set()
        if not public_holidays_count:
            holidays = set(
                PublicHolidayService.get_holidays_in_range(start_date, end_date)
            )

        while current_date <= end_date:
            is_weekend = current_date.weekday() >= 5  # 5=Saturday, 6=Sunday
            is_holiday = current_date in holidays

            if (weekends_count or not is_weekend) and (
                public_holidays_count or not is_holiday
            ):
                working_days += 1

            current_date += timedelta(days=1)

        return working_days

    @staticmethod
    def calculate_working_hours(working_days: int) -> int:
        """Each working day represents 8 working hours."""
        return working_days * 8


class LeaveBalanceService:
    """Tracks and recalculates leave balances for staff."""

    @staticmethod
    def initialize_balances_for_staff(staff: StaffProfile, year: int = 2026):
        """Pre-populate balances for a staff profile from policies."""
        policies = LeaveTypePolicy.objects.all()
        # Seed default policies if none exist
        if not policies.exists():
            LeaveBalanceService.seed_default_policies()
            policies = LeaveTypePolicy.objects.all()

        for policy in policies:
            LeaveBalance.objects.get_or_create(
                staff=staff,
                leave_type=policy.leave_type,
                year=year,
                defaults={
                    "entitlement": policy.annual_entitlement,
                    "remaining": policy.annual_entitlement,
                    "used": 0,
                    "pending": 0,
                    "approved": 0,
                },
            )

    @staticmethod
    def bulk_initialize_balances_for_staff(staff_ids: list[str], year: int = 2026):
        """Pre-populate balances for many staff profiles in a bounded number
        of queries instead of calling initialize_balances_for_staff() (which
        runs ~1-7 queries) once per staff member — used by list/dashboard
        views (e.g. the leave tracker) that render a whole team at once."""
        if not staff_ids:
            return

        policies = list(LeaveTypePolicy.objects.all())
        if not policies:
            LeaveBalanceService.seed_default_policies()
            policies = list(LeaveTypePolicy.objects.all())

        existing = set(
            LeaveBalance.objects.filter(staff_id__in=staff_ids, year=year).values_list(
                "staff_id", "leave_type"
            )
        )

        to_create = [
            LeaveBalance(
                staff_id=staff_id,
                leave_type=policy.leave_type,
                year=year,
                entitlement=policy.annual_entitlement,
                remaining=policy.annual_entitlement,
                used=0,
                pending=0,
                approved=0,
            )
            for staff_id in staff_ids
            for policy in policies
            if (staff_id, policy.leave_type) not in existing
        ]
        if to_create:
            LeaveBalance.objects.bulk_create(to_create, ignore_conflicts=True)

    @staticmethod
    def seed_default_policies():
        """Seed default leave type policies."""
        defaults = [
            ("personal_time_off", "Personal Time Off", 21, False, "Program Lead"),
            ("sick_leave", "Sick Leave", 14, True, "Program Lead"),
            ("maternity_leave", "Maternity Leave", 60, True, "CountryDirector"),
            ("paternity_leave", "Paternity Leave", 5, False, "Program Lead"),
            ("bereavement_leave", "Bereavement Leave", 7, False, "Program Lead"),
        ]
        for key, label, ent, req_attach, role in defaults:
            LeaveTypePolicy.objects.get_or_create(
                leave_type=key,
                defaults={
                    "label": label,
                    "annual_entitlement": ent,
                    "requires_attachment": req_attach,
                    "approver_role": role,
                    "weekends_count": False,
                    "public_holidays_count": False,
                },
            )

    @staticmethod
    def recalculate_balances(staff: StaffProfile, year: int = 2026):
        """Sum days charged and update LeaveBalance table."""
        balances = LeaveBalance.objects.filter(staff=staff, year=year)
        if not balances.exists():
            LeaveBalanceService.initialize_balances_for_staff(staff, year)
            balances = LeaveBalance.objects.filter(staff=staff, year=year)

        for bal in balances:
            # Query leaves for this year and type
            # The start_date contains the year (e.g. "2026-07-08")
            leaves = Leave.objects.filter(
                staff=staff, type=bal.leave_type, start_date__startswith=str(year)
            )

            approved_days = 0
            pending_days = 0

            for leave in leaves:
                days = (
                    leave.days_charged if leave.days_charged is not None else leave.days
                )
                if leave.status == "approved":
                    approved_days += days
                elif leave.status == "pending":
                    pending_days += days

            bal.approved = approved_days
            bal.used = approved_days
            bal.pending = pending_days
            bal.remaining = bal.entitlement - bal.used - bal.pending
            bal.save(update_fields=["approved", "used", "pending", "remaining"])


class CoverageAssignmentService:
    """Fetches eligible coverage candidates based on user active role and supervision."""

    @staticmethod
    def get_eligible_coverage_staff(
        staff: StaffProfile, start_date_str: str, end_date_str: str
    ) -> list[dict]:
        """Fetch candidates list who can cover this staff during their leave."""
        user = staff.user
        role = user.active_role

        # 1. Find all active staff profiles (excluding self)
        qs = (
            StaffProfile.objects.filter(
                deleted_at__isnull=True, onboarding_state="active"
            )
            .exclude(id=staff.id)
            .select_related("user")
        )

        # 2. Exclude anyone on approved leave during the same period
        # start_date__lte=end_date and end_date__gte=start_date
        overlapping_leaves = Leave.objects.filter(
            status="approved",
            start_date__lte=end_date_str,
            end_date__gte=start_date_str,
        ).values_list("staff_id", flat=True)

        qs = qs.exclude(id__in=overlapping_leaves)

        eligible_candidates = []

        # Get supervisor ID mapping if any
        supervisor_assignment = StaffSupervisorAssignment.objects.filter(
            supervisee=staff
        ).first()
        supervisor = supervisor_assignment.supervisor if supervisor_assignment else None

        if role == EdifyRole.CCEO.value:
            # CCEO coverage:
            # - Other CCEOs under the same PL
            # - The supervising PL
            cceo_candidates = qs.filter(user__active_role=EdifyRole.CCEO.value)
            if supervisor:
                # Filter CCEOs who share the same supervisor PL
                peer_ids = StaffSupervisorAssignment.objects.filter(
                    supervisor=supervisor
                ).values_list("supervisee_id", flat=True)
                cceo_candidates = cceo_candidates.filter(id__in=peer_ids)

                # Include the PL as an eligible candidate
                pl_candidate = qs.filter(id=supervisor.id)
                cceo_candidates = cceo_candidates | pl_candidate

            eligible_candidates = list(cceo_candidates)

        elif role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            # PL coverage:
            # - Another PL under the same CD
            # - The CD
            # - Senior CCEOs
            # For simplicity, fetch other PLs, CDs
            pl_candidates = qs.filter(
                user__active_role__in=[
                    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                    EdifyRole.COUNTRY_DIRECTOR.value,
                ]
            )
            # Senior CCEOs supervised by this PL (or CD-allowed CCEOs)
            senior_cceos = qs.filter(user__active_role=EdifyRole.CCEO.value)
            if supervisor:
                # CD is the supervisor of PL, let's check CD supervisees who are PLs
                peer_pl_ids = StaffSupervisorAssignment.objects.filter(
                    supervisor=supervisor
                ).values_list("supervisee_id", flat=True)
                pl_candidates = pl_candidates.filter(id__in=peer_pl_ids) | qs.filter(
                    id=supervisor.id
                )

            # Supervised CCEOs by this PL can act as senior CCEO cover
            supervised_cceos = StaffSupervisorAssignment.objects.filter(
                supervisor=staff
            ).values_list("supervisee_id", flat=True)
            senior_cceos = senior_cceos.filter(id__in=supervised_cceos)

            eligible_candidates = list(pl_candidates) + list(senior_cceos)

        elif role == EdifyRole.COUNTRY_DIRECTOR.value:
            # CD coverage:
            # - RVP
            # - Senior PLs
            cd_candidates = qs.filter(
                user__active_role__in=[
                    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
                    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                ]
            )
            eligible_candidates = list(cd_candidates)

        elif role == EdifyRole.IMPACT_ASSESSMENT.value:
            # IA coverage:
            # - Another IA
            # - CD
            ia_candidates = qs.filter(
                user__active_role__in=[
                    EdifyRole.IMPACT_ASSESSMENT.value,
                    EdifyRole.COUNTRY_DIRECTOR.value,
                ]
            )
            eligible_candidates = list(ia_candidates)

        elif role == EdifyRole.PROGRAM_ACCOUNTANT.value:
            # Accountant coverage:
            # - Another Accountant
            # - CD
            ac_candidates = qs.filter(
                user__active_role__in=[
                    EdifyRole.PROGRAM_ACCOUNTANT.value,
                    EdifyRole.COUNTRY_DIRECTOR.value,
                ]
            )
            eligible_candidates = list(ac_candidates)

        else:
            # Fallback for PC or partners
            eligible_candidates = list(qs[:10])

        # Serialize candidates
        serialized = []
        for sp in eligible_candidates:
            serialized.append(
                {
                    "id": sp.id,
                    "name": sp.user.name,
                    "role": sp.user.active_role,
                }
            )
        return serialized


class LeaveRequestService:
    """Manages the creation and checking of leave requests."""

    @staticmethod
    def request_leave(staff: StaffProfile, data: dict, attachment_file=None) -> Leave:
        leave_type = data.get("type", "personal_time_off")
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")
        covering_staff_id = data.get("covering_staff")
        reason = data.get("reason")
        emergency_contact = data.get("emergency_contact")
        handover_notes = data.get("handover_notes")
        urgent_activities = data.get("urgent_activities")

        # 1. Fetch policy
        policy, _ = LeaveTypePolicy.objects.get_or_create(
            leave_type=leave_type,
            defaults={"label": leave_type.replace("_", " ").title()},
        )

        # 1b. Enforce requires_attachment server-side. Previously only the
        # request-drawer JS enforced this, so the check could be bypassed
        # entirely by posting directly to this service/endpoint.
        if policy.requires_attachment and not attachment_file:
            raise BadRequest(
                f"{policy.label} requires a supporting attachment to be submitted."
            )

        # 2. Calculate working days
        days_charged = WorkingDayCalculator.calculate_working_days(
            start_date_str,
            end_date_str,
            weekends_count=policy.weekends_count,
            public_holidays_count=policy.public_holidays_count,
        )
        hours_covered = WorkingDayCalculator.calculate_working_hours(days_charged)

        # 3. Check balance for PTO
        year = int(start_date_str[:4])
        bal_qs = LeaveBalance.objects.filter(
            staff=staff, leave_type=leave_type, year=year
        )
        if not bal_qs.exists():
            LeaveBalanceService.initialize_balances_for_staff(staff, year)
            bal_qs = LeaveBalance.objects.filter(
                staff=staff, leave_type=leave_type, year=year
            )

        bal = bal_qs.first()
        if bal.remaining < days_charged:
            raise BadRequest(
                f"Insufficient balance for {policy.label}. Required: {days_charged} working days, Remaining: {bal.remaining} days."
            )

        # 4. Resolve covering staff
        covering_staff = None
        if covering_staff_id:
            covering_staff = StaffProfile.objects.filter(id=covering_staff_id).first()

        # 5. Calculate calendar days
        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
            calendar_days = (end_date - start_date).days + 1
        except Exception:
            calendar_days = days_charged

        # 6. Create request
        cov_status = "Awaiting Acceptance" if covering_staff else "Not Required"
        leave = Leave.objects.create(
            staff=staff,
            type=leave_type,
            start_date=start_date_str,
            end_date=end_date_str,
            days=calendar_days,
            days_charged=days_charged,
            hours_covered=hours_covered,
            status="pending",
            coverage_status=cov_status,
            reason=reason,
            covering_staff=covering_staff,
            coverage_notes=data.get("coverage_notes"),
            emergency_contact=emergency_contact,
            handover_notes=handover_notes,
            urgent_activities=urgent_activities,
            attachment=attachment_file,
        )

        # Recalculate balance to include pending days
        LeaveBalanceService.recalculate_balances(staff, year)

        return leave


class LeaveApprovalService:
    """Manages reviewing, approving, or rejecting leave requests."""

    @staticmethod
    def is_authorized_approver(reviewer_user: User, leave: Leave) -> bool:
        """Enforces the strict organizational hierarchy for leave approvals."""
        if not leave or not reviewer_user:
            return False

        # No employee may approve their own leave.
        if leave.staff.user_id == reviewer_user.id:
            return False

        def normalize_role(r):
            if not r:
                return ""
            r = r.replace(" ", "").replace("_", "").lower()
            if r in ["cceo"]:
                return "cceo"
            if r in ["programlead", "pl"]:
                return "pl"
            if r in ["countrydirector", "cd"]:
                return "cd"
            if r in ["regionalvicepresident", "rvp"]:
                return "rvp"
            if r in ["humanresources", "hr"]:
                return "hr"
            if r in ["impactassessment", "ia"]:
                return "ia"
            if r in ["accountant", "programaccountant", "acct"]:
                return "accountant"
            if r in ["projectcoordinator", "pc"]:
                return "pc"
            return r

        rev_role = normalize_role(reviewer_user.active_role)

        # Admin bypass
        if rev_role == "admin":
            return True

        reviewer_profile = getattr(reviewer_user, "staff_profile", None)
        if not reviewer_profile:
            return False

        from apps.accounts.models import StaffSupervisorAssignment

        # Check direct supervisor relationship in database
        direct_supervisor = StaffSupervisorAssignment.objects.filter(
            supervisee=leave.staff, supervisor=reviewer_profile
        ).exists()

        staff_role = normalize_role(leave.staff.user.active_role)

        if staff_role == "cceo":
            # CCEO leave -> PL approval
            return rev_role == "pl" and direct_supervisor

        elif staff_role == "pl":
            # PL leave -> CD approval
            if rev_role == "cd":
                return direct_supervisor or (
                    reviewer_profile.country == leave.staff.country
                )
            return False

        elif staff_role in ["pc", "ia", "accountant", "hr"]:
            # Check if this is country-level or regional-level HR/staff
            if direct_supervisor:
                return rev_role in ["cd", "rvp"]

            # Fallback by country scoping for CD
            if rev_role == "cd" and reviewer_profile.country == leave.staff.country:
                return True
            # RVP approves regional staff or CD
            if rev_role == "rvp":
                return True
            return False

        elif staff_role == "cd":
            # CD leave -> RVP approval
            if rev_role == "rvp":
                return True
            return False

        elif staff_role == "rvp":
            # RVP leave -> Exec/Admin approval (handled by Admin check above)
            return rev_role in ["admin", "executive"]

        # Default fallback
        return direct_supervisor

    @staticmethod
    def approve_request(leave_id: str, reviewer_user: User) -> Leave:
        leave = Leave.objects.filter(id=leave_id).first()
        if not leave:
            raise NotFoundError("Leave request not found.")

        # Hierarchy authorization check
        if not LeaveApprovalService.is_authorized_approver(reviewer_user, leave):
            raise BadRequest("You are not authorized to approve this leave request.")

        with transaction.atomic():
            leave.status = "approved"
            leave.reviewed_by_user_id = reviewer_user.id
            leave.reviewed_at = timezone.now()

            if leave.covering_staff:
                leave.coverage_status = "Approved"
            else:
                leave.coverage_status = "Not Required"

            leave.save(
                update_fields=[
                    "status",
                    "reviewed_by_user_id",
                    "reviewed_at",
                    "coverage_status",
                    "updated_at",
                ]
            )

            # Recalculate balances
            year = int(leave.start_date[:4])
            LeaveBalanceService.recalculate_balances(leave.staff, year)

            # If covering staff is present, create TemporaryCoverageAssignment
            if leave.covering_staff:
                # Access begins at start date 8:00 AM, ends at end date 5:00 PM
                start_dt = timezone.make_aware(
                    datetime.combine(
                        date.fromisoformat(leave.start_date),
                        datetime.min.time().replace(hour=8),
                    )
                )
                end_dt = timezone.make_aware(
                    datetime.combine(
                        date.fromisoformat(leave.end_date),
                        datetime.min.time().replace(hour=17),
                    )
                )

                # Revoke any pre-existing overlapping active coverages for this same leave request
                TemporaryCoverageAssignment.objects.filter(
                    leave_request=leave, status="active"
                ).update(
                    status="revoked",
                    revoked_at=timezone.now(),
                    revoked_by_user_id=reviewer_user.id,
                )

                coverage = TemporaryCoverageAssignment.objects.create(
                    leave_request=leave,
                    original_staff=leave.staff,
                    covering_staff=leave.covering_staff,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                    scope="operational_work",
                    status="active",
                    created_by_user_id=reviewer_user.id,
                )

                # A coverage grant is a real access-delegation event — it
                # widens can_view_record for the covering staff member and
                # causes their actions to be auto-attributed back to the
                # person they're covering for (see apps/audit/services.py).
                from apps.audit.services import log as audit_log

                audit_log(
                    action="hr.coverage_granted",
                    subject_kind="temporary_coverage_assignment",
                    subject_id=coverage.id,
                    actor_id=reviewer_user.id,
                    actor_role=getattr(reviewer_user, "active_role", None),
                    payload={
                        "originalStaffId": leave.staff_id,
                        "coveringStaffId": leave.covering_staff_id,
                        "leaveId": leave.id,
                    },
                )

                # Trigger notifications
                LeaveApprovalService.notify_coverage(leave)

        return leave

    @staticmethod
    def reject_request(
        leave_id: str, reviewer_user: User, reason: str | None = None
    ) -> Leave:
        leave = Leave.objects.filter(id=leave_id).first()
        if not leave:
            raise NotFoundError("Leave request not found.")

        # Hierarchy authorization check
        if not LeaveApprovalService.is_authorized_approver(reviewer_user, leave):
            raise BadRequest("You are not authorized to reject this leave request.")

        with transaction.atomic():
            leave.status = "rejected"
            leave.coverage_status = "Cancelled"
            leave.reviewed_by_user_id = reviewer_user.id
            leave.reviewed_at = timezone.now()
            if reason:
                leave.coverage_notes = (
                    f"{leave.coverage_notes or ''}\nRejected reason: {reason}".strip()
                )
            leave.save(
                update_fields=[
                    "status",
                    "coverage_status",
                    "reviewed_by_user_id",
                    "reviewed_at",
                    "coverage_notes",
                    "updated_at",
                ]
            )

            # Recalculate balances
            year = int(leave.start_date[:4])
            LeaveBalanceService.recalculate_balances(leave.staff, year)

        return leave

    @staticmethod
    def return_request(leave_id: str, reviewer_user: User, reason: str) -> Leave:
        leave = Leave.objects.filter(id=leave_id).first()
        if not leave:
            raise NotFoundError("Leave request not found.")

        # Hierarchy authorization check
        if not LeaveApprovalService.is_authorized_approver(reviewer_user, leave):
            raise BadRequest("You are not authorized to return this leave request.")

        with transaction.atomic():
            leave.status = "returned"
            leave.reviewed_by_user_id = reviewer_user.id
            leave.reviewed_at = timezone.now()
            leave.coverage_notes = (
                f"{leave.coverage_notes or ''}\nReturned reason: {reason}".strip()
            )
            leave.save(
                update_fields=[
                    "status",
                    "reviewed_by_user_id",
                    "reviewed_at",
                    "coverage_notes",
                    "updated_at",
                ]
            )

            # Recalculate balances
            year = int(leave.start_date[:4])
            LeaveBalanceService.recalculate_balances(leave.staff, year)

        return leave

    @staticmethod
    def accept_coverage(leave_id: str, covering_user: User) -> Leave:
        leave = Leave.objects.filter(id=leave_id).first()
        if not leave:
            raise NotFoundError("Leave request not found.")

        covering_profile = getattr(covering_user, "staff_profile", None)
        if (
            not leave.covering_staff
            or not covering_profile
            or leave.covering_staff.id != covering_profile.id
        ):
            raise BadRequest(
                "You are not the designated covering employee for this leave request."
            )

        leave.coverage_status = "Accepted"
        leave.save(update_fields=["coverage_status", "updated_at"])
        return leave

    @staticmethod
    def decline_coverage(leave_id: str, covering_user: User) -> Leave:
        leave = Leave.objects.filter(id=leave_id).first()
        if not leave:
            raise NotFoundError("Leave request not found.")

        covering_profile = getattr(covering_user, "staff_profile", None)
        if (
            not leave.covering_staff
            or not covering_profile
            or leave.covering_staff.id != covering_profile.id
        ):
            raise BadRequest(
                "You are not the designated covering employee for this leave request."
            )

        leave.coverage_status = "Declined"
        leave.save(update_fields=["coverage_status", "updated_at"])
        return leave

    @staticmethod
    def notify_coverage(leave: Leave):
        """Create in-app notifications/threads for the team when leave is approved."""
        try:
            # Create a team message thread introducing the coverage
            staff_name = leave.staff.user.name
            cover_name = (
                leave.covering_staff.user.name if leave.covering_staff else "None"
            )
            type_label = leave.type.replace("_", " ").title()

            msg_content = (
                f"📢 Leave & Coverage Notification:\n\n"
                f"{staff_name} will be on {type_label} from {leave.start_date} to {leave.end_date}.\n"
                f"{cover_name} will cover their schools, planning, and cluster follow-up during this period."
            )
            # Log notification to console / trigger in-app notification if apps are fully loaded
            logger.info("Notification: %s", msg_content)
        except Exception as e:
            logger.error("Failed to send leave notification: %s", e)


class LeaveImpactAnalysisService:
    """Previews affected activities, planning, and fund requests during a leave request period."""

    @staticmethod
    def analyze_impact(
        staff: StaffProfile,
        start_date_str: str,
        end_date_str: str,
        leave_type: str = "personal_time_off",
    ) -> dict:
        from apps.activities.models import Activity
        from apps.planning.models import MonthlyPlanActivity
        from apps.fund_requests.models import FundRequest, FundRequestStatus

        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)
        scheduled_start, scheduled_end = _scheduled_datetime_window(
            start_date, end_date
        )

        # 1. Activities scheduled during leave
        activities = Activity.objects.filter(
            responsible_staff_id__in=_activity_owner_ids(staff),
            scheduled_date__gte=scheduled_start,
            scheduled_date__lt=scheduled_end,
            deleted_at__isnull=True,
        ).select_related("school", "cluster")

        # 2. Planning items owned by the user
        planning_items = MonthlyPlanActivity.objects.filter(
            assignee_id=staff.id, scheduled_date__range=(start_date_str, end_date_str)
        )

        # 3. My Plan items due during leave (incomplete activities)
        my_plan_due = activities.filter(
            status__in=["planned", "scheduled", "partner_scheduled", "in_progress"]
        )

        # 4. Partner assignments waiting
        partner_assignments = Activity.objects.filter(
            monitored_by_staff_id=staff.id,
            scheduled_date__gte=scheduled_start,
            scheduled_date__lt=scheduled_end,
            delivery_type="partner",
            status="planned",
            deleted_at__isnull=True,
        )

        # 5. IA verification items waiting (if role is IA)
        ia_verification_count = 0
        if staff.user.active_role == EdifyRole.IMPACT_ASSESSMENT.value:
            ia_verification_count = Activity.objects.filter(
                ia_verification_status="pending",
                status="completed",
                deleted_at__isnull=True,
            ).count()

        # 6. Finance items waiting (if role is Accountant)
        finance_items_count = 0
        if staff.user.active_role == EdifyRole.PROGRAM_ACCOUNTANT.value:
            finance_items_count = FundRequest.objects.filter(
                status=FundRequestStatus.SENT_TO_ACCOUNTANT.value
            ).count()

        # 7. Fund requests affected (CCEO / PL)
        fund_requests = FundRequest.objects.filter(
            submitted_by_user_id=staff.user.id,
            status__in=[
                FundRequestStatus.SUBMITTED.value,
                FundRequestStatus.SUBMITTED_TO_PL.value,
            ],
        )

        # Count metrics
        activity_count = activities.count()
        planning_count = planning_items.count()
        due_count = my_plan_due.count()
        partner_count = partner_assignments.count()
        fund_count = fund_requests.count()

        # The approval surface must never invent a balance when one has not
        # been initialized. Expose the persisted ledger values (or ``None``)
        # so the UI can render an honest unavailable state.
        try:
            balance_year = date.fromisoformat(start_date_str).year
        except (TypeError, ValueError):
            balance_year = timezone.now().year
        balance = LeaveBalance.objects.filter(
            staff=staff,
            leave_type=leave_type,
            year=balance_year,
        ).first()

        total_impact = (
            activity_count
            + planning_count
            + partner_count
            + fund_count
            + ia_verification_count
            + finance_items_count
        )

        # Recommendations logic
        recommendation = "Approve with coverage"
        details = "All affected tasks will be temporarily scoped to the cover person."

        if due_count > 5:
            recommendation = "Ask user to reschedule activities first"
            details = f"User has {due_count} activities scheduled. Rescheduling is recommended to avoid field overload for the covering person."
        elif fund_count > 0:
            recommendation = "Transfer urgent activities to cover person"
            details = "User has pending fund requests. Recommend checking and transferring ownership or approving them prior to leave."

        return {
            "activity_count": activity_count,
            "planning_count": planning_count,
            "due_count": due_count,
            "partner_count": partner_count,
            "ia_verification_count": ia_verification_count,
            "finance_items_count": finance_items_count,
            "fund_count": fund_count,
            "balance_remaining": balance.remaining if balance else None,
            "balance_entitlement": balance.entitlement if balance else None,
            "total_impact": total_impact,
            "recommendation": recommendation,
            "details": details,
            "activities": [
                {
                    "id": a.id,
                    "type": a.activity_type.replace("_", " ").title(),
                    "date": a.scheduled_date.date().isoformat()
                    if a.scheduled_date
                    else "Not set",
                    "target": a.school.name
                    if a.school
                    else (a.cluster.name if a.cluster else "Unknown"),
                    "status": a.status,
                }
                for a in activities[:5]
            ],
        }


class CalendarBlockService:
    @staticmethod
    def create_block(data: dict, creator_id: str) -> CalendarBlock:
        from datetime import date

        s = (
            date.fromisoformat(data["start_date"])
            if isinstance(data["start_date"], str)
            else data["start_date"]
        )
        e = (
            date.fromisoformat(data["end_date"])
            if isinstance(data["end_date"], str)
            else data["end_date"]
        )
        return CalendarBlock.objects.create(
            title=data["title"],
            description=data.get("description"),
            block_type=data.get("block_type", "PUBLIC_HOLIDAY"),
            start_date=s,
            end_date=e,
            country=data.get("country", "Uganda"),
            region_id=data.get("region_id"),
            district_id=data.get("district_id"),
            applies_to_all_roles=data.get("applies_to_all_roles", True),
            applies_to_roles=data.get("applies_to_roles"),
            created_by=creator_id,
            is_active=True,
        )


class PublicHolidayService:
    @staticmethod
    def get_holidays_in_range(start_date, end_date, country="Uganda"):
        from datetime import date

        s = (
            start_date.date()
            if isinstance(start_date, datetime)
            else (
                date.fromisoformat(start_date)
                if isinstance(start_date, str)
                else start_date
            )
        )
        e = (
            end_date.date()
            if isinstance(end_date, datetime)
            else (
                date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            )
        )

        p_dates = set(
            PublicHoliday.objects.filter(date__range=(s, e)).values_list(
                "date", flat=True
            )
        )

        b_qs = CalendarBlock.objects.filter(
            block_type="PUBLIC_HOLIDAY",
            is_active=True,
            country=country,
            start_date__lte=e,
            end_date__gte=s,
        )
        for b in b_qs:
            curr = max(b.start_date, s)
            stop = min(b.end_date, e)
            while curr <= stop:
                p_dates.add(curr)
                curr += timedelta(days=1)

        return sorted(list(p_dates))


class BlackoutDateService:
    @staticmethod
    def get_blackout_dates_in_range(start_date, end_date, country="Uganda"):
        from datetime import date

        s = (
            start_date.date()
            if isinstance(start_date, datetime)
            else (
                date.fromisoformat(start_date)
                if isinstance(start_date, str)
                else start_date
            )
        )
        e = (
            end_date.date()
            if isinstance(end_date, datetime)
            else (
                date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            )
        )

        b_dates = set()
        b_qs = CalendarBlock.objects.filter(
            block_type="BLACKOUT_DATE",
            is_active=True,
            country=country,
            start_date__lte=e,
            end_date__gte=s,
        )
        for b in b_qs:
            curr = max(b.start_date, s)
            stop = min(b.end_date, e)
            while curr <= stop:
                b_dates.add(curr)
                curr += timedelta(days=1)

        return sorted(list(b_dates))


class LeaveConflictDetectionService:
    @staticmethod
    def detect(
        staff_profile: StaffProfile,
        start_date_str: str,
        end_date_str: str,
        cover_profile: StaffProfile | None = None,
    ) -> list[dict]:
        from apps.activities.models import Activity
        from datetime import date

        s = date.fromisoformat(start_date_str)
        e = date.fromisoformat(end_date_str)
        scheduled_start, scheduled_end = _scheduled_datetime_window(s, e)
        conflicts = []

        activities = Activity.objects.filter(
            responsible_staff_id__in=_activity_owner_ids(staff_profile),
            scheduled_date__gte=scheduled_start,
            scheduled_date__lt=scheduled_end,
        ).exclude(status__in=["cancelled", "completed"])

        for act in activities:
            conflicts.append(
                {
                    "conflict_type": "activity_during_leave",
                    "severity": "Critical",
                    "affected_activity": act,
                    "affected_user": staff_profile.user,
                    "date_range": act.scheduled_date.date().isoformat()
                    if act.scheduled_date
                    else "",
                    "recommended_action": "Reschedule or Reassign this activity.",
                    "can_auto_reschedule": True,
                    "can_reassign": True,
                }
            )

        holidays = PublicHolidayService.get_holidays_in_range(s, e)
        for h in holidays:
            conflicts.append(
                {
                    "conflict_type": "public_holiday",
                    "severity": "Warning",
                    "affected_activity": None,
                    "affected_user": staff_profile.user,
                    "date_range": h.isoformat(),
                    "recommended_action": "Leave request overlaps with a public holiday.",
                    "can_auto_reschedule": False,
                    "can_reassign": False,
                }
            )

        blackouts = BlackoutDateService.get_blackout_dates_in_range(s, e)
        for b in blackouts:
            conflicts.append(
                {
                    "conflict_type": "blackout_date",
                    "severity": "Critical",
                    "affected_activity": None,
                    "affected_user": staff_profile.user,
                    "date_range": b.isoformat(),
                    "recommended_action": "Requested period includes a blocked organizational date.",
                    "can_auto_reschedule": False,
                    "can_reassign": False,
                }
            )

        conferences = CalendarBlock.objects.filter(
            block_type="STAFF_CONFERENCE",
            is_active=True,
            start_date__lte=e,
            end_date__gte=s,
        )
        for conf in conferences:
            conflicts.append(
                {
                    "conflict_type": "staff_conference",
                    "severity": "Warning",
                    "affected_activity": None,
                    "affected_user": staff_profile.user,
                    "date_range": f"{conf.start_date} to {conf.end_date}",
                    "recommended_action": f"Overlaps with Staff Conference Week: {conf.title}",
                    "can_auto_reschedule": False,
                    "can_reassign": False,
                }
            )

        if cover_profile:
            cover_leaves = Leave.objects.filter(
                staff=cover_profile,
                status="approved",
                start_date__lte=end_date_str,
                end_date__gte=start_date_str,
            )
            for cl in cover_leaves:
                conflicts.append(
                    {
                        "conflict_type": "cover_unavailable",
                        "severity": "Critical",
                        "affected_activity": None,
                        "affected_user": cover_profile.user,
                        "date_range": f"{cl.start_date} to {cl.end_date}",
                        "recommended_action": "Covering person is also on approved leave during this range.",
                        "can_auto_reschedule": False,
                        "can_reassign": False,
                    }
                )

            cover_acts_count = (
                Activity.objects.filter(
                    responsible_staff_id__in=_activity_owner_ids(cover_profile),
                    scheduled_date__gte=scheduled_start,
                    scheduled_date__lt=scheduled_end,
                )
                .exclude(status__in=["cancelled", "completed"])
                .count()
            )

            if cover_acts_count > 5:
                conflicts.append(
                    {
                        "conflict_type": "high_workload_cover",
                        "severity": "Warning",
                        "affected_activity": None,
                        "affected_user": cover_profile.user,
                        "date_range": f"{start_date_str} to {end_date_str}",
                        "recommended_action": f"Covering person has high workload ({cover_acts_count} activities) during this period.",
                        "can_auto_reschedule": False,
                        "can_reassign": False,
                    }
                )

        return conflicts


# PlanningAvailabilityService now lives at apps.core.calendar_policy as
# SchedulingPolicyService (REG-02) — imported above under the historical name
# so every existing call site keeps working unchanged.


class LeaveImpactPreviewService:
    @staticmethod
    def preview_impact(
        staff_profile: StaffProfile, start_date_str: str, end_date_str: str
    ) -> dict:
        from datetime import date

        s = date.fromisoformat(start_date_str)
        e = date.fromisoformat(end_date_str)

        calendar_days = (e - s).days + 1
        working_days = WorkingDayCalculator.calculate_working_days(
            start_date_str, end_date_str
        )

        weekends = 0
        curr = s
        while curr <= e:
            if curr.weekday() >= 5:
                weekends += 1
            curr += timedelta(days=1)

        holidays_list = PublicHolidayService.get_holidays_in_range(
            start_date_str, end_date_str
        )
        holidays_count = len(holidays_list)

        blackouts_list = BlackoutDateService.get_blackout_dates_in_range(
            start_date_str, end_date_str
        )
        blackouts_count = len(blackouts_list)

        conferences = CalendarBlock.objects.filter(
            block_type="STAFF_CONFERENCE",
            is_active=True,
            start_date__lte=e,
            end_date__gte=s,
        )
        conf_overlap = conferences.exists()

        from apps.activities.models import Activity

        scheduled_start, scheduled_end = _scheduled_datetime_window(s, e)

        affected_activities_count = (
            Activity.objects.filter(
                responsible_staff_id__in=_activity_owner_ids(staff_profile),
                scheduled_date__gte=scheduled_start,
                scheduled_date__lt=scheduled_end,
            )
            .exclude(status__in=["cancelled", "completed"])
            .count()
        )

        return {
            "calendar_days": calendar_days,
            "working_days_charged": working_days,
            "weekends_skipped": weekends,
            "public_holidays_skipped": holidays_count,
            "blackout_dates_skipped": blackouts_count,
            "staff_conference_overlap": conf_overlap,
            "affected_activities_count": affected_activities_count,
        }


class TeamAvailabilityService:
    @staticmethod
    def get_4week_heatmap(
        supervisor_profile: StaffProfile | None = None,
        country_scope: bool = False,
        limit: int | None = None,
    ) -> list[dict]:
        """Build the 4-week availability matrix.

        Was a severe nested N+1: 4 queries (leaves/conferences/blackouts/
        activity count) per staff member PER WEEK — up to 16 queries per
        staff — over an unbounded, org-wide staff queryset for CD/HR/Admin
        (some callers then sliced the result to [:10] in Python, after
        already paying for the full computation). Batches every lookup once
        for the whole team/window instead; pass `limit` to also bound the
        staff queryset itself for preview call sites that only show a few
        rows.
        """
        from datetime import date, timedelta
        from apps.accounts.models import StaffProfile, Leave
        from apps.activities.models import Activity

        today = date.today()
        weeks = []
        for i in range(4):
            start = today + timedelta(weeks=i) - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            weeks.append((start, end))
        overall_start, overall_end = weeks[0][0], weeks[-1][1]

        staff_qs = (
            StaffProfile.objects.filter(deleted_at__isnull=True)
            .select_related("user")
            .order_by("user__name")
        )
        if supervisor_profile and not country_scope:
            from apps.accounts.models import StaffSupervisorAssignment

            supervisee_ids = StaffSupervisorAssignment.objects.filter(
                supervisor=supervisor_profile
            ).values_list("supervisee_id", flat=True)
            staff_qs = staff_qs.filter(id__in=supervisee_ids)
        if limit:
            staff_qs = staff_qs[:limit]

        staff_list = list(staff_qs)
        if not staff_list:
            return []

        staff_ids = [sp.id for sp in staff_list]
        activity_owner_ids = list(
            dict.fromkeys(
                identity for sp in staff_list for identity in _activity_owner_ids(sp)
            )
        )
        scheduled_start, scheduled_end = _scheduled_datetime_window(
            overall_start, overall_end
        )

        leaves_by_staff: dict[str, list[tuple[str, str]]] = {}
        for row in Leave.objects.filter(
            staff_id__in=staff_ids,
            status="approved",
            start_date__lte=overall_end.isoformat(),
            end_date__gte=overall_start.isoformat(),
        ).values("staff_id", "start_date", "end_date"):
            leaves_by_staff.setdefault(row["staff_id"], []).append(
                (row["start_date"], row["end_date"])
            )

        # Calendar blocks aren't staff-scoped — 2 small global queries total,
        # not per staff member.
        confs = list(
            CalendarBlock.objects.filter(
                block_type="STAFF_CONFERENCE",
                is_active=True,
                start_date__lte=overall_end,
                end_date__gte=overall_start,
            ).values("start_date", "end_date")
        )
        blackouts = list(
            CalendarBlock.objects.filter(
                block_type="BLACKOUT_DATE",
                is_active=True,
                start_date__lte=overall_end,
                end_date__gte=overall_start,
            ).values("start_date", "end_date")
        )

        acts_by_user: dict[str, list] = {}
        for row in (
            Activity.objects.filter(
                responsible_staff_id__in=activity_owner_ids,
                scheduled_date__gte=scheduled_start,
                scheduled_date__lt=scheduled_end,
            )
            .exclude(status__in=["cancelled", "completed"])
            .values("responsible_staff_id", "scheduled_date")
        ):
            acts_by_user.setdefault(row["responsible_staff_id"], []).append(
                row["scheduled_date"]
            )

        matrix = []
        for sp in staff_list:
            staff_leaves = leaves_by_staff.get(sp.id, [])
            user_acts = [
                activity_date
                for identity in _activity_owner_ids(sp)
                for activity_date in acts_by_user.get(identity, [])
            ]
            row = {
                "staff_name": sp.user.name,
                "staff_id": sp.id,
                "role": sp.user.active_role,
                "weeks": [],
            }
            for start, end in weeks:
                start_iso, end_iso = start.isoformat(), end.isoformat()
                on_leave = any(
                    l_start <= end_iso and l_end >= start_iso
                    for l_start, l_end in staff_leaves
                )
                in_conf = any(
                    c["start_date"] <= end and c["end_date"] >= start for c in confs
                )
                in_blackout = any(
                    b["start_date"] <= end and b["end_date"] >= start for b in blackouts
                )
                act_count = sum(
                    1
                    for sd in user_acts
                    if sd and start <= timezone.localtime(sd).date() <= end
                )

                status = "Available"
                if on_leave:
                    status = "On Leave"
                elif in_conf:
                    status = "Conference Week"
                elif in_blackout:
                    status = "Blocked"
                elif act_count >= 5:
                    status = "High Workload"

                row["weeks"].append(
                    {
                        "start": start_iso,
                        "end": end_iso,
                        "status": status,
                        "act_count": act_count,
                    }
                )
            matrix.append(row)

        return matrix


class LeaveNotificationService:
    @staticmethod
    def notify_leave_requested(leave: Leave) -> None:
        """Notify the supervisor and HR that a new leave request needs approval."""
        from apps.accounts.models import StaffSupervisorAssignment, User
        from apps.notifications.services import WorkflowNotificationService

        staff = leave.staff
        supervisor_asgn = StaffSupervisorAssignment.objects.filter(
            supervisee=staff
        ).first()
        supervisor = supervisor_asgn.supervisor if supervisor_asgn else None

        body = (
            f"{staff.user.name if staff.user else 'Staff'} has requested {leave.type.replace('_', ' ')} "
            f"from {leave.start_date} to {leave.end_date} ({leave.days_charged} working days). "
            f"Please review and approve or reject this request."
        )

        recipients = []
        if supervisor and supervisor.user_id:
            recipients.append(supervisor.user_id)
        # Always notify HR so they can track
        for hr in User.objects.filter(
            active_role="HumanResources", deleted_at__isnull=True
        ):
            recipients.append(hr.id)
        # CD can also see if the staff member is a PL
        if staff.user and staff.user.active_role == "Program Lead":
            for cd in User.objects.filter(
                active_role="CountryDirector", deleted_at__isnull=True
            ):
                recipients.append(cd.id)

        if not recipients:
            return

        WorkflowNotificationService.trigger(
            event_type="leave_requested",
            category="leave",
            priority="high",
            title="Leave Request Needs Approval",
            body=body,
            context_type="Leave",
            context_id=leave.id,
            recipients=recipients,
        )

    @staticmethod
    def notify_leave_approved(leave: Leave) -> None:
        original_staff = leave.staff
        cover_staff = leave.covering_staff

        from apps.accounts.models import StaffSupervisorAssignment

        supervisor_assignment = StaffSupervisorAssignment.objects.filter(
            supervisee=original_staff
        ).first()
        supervisor = supervisor_assignment.supervisor if supervisor_assignment else None

        body = (
            f"{original_staff.user.name} will be on Personal Time Off from {leave.start_date} to {leave.end_date}. "
            f"{cover_staff.user.name if cover_staff else 'None'} will cover her dashboard, planning, My Plan, and cluster follow-up during this period."
        )

        recipients = []
        if cover_staff:
            recipients.append(cover_staff.user.id)
        if supervisor:
            recipients.append(supervisor.user.id)

        from apps.accounts.models import User

        hr_users = User.objects.filter(active_role="HumanResources")
        for hr in hr_users:
            recipients.append(hr.id)

        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="leave_approved",
            category="leave",
            priority="normal",
            title="Leave Coverage Activated",
            body=body,
            context_type="Leave",
            context_id=leave.id,
            recipients=recipients,
        )

    @staticmethod
    def notify_leave_rejected(
        leave: Leave, reviewer_name: str, reason: str = ""
    ) -> None:
        """Notify the requesting staff member that their leave was rejected."""
        from apps.notifications.services import WorkflowNotificationService

        staff = leave.staff
        if not staff or not staff.user_id:
            return

        body = (
            f"Your {leave.type.replace('_', ' ')} request ({leave.start_date} to {leave.end_date}) "
            f"has been rejected by {reviewer_name}."
        )
        if reason:
            body += f" Reason: {reason}"

        WorkflowNotificationService.trigger(
            event_type="leave_rejected",
            category="leave",
            priority="high",
            title="Leave Request Rejected",
            body=body,
            context_type="Leave",
            context_id=leave.id,
            recipients=[staff.user_id],
        )

    @staticmethod
    def notify_leave_returned(
        leave: Leave, reviewer_name: str, reason: str = ""
    ) -> None:
        """Notify the requesting staff member that their leave was returned for correction."""
        from apps.notifications.services import WorkflowNotificationService

        staff = leave.staff
        if not staff or not staff.user_id:
            return

        body = (
            f"Your {leave.type.replace('_', ' ')} request ({leave.start_date} to {leave.end_date}) "
            f"has been returned by {reviewer_name} for review. Please update and resubmit."
        )
        if reason:
            body += f" Note: {reason}"

        WorkflowNotificationService.trigger(
            event_type="leave_returned",
            category="leave",
            priority="normal",
            title="Leave Request Returned for Review",
            body=body,
            context_type="Leave",
            context_id=leave.id,
            recipients=[staff.user_id],
        )

    @staticmethod
    def notify_conflict_detected(user_id: str, message: str, leave_id: str) -> None:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="conflict_detected",
            category="leave",
            priority="normal",
            title="Schedule Conflict Detected",
            body=message,
            context_type="Leave",
            context_id=leave_id,
            recipients=[user_id],
        )

    @staticmethod
    def notify_holiday_conflict(user_id: str, message: str) -> None:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="holiday_blocked",
            category="blackout",
            priority="normal",
            title="Holiday Blocked Scheduling",
            body=message,
            context_type="CalendarBlock",
            recipients=[user_id],
        )

    @staticmethod
    def notify_leave_coverage_assigned(leave: Leave) -> None:
        """Notify the coverage employee that they have been proposed to cover a leave request."""
        from apps.notifications.services import WorkflowNotificationService

        cover = leave.covering_staff
        if not cover or not cover.user_id:
            return

        body = (
            f"You have been proposed by {leave.staff.user.name} to cover their role during their leave "
            f"from {leave.start_date} to {leave.end_date}. Please accept or decline the request."
        )

        WorkflowNotificationService.trigger(
            event_type="leave_coverage_proposed",
            category="leave",
            priority="normal",
            title="Leave Coverage Assignment Proposed",
            body=body,
            context_type="Leave",
            context_id=leave.id,
            recipients=[cover.user_id],
        )


class LeaveBudgetImpactService:
    @staticmethod
    def handle_reschedule(activity, old_date, new_date, reason) -> None:
        if not old_date or not new_date or old_date == new_date:
            return

        from apps.activities.models import ActivityScheduleCostLine
        from apps.core.fy import get_operational_fy, get_quarter_for_date

        new_fy = get_operational_fy(new_date)
        new_quarter = get_quarter_for_date(new_date)

        new_week = new_date.isocalendar()[1]
        old_week = old_date.isocalendar()[1]

        cost_lines = ActivityScheduleCostLine.objects.filter(activity=activity)
        for line in cost_lines:
            line.planned_date = new_date
            line.week_start_date = new_date - timedelta(days=new_date.weekday())
            line.week_end_date = line.week_start_date + timedelta(days=6)
            line.month = new_date.month
            line.quarter = new_quarter
            line.fiscal_year = new_fy

            trail = f" [Audit: Rescheduled due to {reason}. Old period: Week {old_week}, New period: Week {new_week}]"
            if line.description:
                if "Rescheduled due to" not in line.description:
                    line.description = f"{line.description}{trail}"[:255]
            else:
                line.description = trail.strip()[:255]

            line.save()

            wfr_line = line.weekly_request_lines.first()
            if wfr_line:
                wfr_line.week_number = new_week
                wfr_line.save()
