"""Professional Development health checks (mandate §36) — every count is
derived live from real workflow rows; consumed by
apps.system_health.services.report(). Each check guards one of the
mandate's non-negotiables (no certificate → no complete, no funded course
closed without NetSuite Expense ID, no self-approval/self-signoff leak) so a
violation here means a bug slipped past the service-layer guards, not that
the guard is missing."""

from __future__ import annotations


from django.utils import timezone


def _check(key, label, items, severity, fix):
    return {
        "key": key,
        "label": label,
        "count": len(items),
        "severity": severity if items else "ok",
        "items": items[:10],
        "fix": fix,
    }


def pd_health_checks() -> dict:
    from apps.professional_development.models import (
        FUNDED_TYPES,
        PDStatus,
        ProfessionalDevelopmentDisbursement,
        ProfessionalDevelopmentFundRequest,
        ProfessionalDevelopmentRequest,
    )

    now = timezone.now()
    today = now.date()

    closed = ProfessionalDevelopmentRequest.objects.filter(
        status=PDStatus.COMPLETED_CLOSED
    )

    # 1. Closed without an uploaded certificate.
    closed_no_cert = [
        f"{r.staff_name} — {r.course_name}"
        for r in closed
        if not r.certificates.filter(status="uploaded").exists()
    ]

    # 2. Closed + funded without a NetSuite Expense ID.
    closed_funded_no_netsuite = [
        f"{r.staff_name} — {r.course_name}"
        for r in closed.filter(funding_type__in=FUNDED_TYPES)
        if not (r.accountability_netsuite_id or "").strip()
    ]

    # 3. Self-signoff leak — signed off by the record's own owner.
    self_signoff = [
        f"{r.staff_name} — {r.course_name}"
        for r in closed.exclude(signed_off_by__isnull=True)
        if r.signed_off_by == r.owner_user_id
    ]

    # 4. Self-approval leak — supervisor stage approved by the owner.
    supervisor_reviewed = ProfessionalDevelopmentRequest.objects.exclude(
        supervisor_reviewed_by__isnull=True
    )
    self_supervisor_approval = [
        f"{r.staff_name} — {r.course_name}"
        for r in supervisor_reviewed
        if r.supervisor_reviewed_by == r.owner_user_id
    ]

    # 5. Self-approval leak — HR stage approved by the owner.
    hr_reviewed = ProfessionalDevelopmentRequest.objects.exclude(
        hr_reviewed_by__isnull=True
    )
    self_hr_approval = [
        f"{r.staff_name} — {r.course_name}"
        for r in hr_reviewed
        if r.hr_reviewed_by == r.owner_user_id
    ]

    # 6. Self-disbursement leak — the Accountant who disbursed is the owner.
    self_disbursement = [
        f"{d.fund_request.request.staff_name} — {d.fund_request.request.course_name}"
        for d in ProfessionalDevelopmentDisbursement.objects.select_related(
            "fund_request__request"
        )
        if d.disbursed_by == d.fund_request.request.owner_user_id
    ]

    # 7. Funded + approved-or-later with no PD fund request on record.
    approved_or_later = ProfessionalDevelopmentRequest.objects.filter(
        funding_type__in=FUNDED_TYPES,
        status__in=(
            PDStatus.APPROVED_PENDING_FUNDING,
            PDStatus.DISBURSED,
            PDStatus.ENROLLMENT_PENDING,
            PDStatus.ENROLLMENT_CONFIRMED,
            PDStatus.IN_PROGRESS,
            PDStatus.ENDED,
            PDStatus.MARKED_COMPLETE,
            PDStatus.CERTIFICATE_UPLOADED,
            PDStatus.BAMBOOHR_CONFIRMED,
            PDStatus.ACCOUNTABILITY_SUBMITTED,
            PDStatus.AWAITING_HR_SIGNOFF,
            PDStatus.COMPLETED_CLOSED,
        ),
    ).exclude(
        id__in=ProfessionalDevelopmentFundRequest.objects.values_list(
            "request_id", flat=True
        )
    )
    missing_fund_request = [
        f"{r.staff_name} — {r.course_name}" for r in approved_or_later
    ]

    # 8. In-person/hybrid, submitted-or-later, with zero uploaded evidence.
    submitted_or_later_statuses = [
        s for s in PDStatus.values if s not in (PDStatus.DRAFT,)
    ]
    evidence_required = ProfessionalDevelopmentRequest.objects.filter(
        course_type__in=("in_person", "hybrid"), status__in=submitted_or_later_statuses
    )
    missing_evidence = [
        f"{r.staff_name} — {r.course_name}"
        for r in evidence_required
        if not r.evidence_files.filter(status="uploaded").exists()
    ]

    # 9. Course ended but not marked complete for more than 30 days.
    stale_ended = [
        f"{r.staff_name} — {r.course_name} ({(today - r.end_date).days}d)"
        for r in ProfessionalDevelopmentRequest.objects.filter(status=PDStatus.ENDED)
        if (today - r.end_date).days > 30
    ]

    # 10. Certificate uploaded but BambooHR not confirmed for more than 14 days.
    stale_bamboohr = [
        f"{r.staff_name} — {r.course_name} ({(now - r.updated_at).days}d)"
        for r in ProfessionalDevelopmentRequest.objects.filter(
            status=PDStatus.CERTIFICATE_UPLOADED
        )
        if (now - r.updated_at).days > 14
    ]

    # 11. BambooHR confirmed (funded) but accountability not submitted for more than 14 days.
    stale_accountability = [
        f"{r.staff_name} — {r.course_name} ({(now - r.updated_at).days}d)"
        for r in ProfessionalDevelopmentRequest.objects.filter(
            status=PDStatus.BAMBOOHR_CONFIRMED, funding_type__in=FUNDED_TYPES
        )
        if (now - r.updated_at).days > 14
    ]

    # 12. Awaiting HR sign-off for more than 14 days.
    stale_signoff = [
        f"{r.staff_name} — {r.course_name} ({(now - r.updated_at).days}d)"
        for r in ProfessionalDevelopmentRequest.objects.filter(
            status=PDStatus.AWAITING_HR_SIGNOFF
        )
        if (now - r.updated_at).days > 14
    ]

    # 13. Calendar blocks left behind by a request that is no longer active.
    inactive_with_block = (
        ProfessionalDevelopmentRequest.objects.filter(
            status__in=(PDStatus.REJECTED, PDStatus.CANCELLED, PDStatus.WITHDRAWN)
        )
        .exclude(calendar_block_id__isnull=True)
        .exclude(calendar_block_id="")
    )
    orphaned_blocks = [f"{r.staff_name} — {r.course_name}" for r in inactive_with_block]

    # 14. Draft requests untouched for more than 90 days (abandoned).
    stale_drafts = [
        f"{r.staff_name or 'Unnamed'} — {r.course_name or 'Untitled'} ({(now - r.updated_at).days}d)"
        for r in ProfessionalDevelopmentRequest.objects.filter(status=PDStatus.DRAFT)
        if (now - r.updated_at).days > 90
    ]

    # 15. Allocation rows with a negative annual allocation (data integrity).
    from apps.professional_development.models import ProfessionalDevelopmentAllocation

    negative_allocations = [
        f"{a.staff_id} FY{a.fy}"
        for a in ProfessionalDevelopmentAllocation.objects.filter(
            annual_allocation__lt=0
        )
    ]

    return {
        "checks": [
            _check(
                "pd_closed_no_certificate",
                "Closed PD records missing a certificate",
                closed_no_cert,
                "blocking",
                "A course cannot be signed off without an uploaded certificate — investigate how this closed.",
            ),
            _check(
                "pd_closed_funded_no_netsuite",
                "Closed funded PD records missing a NetSuite Expense ID",
                closed_funded_no_netsuite,
                "blocking",
                "Non-negotiable: enter the NetSuite Expense ID before any funded course can close.",
            ),
            _check(
                "pd_self_signoff",
                "PD records signed off by their own owner",
                self_signoff,
                "blocking",
                "HR must never sign off their own Professional Development record — reassign to an independent reviewer.",
            ),
            _check(
                "pd_self_supervisor_approval",
                "PD records approved by their own supervisor stage",
                self_supervisor_approval,
                "blocking",
                "No manager may approve their own request — check the routing assignment.",
            ),
            _check(
                "pd_self_hr_approval",
                "PD records approved by HR for themselves",
                self_hr_approval,
                "blocking",
                "HR must never approve its own staff's request — route to an independent HR/leadership reviewer.",
            ),
            _check(
                "pd_self_disbursement",
                "PD funds disbursed by the requester's own account",
                self_disbursement,
                "blocking",
                "An Accountant must never disburse their own Professional Development funding.",
            ),
            _check(
                "pd_missing_fund_request",
                "Funded PD requests with no dedicated fund request",
                missing_fund_request,
                "blocking",
                "Every approved funded course must have a PD fund request — funding must never bypass the dedicated PD ledger.",
            ),
            _check(
                "pd_missing_evidence",
                "In-person/hybrid PD requests missing enrollment evidence",
                missing_evidence,
                "blocking",
                "In-person and hybrid courses require an uploaded admission/enrollment letter before submission.",
            ),
            _check(
                "pd_stale_ended",
                "Courses ended over 30 days without being marked complete",
                stale_ended,
                "warning",
                "Follow up with the employee to mark the course complete and start the closure sequence.",
            ),
            _check(
                "pd_stale_bamboohr",
                "Certificates uploaded over 14 days without BambooHR confirmation",
                stale_bamboohr,
                "warning",
                "Remind the employee to confirm the BambooHR upload.",
            ),
            _check(
                "pd_stale_accountability",
                "Funded courses awaiting accountability over 14 days",
                stale_accountability,
                "warning",
                "Remind the employee to submit accountability and the NetSuite Expense ID.",
            ),
            _check(
                "pd_stale_signoff",
                "Records awaiting HR sign-off over 14 days",
                stale_signoff,
                "warning",
                "HR should clear the sign-off queue — check the HR Sign-Off Queue.",
            ),
            _check(
                "pd_orphaned_calendar_blocks",
                "Calendar blocks left behind by an inactive PD request",
                orphaned_blocks,
                "warning",
                "Clear the PD calendar block for rejected/cancelled/withdrawn requests.",
            ),
            _check(
                "pd_stale_drafts",
                "Draft PD requests untouched over 90 days",
                stale_drafts,
                "warning",
                "Prompt the employee to submit or cancel the abandoned draft.",
            ),
            _check(
                "pd_negative_allocation",
                "PD allocations with a negative annual amount",
                negative_allocations,
                "blocking",
                "A negative annual allocation is a data-entry error — correct the allocation record.",
            ),
        ],
    }


__all__ = ["pd_health_checks"]
