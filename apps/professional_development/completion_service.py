"""PD completion pipeline (§17, §20–24).

Enrollment confirmation → course-date-driven status sync → employee marks
complete (does NOT close the record) → certificate upload → BambooHR
confirmation → accountability + NetSuite Expense ID (funded only) → HR
sign-off (the ONLY action that closes the record). Every gate in §24 is
enforced in `sign_off()` — HR literally cannot close a record missing any of
them, and the independent-reviewer rule from the approval stage applies here
too (an HR employee can never sign off their own course).
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from apps.professional_development.models import (
    FUNDED_TYPES,
    PDStatus,
    ProfessionalDevelopmentCertificate,
    ProfessionalDevelopmentEvidence,
    ProfessionalDevelopmentRequest,
)
from apps.professional_development.uploads import store_pd_file

HR_ROLE = "HumanResources"


def _may_close_stage(req, principal) -> bool:
    """Who may verify BambooHR, sign off, or return a completion.

    HR owns these stages. Leadership is only ever the fallback for HR's OWN
    request, and only within its own country — the same rule the HR approval
    stage already enforces. Without this the closing stages accepted any
    CountryDirector or RegionalVicePresident for any employee in any country:
    a CD in one country could close another country's record.
    """
    from apps.professional_development.approval_service import _may_review_hr_stage

    return _may_review_hr_stage(req, principal)

# HR return-reason → the status the record snaps back to, and who must act.
RETURN_REASON_TARGETS = {
    "certificate_missing": PDStatus.MARKED_COMPLETE,
    "certificate_unreadable": PDStatus.MARKED_COMPLETE,
    "wrong_certificate": PDStatus.MARKED_COMPLETE,
    "bamboohr_not_confirmed": PDStatus.CERTIFICATE_UPLOADED,
    "course_not_completed": PDStatus.ENDED,
    "accountability_incomplete": PDStatus.BAMBOOHR_CONFIRMED,
    "netsuite_missing": PDStatus.BAMBOOHR_CONFIRMED,
    "finance_not_cleared": PDStatus.ACCOUNTABILITY_SUBMITTED,
    "learning_application_incomplete": PDStatus.MARKED_COMPLETE,
    "other": PDStatus.MARKED_COMPLETE,
}


def _assert_owner(req: ProfessionalDevelopmentRequest, principal) -> None:
    if req.staff_id != (principal.staff_profile_id or ""):
        raise Forbidden("You may only act on your own Professional Development record.")


class PDCourseTrackingService:
    @staticmethod
    def can_signoff_review(req: ProfessionalDevelopmentRequest, principal) -> bool:
        if req.staff_id == (principal.staff_profile_id or ""):
            return False
        if getattr(principal, "active_role", "") not in (
            HR_ROLE,
            "CountryDirector",
            "RegionalVicePresident",
            "Admin",
        ):
            return False
        return req.status == PDStatus.AWAITING_HR_SIGNOFF

    @staticmethod
    def sync_dates(
        req: ProfessionalDevelopmentRequest, today: date | None = None
    ) -> ProfessionalDevelopmentRequest:
        """Lazy status advance driven purely by today's date — called on every
        page read, no cron required. Never advances past what the employee/HR
        workflow has actually reached (e.g. never touches DRAFT or anything
        awaiting a human decision)."""
        today = today or date.today()
        changed = False
        if req.status == PDStatus.ENROLLMENT_CONFIRMED and today >= req.start_date:
            req.status = PDStatus.IN_PROGRESS
            changed = True
        if req.status == PDStatus.IN_PROGRESS and today >= req.end_date:
            req.status = PDStatus.ENDED
            changed = True
        if changed:
            req.save(update_fields=["status", "updated_at"])
        return req

    @staticmethod
    def sync_all(staff_id: str) -> None:
        today = date.today()
        for req in ProfessionalDevelopmentRequest.objects.filter(
            staff_id=staff_id,
            status__in=[PDStatus.ENROLLMENT_CONFIRMED, PDStatus.IN_PROGRESS],
        ):
            PDCourseTrackingService.sync_dates(req, today)

    # ── §17 Enrollment confirmation ──────────────────────────────────────────
    @staticmethod
    def confirm_enrollment(
        req_id: str, principal, *, enrollment_date, reference: str = ""
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        if req.status not in (
            PDStatus.DISBURSED,
            PDStatus.APPROVED_UNFUNDED,
            PDStatus.ENROLLMENT_PENDING,
        ):
            raise BadRequest("This request is not ready for enrollment confirmation.")
        req.enrollment_confirmed = True
        req.enrollment_confirmed_at = timezone.now()
        req.enrollment_date = enrollment_date
        req.enrollment_reference = (reference or "")[:255]
        req.status = PDStatus.ENROLLMENT_CONFIRMED
        req.save()
        PDCourseTrackingService.sync_dates(req)
        return req

    # ── §20 Employee marks complete (does not close the record) ─────────────
    @staticmethod
    def mark_complete(
        req_id: str,
        principal,
        *,
        actual_completion_date,
        course_outcome: str,
        skills_gained: str = "",
        application_plan: str = "",
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        PDCourseTrackingService.sync_dates(req)
        if req.status != PDStatus.ENDED:
            raise BadRequest(
                "The course must reach its end date before it can be marked complete."
            )
        if not (course_outcome or "").strip():
            raise BadRequest("A course outcome summary is required.")
        req.actual_completion_date = actual_completion_date
        req.course_outcome = course_outcome
        req.skills_gained = skills_gained
        req.application_plan = application_plan
        req.marked_complete_at = timezone.now()
        req.status = PDStatus.MARKED_COMPLETE
        req.save()
        return req

    @staticmethod
    def mark_deferred_or_withdrawn(
        req_id: str, principal, *, outcome: str, reason: str
    ) -> ProfessionalDevelopmentRequest:
        if outcome not in ("deferred", "withdrawn"):
            raise BadRequest("Unknown outcome.")
        if not (reason or "").strip():
            raise BadRequest("A reason is required.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        PDCourseTrackingService.sync_dates(req)
        if req.status not in (
            PDStatus.ENDED,
            PDStatus.IN_PROGRESS,
            PDStatus.ENROLLMENT_CONFIRMED,
        ):
            raise BadRequest(
                "This course cannot be deferred or withdrawn from its current state."
            )
        req.status = PDStatus.DEFERRED if outcome == "deferred" else PDStatus.WITHDRAWN
        req.deferred_withdrawn_reason = reason[:512]
        req.save()
        return req

    # ── §21 Certificate upload ────────────────────────────────────────────────
    @staticmethod
    def upload_certificate(
        req_id: str,
        principal,
        file_obj,
        *,
        certificate_name="",
        certificate_number="",
        issuing_institution="",
        issue_date=None,
        expiry_date=None,
        verification_link="",
    ) -> ProfessionalDevelopmentCertificate:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        if req.status not in (PDStatus.MARKED_COMPLETE, PDStatus.CERTIFICATE_UPLOADED):
            raise BadRequest("Mark the course complete before uploading a certificate.")
        stored = store_pd_file(file_obj)
        stored.pop(
            "file_extension", None
        )  # not a field on Certificate (only Evidence has it)
        cert = ProfessionalDevelopmentCertificate.objects.create(
            request=req,
            uploaded_by=principal.user_id,
            certificate_name=certificate_name or req.course_name,
            certificate_number=certificate_number,
            issuing_institution=issuing_institution,
            issue_date=issue_date,
            expiry_date=expiry_date,
            verification_link=verification_link,
            **stored,
        )
        req.status = PDStatus.CERTIFICATE_UPLOADED
        req.save(update_fields=["status", "updated_at"])
        return cert

    @staticmethod
    def upload_evidence(
        req_id: str, principal, file_obj, kind: str
    ) -> ProfessionalDevelopmentEvidence:
        """§8 — conditional enrollment evidence, uploaded at request time or
        while a returned request is being fixed."""
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        if req.status not in (
            PDStatus.DRAFT,
            PDStatus.RETURNED_BY_SUPERVISOR,
            PDStatus.RETURNED_BY_HR,
        ):
            raise BadRequest(
                "Evidence can only be added while the request is a draft or returned for correction."
            )
        stored = store_pd_file(file_obj)
        return ProfessionalDevelopmentEvidence.objects.create(
            request=req, kind=kind, uploaded_by=principal.user_id, **stored
        )

    # ── §22 BambooHR upload confirmation ─────────────────────────────────────
    @staticmethod
    def confirm_bamboohr(
        req_id: str, principal, reference: str = ""
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        if req.status != PDStatus.CERTIFICATE_UPLOADED:
            raise BadRequest(
                "Upload your certificate to Edify before confirming the BambooHR upload."
            )
        req.bamboohr_uploaded = True
        req.bamboohr_uploaded_at = timezone.now()
        req.bamboohr_reference = (reference or "")[:255]
        # Unfunded courses skip accountability entirely and go straight to
        # the sign-off gate; funded courses still owe accountability.
        req.status = (
            PDStatus.BAMBOOHR_CONFIRMED
            if req.funding_type in FUNDED_TYPES
            else PDStatus.AWAITING_HR_SIGNOFF
        )
        req.save()
        return req

    @staticmethod
    def verify_bamboohr(req_id: str, principal) -> ProfessionalDevelopmentRequest:
        """HR opens/verifies the BambooHR record (§22 no-integration fallback).
        Informational — not a hard gate for sign-off beyond the employee's
        own confirmation, which HR reviews at sign-off time regardless."""
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        role = getattr(principal, "active_role", "")
        if not _may_close_stage(req, principal):
            raise Forbidden("Only HR may verify a BambooHR upload.")
        req.bamboohr_verified_by = principal.user_id
        req.bamboohr_verified_at = timezone.now()
        req.save(
            update_fields=["bamboohr_verified_by", "bamboohr_verified_at", "updated_at"]
        )
        return req

    # ── §23 Accountability + NetSuite Expense ID (funded courses only) ──────
    @staticmethod
    def submit_accountability(
        req_id: str,
        principal,
        *,
        actual_spent: int,
        returned_amount: int,
        netsuite_expense_id: str,
        variance_note: str = "",
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        _assert_owner(req, principal)
        if (
            req.status != PDStatus.BAMBOOHR_CONFIRMED
            or req.funding_type not in FUNDED_TYPES
        ):
            raise BadRequest("Accountability is not due for this request.")
        if not (netsuite_expense_id or "").strip():
            # Non-negotiable (§23): no NetSuite Expense ID → accountability
            # remains incomplete. Never allow submission without it.
            raise BadRequest(
                "A NetSuite Expense ID is required to submit accountability."
            )
        disbursed = req.requested_amount_cents
        if (
            actual_spent + returned_amount != disbursed
            and not (variance_note or "").strip()
        ):
            raise BadRequest(
                "Actual spent plus returned amount must equal the disbursed amount, "
                "or a variance explanation is required."
            )
        req.accounted_amount = actual_spent
        req.returned_amount = returned_amount
        req.accountability_netsuite_id = netsuite_expense_id.strip()
        req.accountability_variance_note = variance_note
        req.accountability_submitted_at = timezone.now()
        req.accountability_status = "submitted"
        req.status = PDStatus.ACCOUNTABILITY_SUBMITTED
        req.save()
        try:
            from apps.professional_development.approval_service import _pick_approver
            from apps.professional_development.fund_service import PDFundRequestService

            approver = _pick_approver("Accountant", req.owner_user_id)
            if approver:
                PDFundRequestService._notify(
                    approver.id,
                    "PD accountability submitted",
                    f"{req.staff_name} submitted accountability for “{req.course_name}”.",
                    req,
                )
        except Exception:  # noqa: BLE001
            pass
        return req

    # ── §24 HR Sign-Off — the ONLY action that closes the record ─────────────
    @staticmethod
    def _assert_signoff_eligible(req: ProfessionalDevelopmentRequest) -> list[str]:
        missing = []
        if not req.marked_complete_at:
            missing.append("Employee has not marked the course complete")
        if not req.certificates.filter(status="uploaded").exists():
            missing.append("Certificate missing")
        if not req.bamboohr_uploaded:
            missing.append("BambooHR upload not confirmed")
        if req.funding_type in FUNDED_TYPES:
            if not (req.accountability_netsuite_id or "").strip():
                missing.append("NetSuite Expense ID missing")
            if not req.accountability_reviewed_at:
                missing.append("Finance has not cleared accountability")
        return missing

    @staticmethod
    @transaction.atomic
    def sign_off(req_id: str, principal) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(id=req_id)
        role = getattr(principal, "active_role", "")
        if not _may_close_stage(req, principal):
            raise Forbidden(
                "Only HR (or leadership, for HR's own course) may sign off."
            )
        if req.staff_id == (principal.staff_profile_id or ""):
            raise Forbidden(
                "You cannot sign off your own Professional Development record."
            )
        if req.status != PDStatus.AWAITING_HR_SIGNOFF:
            raise BadRequest("This record is not awaiting HR sign-off.")
        missing = PDCourseTrackingService._assert_signoff_eligible(req)
        if missing:
            raise BadRequest("Cannot sign off — " + "; ".join(missing) + ".")
        req.status = PDStatus.COMPLETED_CLOSED
        req.signed_off_by = principal.user_id
        req.signed_off_at = timezone.now()
        req.save()
        PDCourseTrackingService._update_cpd_and_skills(req)
        try:
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )
            from apps.professional_development.fund_service import PDFundRequestService

            PDFundRequestService._notify(
                req.owner_user_id,
                "Professional Development closed",
                f"“{req.course_name}” has been signed off and closed by HR.",
                req,
            )
            PDApprovalRoutingService._message_from_hr(
                req,
                principal,
                "Your Professional Development course is closed",
                f"“{req.course_name}” has been signed off and closed — congratulations "
                "on completing your Professional Development.",
            )
        except Exception:  # noqa: BLE001
            pass
        return req

    @staticmethod
    def hr_return_completion(
        req_id: str, principal, reason_category: str, note: str = ""
    ) -> ProfessionalDevelopmentRequest:
        target = RETURN_REASON_TARGETS.get(reason_category)
        if target is None:
            raise BadRequest("Unknown return reason.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        role = getattr(principal, "active_role", "")
        if not _may_close_stage(req, principal):
            raise Forbidden("Only HR may return a completion for correction.")
        if req.staff_id == (principal.staff_profile_id or ""):
            raise Forbidden(
                "You cannot review your own Professional Development record."
            )
        if req.status != PDStatus.AWAITING_HR_SIGNOFF:
            raise BadRequest("This record is not awaiting HR sign-off.")
        req.status = target
        req.hr_note = f"[{reason_category.replace('_', ' ').title()}] {note}"[:512]
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        req.save()
        try:
            from apps.professional_development.approval_service import (
                PDApprovalRoutingService,
            )
            from apps.professional_development.fund_service import PDFundRequestService

            PDFundRequestService._notify(
                req.owner_user_id, "PD completion returned by HR", req.hr_note, req
            )
            PDApprovalRoutingService._message_from_hr(
                req, principal, "Your PD completion needs a fix", req.hr_note
            )
        except Exception:  # noqa: BLE001
            pass
        return req

    # ── §24 closing hooks: CPD history + Skills Matrix ───────────────────────
    @staticmethod
    def _update_cpd_and_skills(req: ProfessionalDevelopmentRequest) -> None:
        try:
            from apps.hr.models import CPDAssignment, EmployeeSkill, Skill

            CPDAssignment.objects.update_or_create(
                staff_id=req.staff_id,
                course_name=req.course_name,
                defaults={
                    "category": req.course_category,
                    "status": "Verified",
                    "evidence_url": (
                        req.certificates.filter(status="uploaded")
                        .order_by("-created_at")
                        .values_list("uri", flat=True)
                        .first()
                    ),
                    "completed_at": req.signed_off_at,
                },
            )
            for line in (req.skills_gained or "").replace(",", "\n").splitlines():
                name = line.strip()
                if not name:
                    continue
                skill, _ = Skill.objects.get_or_create(name=name[:128])
                existing = EmployeeSkill.objects.filter(
                    staff_id=req.staff_id, skill=skill
                ).first()
                if existing:
                    existing.level = min(5, existing.level + 1)
                    existing.save(update_fields=["level", "updated_at"])
                else:
                    EmployeeSkill.objects.create(
                        staff_id=req.staff_id, skill=skill, level=2
                    )
        except Exception:  # noqa: BLE001 — CPD/skills sync is a bonus, never blocking sign-off
            pass
