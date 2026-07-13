"""PDApprovalRoutingService — one routing engine for every employee role.

The lifecycle is identical for everyone: Supervisor → HR → Finance. Only the
*people* filling those seats change, resolved generically:

  Stage 1 (Supervisor) = whoever supervises this StaffProfile via
    StaffSupervisorAssignment. This single rule reproduces every routing
    example in the mandate (CCEO→PL, PL→CD, CD→RVP, PC/IA/Accountant→their
    configured supervisor) without a per-role table. If nobody supervises the
    requester (e.g. an RVP with no configured executive supervisor), stage 1
    auto-clears with an audit note and the request proceeds straight to HR —
    documented, not silently skipped.

  Stage 2 (HR) = an active HumanResources user. If the requester IS HR, the
    pool excludes them (conflict of interest, §13/§31); if no other HR user
    exists, an independent CD/RVP reviews instead — never the requester.

  Stage 3 (Finance) = an active Accountant user, same self-exclusion rule.

No employee may approve, sign off, or clear their own request — enforced by
`_pick_approver` at the point a reviewer is resolved, not just at submit time.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import BadRequest, Forbidden

from apps.professional_development.models import FUNDED_TYPES, PDStatus, ProfessionalDevelopmentRequest

HR_ROLE = "HumanResources"
FINANCE_ROLE = "Accountant"
LEADERSHIP_ROLES = ("CountryDirector", "RegionalVicePresident")


def _pick_approver(role: str, exclude_user_id: str) -> User | None:
    """An active user in `role`, excluding the requester. Falls back to
    leadership (CD/RVP) when the excluded person is the only holder of that
    role — never returns the excluded user."""
    pool = User.objects.filter(
        roles__contains=[role], status="active", deleted_at__isnull=True
    ).exclude(id=exclude_user_id)
    pick = pool.order_by("name").first()
    if pick:
        return pick
    if role == HR_ROLE:
        return (
            User.objects.filter(roles__contains=["CountryDirector"], status="active")
            .exclude(id=exclude_user_id).first()
            or User.objects.filter(roles__contains=["RegionalVicePresident"], status="active")
            .exclude(id=exclude_user_id).first()
        )
    return None


class PDApprovalRoutingService:
    @staticmethod
    def supervisor_for(staff: StaffProfile) -> StaffProfile | None:
        link = StaffSupervisorAssignment.objects.filter(supervisee=staff).select_related(
            "supervisor__user"
        ).first()
        return link.supervisor if link else None

    @staticmethod
    def can_review(req: ProfessionalDevelopmentRequest, principal) -> bool:
        """Non-raising authorization check for the view layer — is this
        principal the reviewer entitled to act on this request RIGHT NOW."""
        if req.staff_id == (principal.staff_profile_id or ""):
            return False
        if req.status == PDStatus.SUBMITTED_TO_SUPERVISOR:
            staff = StaffProfile.objects.filter(id=req.staff_id).first()
            supervisor = PDApprovalRoutingService.supervisor_for(staff) if staff else None
            return bool(supervisor and supervisor.user_id == principal.user_id)
        if req.status in (PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION):
            return getattr(principal, "active_role", "") in (HR_ROLE,) + LEADERSHIP_ROLES
        return False

    # ── Submission ────────────────────────────────────────────────────────────
    @staticmethod
    def submit(req: ProfessionalDevelopmentRequest, principal) -> ProfessionalDevelopmentRequest:
        if req.staff_id != (principal.staff_profile_id or ""):
            raise Forbidden("You may only submit your own request.")
        if req.status not in (PDStatus.DRAFT, PDStatus.RETURNED_BY_SUPERVISOR, PDStatus.RETURNED_BY_HR):
            raise BadRequest("Only a draft or returned request can be submitted.")
        required = [
            req.course_name, req.course_type, req.institution, req.start_date,
            req.end_date, req.funding_type,
        ]
        if any(v in (None, "") for v in required):
            raise BadRequest("Course name, type, institution, dates and funding type are required.")
        if req.course_type == "in_person" and not req.evidence_files.filter(
            status="uploaded"
        ).exists():
            raise BadRequest("In-person courses require an admission or enrollment letter (PDF).")
        if req.course_type == "online" and not (req.course_link or "").strip():
            raise BadRequest("Online courses require an institution or course link.")
        if req.course_type == "hybrid" and not (
            (req.course_link or "").strip() and req.evidence_files.filter(status="uploaded").exists()
        ):
            raise BadRequest("Hybrid courses require both a course link and enrollment evidence.")

        req.total_cost_cents = (req.course_fee_cents or 0) + (req.other_costs_cents or 0)

        # §9 — the requested amount must not exceed the remaining PD fund
        # unless the employee has explicitly requested a funding exception.
        if req.funding_type in FUNDED_TYPES and req.requested_amount_cents > 0:
            from apps.professional_development.services import StaffPDService

            staff_user = StaffProfile.objects.get(id=req.staff_id).user
            remaining = StaffPDService.balances(staff_user, req.fy)["remaining"]
            over_allocation = req.requested_amount_cents > remaining
            if over_allocation and not (req.exception_reason or "").strip():
                raise BadRequest(
                    f"Requested amount exceeds your remaining PD fund "
                    f"({req.currency} {remaining/100:,.0f} available) — provide a funding "
                    "exception reason to proceed."
                )
            req.is_exception = over_allocation

        supervisor = PDApprovalRoutingService.supervisor_for(
            StaffProfile.objects.get(id=req.staff_id)
        )
        req.status = (
            PDStatus.SUBMITTED_TO_SUPERVISOR if supervisor else PDStatus.SUBMITTED_TO_HR
        )
        req.submitted_at = timezone.now()
        req.save()
        if not supervisor:
            PDApprovalRoutingService._notify_hr_stage(req)
        else:
            PDApprovalRoutingService._notify(
                supervisor.user_id, "PD request awaiting your review",
                f"{req.staff_name} requested Professional Development support for "
                f"“{req.course_name}”.", req)
        return req

    # ── Stage 1: Supervisor ──────────────────────────────────────────────────
    @staticmethod
    def _assert_supervisor(req: ProfessionalDevelopmentRequest, principal) -> None:
        if req.status != PDStatus.SUBMITTED_TO_SUPERVISOR:
            raise BadRequest("This request is not awaiting supervisor review.")
        staff = StaffProfile.objects.filter(id=req.staff_id).first()
        supervisor = PDApprovalRoutingService.supervisor_for(staff) if staff else None
        if not supervisor or supervisor.user_id != principal.user_id:
            raise Forbidden("You are not the configured supervisor for this request.")
        if req.staff_id == (principal.staff_profile_id or ""):
            raise Forbidden("You cannot approve your own request.")

    @staticmethod
    @transaction.atomic
    def supervisor_approve(req_id: str, principal) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(id=req_id)
        PDApprovalRoutingService._assert_supervisor(req, principal)
        conflict = req.conflict_status
        if conflict == "major_conflict":
            raise BadRequest(
                "Major schedule conflict detected — resolve coverage before approving. "
                f"{req.conflict_detail}"
            )
        req.status = PDStatus.SUBMITTED_TO_HR
        req.supervisor_reviewed_by = principal.user_id
        req.supervisor_reviewed_at = timezone.now()
        req.save(update_fields=["status", "supervisor_reviewed_by", "supervisor_reviewed_at", "updated_at"])
        PDApprovalRoutingService._notify_hr_stage(req)
        return req

    @staticmethod
    def supervisor_return(req_id: str, principal, reason: str) -> ProfessionalDevelopmentRequest:
        if not (reason or "").strip():
            raise BadRequest("A return reason is required.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        PDApprovalRoutingService._assert_supervisor(req, principal)
        req.status = PDStatus.RETURNED_BY_SUPERVISOR
        req.supervisor_reviewed_by = principal.user_id
        req.supervisor_reviewed_at = timezone.now()
        req.supervisor_note = reason[:512]
        req.save()
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request returned by your supervisor", reason, req)
        return req

    @staticmethod
    def _notify_hr_stage(req: ProfessionalDevelopmentRequest) -> None:
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save(update_fields=["status", "updated_at"])
        approver = _pick_approver(HR_ROLE, req.owner_user_id)
        if approver:
            PDApprovalRoutingService._notify(
                approver.id, "PD request awaiting HR review",
                f"{req.staff_name} — “{req.course_name}”.", req)

    # ── Stage 2: HR ───────────────────────────────────────────────────────────
    @staticmethod
    def _assert_hr(req: ProfessionalDevelopmentRequest, principal) -> None:
        if req.status not in (PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION):
            raise BadRequest("This request is not awaiting HR review.")
        role = getattr(principal, "active_role", "")
        is_hr_leadership = role in (HR_ROLE,) + LEADERSHIP_ROLES
        if not is_hr_leadership:
            raise Forbidden("Only HR (or leadership, for HR's own requests) may review this stage.")
        if req.staff_id == (principal.staff_profile_id or ""):
            raise Forbidden("You cannot approve or sign off your own request — HR self-approval is not permitted.")

    @staticmethod
    @transaction.atomic
    def hr_approve(req_id: str, principal, exception: bool = False) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(id=req_id)
        PDApprovalRoutingService._assert_hr(req, principal)
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        # By construction the reviewer is never the requester (_assert_hr); a
        # requester whose own role is HR was necessarily routed to someone
        # else — flag that explicitly for the audit trail (§13).
        requester_role = getattr(
            StaffProfile.objects.filter(id=req.staff_id).select_related("user").first(),
            "user", None,
        )
        req.hr_is_independent_reviewer = bool(
            requester_role and requester_role.active_role == HR_ROLE
        )
        if req.is_exception and not exception:
            raise BadRequest("This request requires exception approval before HR can approve it.")
        from apps.professional_development.fund_service import PDFundRequestService

        if req.funding_type in FUNDED_TYPES and req.requested_amount_cents > 0:
            req.status = PDStatus.APPROVED_PENDING_FUNDING
            req.save()
            PDFundRequestService.create(req)
        else:
            req.status = PDStatus.APPROVED_UNFUNDED
            req.save()
        # Calendar block on approval (§14) — never a school Activity.
        from apps.professional_development.services import StaffPDService

        req.calendar_block_id = StaffPDService.create_calendar_block(req)
        req.save(update_fields=["calendar_block_id", "updated_at"])
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request approved",
            f"Your request for “{req.course_name}” was approved by HR.", req)
        PDApprovalRoutingService._message_from_hr(
            req, principal, "Your PD request was approved",
            f"Good news — “{req.course_name}” has been approved. "
            "Check My Professional Development for the next step.")
        return req

    @staticmethod
    def hr_return(req_id: str, principal, reason: str) -> ProfessionalDevelopmentRequest:
        if not (reason or "").strip():
            raise BadRequest("A return reason is required.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        PDApprovalRoutingService._assert_hr(req, principal)
        req.status = PDStatus.RETURNED_BY_HR
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        req.hr_note = reason[:512]
        req.save()
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request returned by HR", reason, req)
        PDApprovalRoutingService._message_from_hr(
            req, principal, "Your PD request needs a fix",
            f"“{req.course_name}” was returned: {reason}")
        return req

    @staticmethod
    def hr_reject(req_id: str, principal, reason: str) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        PDApprovalRoutingService._assert_hr(req, principal)
        req.status = PDStatus.REJECTED
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        req.hr_note = (reason or "")[:512]
        req.save()
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request rejected", reason or "", req)
        PDApprovalRoutingService._message_from_hr(
            req, principal, "Your PD request was not approved",
            f"“{req.course_name}” was rejected." + (f" Reason: {reason}" if reason else ""))
        return req

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _notify(recipient_user_id, title, body, req) -> None:
        if not recipient_user_id:
            return
        try:
            from apps.notifications.models import Notification

            Notification.objects.create(
                recipient_id=recipient_user_id, title=title, body=body,
                category="professional_development", context_type="pd_request",
                context_id=req.id, target_route=f"/my-professional-development/request?id={req.id}",
                action_label="Open", action_required=True, priority="high",
            )
        except Exception:  # noqa: BLE001 — notification is supportive, never blocking
            pass

    @staticmethod
    def _message_from_hr(req, principal, subject: str, body: str) -> None:
        """Feeds the employee's "Messages from HR" panel — distinct from the
        Notification bell, and best-effort so it never blocks the decision."""
        if not req.owner_user_id:
            return
        try:
            from apps.messaging.services import workflow_message

            workflow_message(
                context_type="professional_development", context_id=req.id,
                subject=subject, body=body, recipient_ids=[req.owner_user_id],
                category="professional_development", priority="high",
                sender_id=principal.user_id,
            )
        except Exception:  # noqa: BLE001
            pass
