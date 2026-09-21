"""PDApprovalRoutingService — one routing engine for every employee role.

The lifecycle is identical for everyone: Supervisor → HR → Finance. Only the
*people* filling those seats change, resolved generically:

  Stage 1 (Supervisor) = the person the organisation's reporting line names,
    resolved by apps.hr.review_authority — the one place that answers "who
    reviews whom" (CCEO→PL, PL/IA/Accountant/PC/HR→CD, CD→RVP). This used to
    be "whoever holds a StaffSupervisorAssignment row", which is not the same
    thing twice over: the model carries oversight rows beside reporting lines,
    so an assurance reviewer could end up deciding a Programme Lead's course,
    and a row nobody had configured meant no supervisor at all. If the chart
    genuinely names nobody (an RVP with no configured executive supervisor),
    stage 1 auto-clears with an audit note and the request proceeds straight
    to HR — documented, not silently skipped.

  Stage 2 (HR) = an active HumanResources user. If the requester IS HR, the
    pool excludes them (conflict of interest, §13/§31); if no other HR user
    exists, an independent CD/RVP reviews instead — never the requester.

  Stage 3 (Finance) = an active Accountant user, same self-exclusion rule.

No employee may approve, sign off, or clear their own request — enforced by
`_pick_approver` at the point a reviewer is resolved, not just at submit time.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.hr.review_authority import (
    COUNTRY_DIRECTOR,
    LIVE_STATES,
    REVIEWER_ROLE_FOR,
)

from apps.professional_development.models import (
    FUNDED_TYPES,
    PDStatus,
    ProfessionalDevelopmentRequest,
)

HR_ROLE = "HumanResources"
FINANCE_ROLE = "Accountant"
LEADERSHIP_ROLES = ("CountryDirector", "RegionalVicePresident", "Admin")


def _live(staff: StaffProfile) -> bool:
    """Authority belongs to someone who still works here.

    A suspended or exited manager holding a queue is how a request stops
    moving without anyone being told it has stopped.
    """
    user = getattr(staff, "user", None)
    return bool(
        user
        and user.is_active
        and user.deleted_at is None
        and staff.onboarding_state in LIVE_STATES
    )


def _directors_by_country(countries: set[str]) -> dict[str, StaffProfile]:
    """The serving Country Director of each country, one query for all of them.

    Only the Director is resolvable from the chart alone, and only as a
    fallback for someone whose reporting line was never configured. Below the
    Director the line is a roster rather than a role — a CCEO belongs to one
    Programme Lead's team, and picking a Lead by country would hand a stranger
    the approval — so that case keeps waiting for its row, as leave does.

    This is the arm leave has always had (apps.hr.leave_services
    .is_authorized_approver: "Fallback by country scoping for CD"), which is
    why the same employee's leave reached their Director while their course
    did not.
    """
    role_held = Q(user__active_role=COUNTRY_DIRECTOR) | Q(
        user__roles__contains=[COUNTRY_DIRECTOR]
    )
    chosen: dict[str, StaffProfile] = {}
    for profile in (
        StaffProfile.objects.filter(country__in=countries)
        .filter(role_held)
        .filter(
            user__is_active=True,
            user__deleted_at__isnull=True,
            onboarding_state__in=LIVE_STATES,
        )
        .select_related("user")
        .order_by("user__name", "id")
    ):
        chosen.setdefault(profile.country, profile)
    return chosen


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
            .exclude(id=exclude_user_id)
            .first()
            or User.objects.filter(
                roles__contains=["RegionalVicePresident"], status="active"
            )
            .exclude(id=exclude_user_id)
            .first()
        )
    return None


def _audit_decision(
    action: str,
    req: ProfessionalDevelopmentRequest,
    principal,
    *,
    reason: str | None = None,
    extra: dict | None = None,
) -> None:
    """Record a PD decision on the tamper-evident chain.

    PD moves real money (an HR approval spawns the finance disbursement), so
    every decision needs the same trail the budget chain already has.
    """
    from apps.audit.services import log as audit_log

    payload = {
        "requestId": req.id,
        "staffId": req.staff_id,
        "staffName": req.staff_name,
        "course": req.course_name,
        "status": req.status,
        "amountCents": req.requested_amount_cents,
    }
    if extra:
        payload.update(extra)
    audit_log(
        action=action,
        subject_kind="ProfessionalDevelopmentRequest",
        subject_id=req.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload=payload,
    )


def _principal_country(principal) -> str | None:
    staff_id = getattr(principal, "staff_profile_id", None)
    if not staff_id:
        return None
    sp = StaffProfile.objects.filter(id=staff_id).only("country").first()
    return getattr(sp, "country", None) if sp else None


def _may_review_hr_stage(req: ProfessionalDevelopmentRequest, principal) -> bool:
    """Who may act at the HR stage.

    HR owns this stage. Leadership (CD/RVP) is only ever the *fallback*
    reviewer for HR's own request (§13/§31 conflict of interest) — never a
    general approver of everyone's PD. Leadership is additionally confined to
    its own country, so a CD cannot fund development in a country they do not
    run. Previously this was a bare role check, which let any CD or RVP
    approve any request anywhere and spawn the finance disbursement.
    """
    role = getattr(principal, "active_role", "")
    if role == "Admin":
        return req.staff_id != (getattr(principal, "staff_profile_id", None) or "")
    actor_country = _principal_country(principal)
    if role == HR_ROLE:
        # This was an unconditional `return True`, so HR in one country could
        # approve, return, reject, sign off and close a funded course for an
        # employee anywhere — spawning that country's disbursement. The
        # Regional HR Director acts in the countries they oversee.
        from apps.hr.reach import people_reach

        if not req.country:
            return False
        return people_reach(principal).allows_country(req.country)
    if role not in LEADERSHIP_ROLES:
        return False
    requester_is_hr = (
        StaffProfile.objects.filter(id=req.staff_id)
        .filter(user__active_role=HR_ROLE)
        .exists()
    )
    if not requester_is_hr:
        return False
    # An unset country on either side is not a licence to approve globally —
    # and the guard below now does what that sentence says. Written as
    # `if actor_country and req.country and ...` it SKIPPED entirely when
    # either side was falsy and fell through to `return True`, so a leadership
    # account with no StaffProfile approved HR's PD in every country.
    if not actor_country or not req.country:
        return False
    return actor_country == req.country


class PDApprovalRoutingService:
    @staticmethod
    def supervisor_for(staff: StaffProfile) -> StaffProfile | None:
        return PDApprovalRoutingService.supervisors_for([staff]).get(staff.id)

    @staticmethod
    def supervisors_for(staff: list[StaffProfile]) -> dict[str, StaffProfile]:
        """Who reviews each of these people's courses, in three queries.

        The rule is apps.hr.review_authority's, not a second copy of it: a
        configured row counts when its holder is the role the chart names for
        this person and is still employed. That is the whole of the fix to two
        defects review_authority was written for and PD never picked up — an
        oversight row answering "is this their manager?", and an exited manager
        keeping the queue.

        Where the chart names the Country Director and no row was ever
        configured, the Director of that person's country answers, which is
        what leave does. Everything else with no reviewer clears stage 1 for
        HR, §13's documented auto-skip.

        Bulk because the supervisor's own queue asks this about every waiting
        request at once, and it must get the same answer the approval guard
        will give — a queue that lists what you may not decide, or hides what
        you must, is worse than no queue.
        """
        people = [person for person in staff if person]
        if not people:
            return {}

        links: dict[str, list] = {}
        for link in (
            StaffSupervisorAssignment.objects.filter(
                supervisee_id__in=[person.id for person in people]
            )
            .select_related("supervisor__user")
            .order_by("id")
        ):
            links.setdefault(link.supervisee_id, []).append(link)

        resolved: dict[str, StaffProfile] = {}
        from_chart: list[StaffProfile] = []
        for person in people:
            user = getattr(person, "user", None)
            expected = REVIEWER_ROLE_FOR.get(getattr(user, "active_role", ""), ())
            if not expected:
                continue
            reviewer = next(
                (
                    link.supervisor
                    for link in links.get(person.id, [])
                    if getattr(link.supervisor.user, "active_role", "") in expected
                    and _live(link.supervisor)
                ),
                None,
            )
            if reviewer:
                resolved[person.id] = reviewer
            elif expected == (COUNTRY_DIRECTOR,) and person.country:
                from_chart.append(person)

        if from_chart:
            directors = _directors_by_country({p.country for p in from_chart})
            for person in from_chart:
                director = directors.get(person.country)
                # Nobody supervises themselves, however the chart reads.
                if director and director.id != person.id:
                    resolved[person.id] = director
        return resolved

    @staticmethod
    def acting_supervisor_ids(staff: StaffProfile) -> list[str]:
        """User ids entitled to act as this staffer's supervisor right now —
        the configured supervisor plus anyone actively covering for them.

        Without the coverage arm a supervisor's own leave froze every PD
        request routed to them, even though the platform already tracks who is
        standing in.
        """
        supervisor = PDApprovalRoutingService.supervisor_for(staff)
        if not supervisor:
            return []
        ids = [supervisor.user_id] if supervisor.user_id else []
        now = timezone.now()
        covering = (
            TemporaryCoverageAssignment.objects.filter(
                original_staff=supervisor,
                start_datetime__lte=now,
                end_datetime__gte=now,
                status="active",
            )
            .select_related("covering_staff")
            .values_list("covering_staff__user_id", flat=True)
        )
        ids.extend([c for c in covering if c])
        return ids

    @staticmethod
    def can_review(req: ProfessionalDevelopmentRequest, principal) -> bool:
        """Non-raising authorization check for the view layer — is this
        principal the reviewer entitled to act on this request RIGHT NOW."""
        if req.staff_id == (principal.staff_profile_id or ""):
            return False
        if req.status == PDStatus.SUBMITTED_TO_SUPERVISOR:
            staff = StaffProfile.objects.filter(id=req.staff_id).first()
            acting = (
                PDApprovalRoutingService.acting_supervisor_ids(staff) if staff else []
            )
            return principal.user_id in acting
        if req.status in (PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION):
            return _may_review_hr_stage(req, principal)
        return False

    # ── Submission ────────────────────────────────────────────────────────────
    @staticmethod
    def submit(
        req: ProfessionalDevelopmentRequest, principal
    ) -> ProfessionalDevelopmentRequest:
        if req.staff_id != (principal.staff_profile_id or ""):
            raise Forbidden("You may only submit your own request.")
        if req.status not in (
            PDStatus.DRAFT,
            PDStatus.RETURNED_BY_SUPERVISOR,
            PDStatus.RETURNED_BY_HR,
        ):
            raise BadRequest("Only a draft or returned request can be submitted.")
        required = [
            req.course_name,
            req.course_type,
            req.institution,
            req.start_date,
            req.end_date,
            req.funding_type,
        ]
        if any(v in (None, "") for v in required):
            raise BadRequest(
                "Course name, type, institution, dates and funding type are required."
            )
        if (
            req.course_type == "in_person"
            and not req.evidence_files.filter(status="uploaded").exists()
        ):
            raise BadRequest(
                "In-person courses require an admission or enrollment letter (PDF)."
            )
        if req.course_type == "online" and not (req.course_link or "").strip():
            raise BadRequest("Online courses require an institution or course link.")
        if req.course_type == "hybrid" and not (
            (req.course_link or "").strip()
            and req.evidence_files.filter(status="uploaded").exists()
        ):
            raise BadRequest(
                "Hybrid courses require both a course link and enrollment evidence."
            )

        req.total_cost_cents = (req.course_fee_cents or 0) + (
            req.other_costs_cents or 0
        )

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
                    f"({req.currency} {remaining / 100:,.0f} available) — provide a funding "
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
                supervisor.user_id,
                "PD request awaiting your review",
                f"{req.staff_name} requested Professional Development support for "
                f"“{req.course_name}”.",
                req,
            )
        return req

    # ── Stage 1: Supervisor ──────────────────────────────────────────────────
    @staticmethod
    def _assert_supervisor(req: ProfessionalDevelopmentRequest, principal) -> None:
        if req.status != PDStatus.SUBMITTED_TO_SUPERVISOR:
            raise BadRequest("This request is not awaiting supervisor review.")
        staff = StaffProfile.objects.filter(id=req.staff_id).first()
        acting = PDApprovalRoutingService.acting_supervisor_ids(staff) if staff else []
        if principal.user_id not in acting:
            raise Forbidden(
                "You are not the configured supervisor (or active cover) for "
                "this request."
            )
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
        req.save(
            update_fields=[
                "status",
                "supervisor_reviewed_by",
                "supervisor_reviewed_at",
                "updated_at",
            ]
        )
        _audit_decision("pd_supervisor_approve", req, principal)
        PDApprovalRoutingService._notify_hr_stage(req)
        return req

    @staticmethod
    def supervisor_return(
        req_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentRequest:
        if not (reason or "").strip():
            raise BadRequest("A return reason is required.")
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        PDApprovalRoutingService._assert_supervisor(req, principal)
        req.status = PDStatus.RETURNED_BY_SUPERVISOR
        req.supervisor_reviewed_by = principal.user_id
        req.supervisor_reviewed_at = timezone.now()
        req.supervisor_note = reason[:512]
        req.save()
        _audit_decision("pd_supervisor_return", req, principal, reason=reason)
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request returned by your supervisor", reason, req
        )
        return req

    @staticmethod
    def _notify_hr_stage(req: ProfessionalDevelopmentRequest) -> None:
        req.status = PDStatus.SUBMITTED_TO_HR
        req.save(update_fields=["status", "updated_at"])
        # Notify the whole HR desk, not one person. `_pick_approver` returns
        # the alphabetically first holder of the role — so every PD request
        # awaiting HR went to the same individual, and if they were on leave
        # the request simply stalled with nobody else aware of it
        # (2026-08-20 HR audit).
        from apps.notifications.services import role_recipients

        desk = role_recipients(HR_ROLE, exclude_user_id=req.owner_user_id)
        if not desk:
            fallback = _pick_approver(HR_ROLE, req.owner_user_id)
            desk = [fallback] if fallback else []
        for approver in desk:
            PDApprovalRoutingService._notify(
                approver.id,
                "PD request awaiting HR review",
                f"{req.staff_name} — “{req.course_name}”.",
                req,
            )

    # ── Stage 2: HR ───────────────────────────────────────────────────────────
    @staticmethod
    def _assert_hr(req: ProfessionalDevelopmentRequest, principal) -> None:
        if req.status not in (PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION):
            raise BadRequest("This request is not awaiting HR review.")
        if req.staff_id == (principal.staff_profile_id or ""):
            raise Forbidden(
                "You cannot approve or sign off your own request — HR self-approval is not permitted."
            )
        if not _may_review_hr_stage(req, principal):
            raise Forbidden(
                "Only HR (or, for HR's own request, in-country leadership) may review this stage."
            )

    @staticmethod
    @transaction.atomic
    def hr_approve(
        req_id: str, principal, exception: bool = False
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.select_for_update().get(id=req_id)
        PDApprovalRoutingService._assert_hr(req, principal)
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        # By construction the reviewer is never the requester (_assert_hr); a
        # requester whose own role is HR was necessarily routed to someone
        # else — flag that explicitly for the audit trail (§13).
        requester_role = getattr(
            StaffProfile.objects.filter(id=req.staff_id).select_related("user").first(),
            "user",
            None,
        )
        req.hr_is_independent_reviewer = bool(
            requester_role and requester_role.active_role == HR_ROLE
        )
        if req.is_exception and not exception:
            raise BadRequest(
                "This request requires exception approval before HR can approve it."
            )
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
            req.owner_user_id,
            "PD request approved",
            f"Your request for “{req.course_name}” was approved by HR.",
            req,
        )
        PDApprovalRoutingService._message_from_hr(
            req,
            principal,
            "Your PD request was approved",
            f"Good news — “{req.course_name}” has been approved. "
            "Check My Professional Development for the next step.",
        )
        _audit_decision(
            "pd_hr_approve",
            req,
            principal,
            extra={
                "exception": bool(exception),
                "independentReviewer": req.hr_is_independent_reviewer,
            },
        )
        return req

    @staticmethod
    def hr_return(
        req_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentRequest:
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
            req.owner_user_id, "PD request returned by HR", reason, req
        )
        PDApprovalRoutingService._message_from_hr(
            req,
            principal,
            "Your PD request needs a fix",
            f"“{req.course_name}” was returned: {reason}",
        )
        _audit_decision("pd_hr_return", req, principal, reason=reason)
        return req

    @staticmethod
    def hr_reject(
        req_id: str, principal, reason: str
    ) -> ProfessionalDevelopmentRequest:
        req = ProfessionalDevelopmentRequest.objects.get(id=req_id)
        PDApprovalRoutingService._assert_hr(req, principal)
        req.status = PDStatus.REJECTED
        req.hr_reviewed_by = principal.user_id
        req.hr_reviewed_at = timezone.now()
        req.hr_note = (reason or "")[:512]
        req.save()
        PDApprovalRoutingService._notify(
            req.owner_user_id, "PD request rejected", reason or "", req
        )
        PDApprovalRoutingService._message_from_hr(
            req,
            principal,
            "Your PD request was not approved",
            f"“{req.course_name}” was rejected."
            + (f" Reason: {reason}" if reason else ""),
        )
        _audit_decision("pd_hr_reject", req, principal, reason=reason)
        return req

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _notify(
        recipient_user_id, title, body, req, event_type="pd_action_required"
    ) -> None:
        """Route through the central service, not a raw insert.

        This wrote `Notification.objects.create` directly with no
        `source_event_type`, so the dedupe index could never match it and
        `resolve_condition` could never close it. A request that bounced
        between stages left a permanent stack of unread rows, each promoted to
        "urgent" by the 48-hour escalation job — which is how HR's urgent
        count stopped meaning anything (2026-08-20 HR audit).
        """
        if not recipient_user_id:
            return
        try:
            from apps.notifications.services import WorkflowNotificationService

            WorkflowNotificationService.trigger(
                event_type=event_type,
                category="professional_development",
                priority="high",
                title=title,
                body=body,
                context_type="pd_request",
                context_id=req.id,
                recipients=[recipient_user_id],
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
                context_type="professional_development",
                context_id=req.id,
                subject=subject,
                body=body,
                recipient_ids=[req.owner_user_id],
                category="professional_development",
                priority="high",
                sender_id=principal.user_id,
            )
        except Exception:  # noqa: BLE001
            pass
