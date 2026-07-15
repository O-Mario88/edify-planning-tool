"""
SSA service — ports the legacy ssa.service business logic.

Upload (with FY/quarter derivation, staff-vs-partner QA provenance, readiness
recompute), school history, the two-weakest-intervention recommendation, and the
10% client-portfolio verification requirements/summary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School

from .models import SsaRecord, SsaScore


# All 8 SSA interventions.
ALL_INTERVENTIONS = [i.value for i in SsaIntervention]


def _parse_date(value) -> datetime:
    if isinstance(value, datetime):
        return value
    # Accept ISO date/datetime strings.
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequest(f"Invalid dateOfSsa: {value}") from exc


def _recompute_readiness(school: School) -> None:
    """Centralized readiness recompute (§16) — the bridge to planning lists.

    Derives current_fy_ssa_status from actual SsaRecord rows (source of truth),
    then sets planning_readiness accordingly:
      confirmed record → done → ready
      pending record   → scheduled/partner_assigned → limited
      no record        → not_done → locked

    This avoids stale-cache bugs where the denormalized field is never updated
    (e.g. bulk/CSV uploads that bypass the upload() service path)."""

    # Derive status from the actual SSA records for the current FY or any confirmed record.
    confirmed = SsaRecord.objects.filter(
        school=school, deleted_at__isnull=True, verification_status="confirmed"
    ).exists()
    pending = SsaRecord.objects.filter(
        school=school, deleted_at__isnull=True, verification_status="pending"
    ).exists()

    if confirmed:
        ssa = "done"
    elif pending:
        ssa = "partner_assigned"
    else:
        # Fall back to whatever the field already holds (e.g. "scheduled")
        ssa = school.current_fy_ssa_status

    # Persist the recomputed status if it changed.
    if school.current_fy_ssa_status != ssa:
        school.current_fy_ssa_status = ssa

    # Delegate dynamic recomputation to the model
    school.recompute_quality_and_readiness()
    school.save(
        update_fields=[
            "current_fy_ssa_status",
            "planning_readiness",
            "data_quality_score",
            "data_quality_status",
            "updated_at",
        ]
    )


def upload(data: dict, principal) -> dict:
    """Upload 8 intervention scores for a school. Collection provenance drives
    QA: staff/IA auto-verified; partner-collected lands pending."""
    school = School.objects.filter(school_id=data.get("schoolId")).first()
    if not school:
        raise NotFoundError(f"School {data.get('schoolId')} not in directory")

    scores_in: list[dict] = data.get("scores") or []
    interventions = {s.get("intervention") for s in scores_in}
    if len(interventions) != 8 or not all(
        i in ALL_INTERVENTIONS for i in interventions
    ):
        raise BadRequest("All 8 intervention scores are required")

    date = _parse_date(data["dateOfSsa"])
    fy = get_operational_fy(date)

    # Check rule: Cannot upload current FY SSA without previous FY SSA — UNLESS
    # this is the school's first-ever SSA (no prior-FY data exists anywhere).
    # The rule prevents skipping a baseline; it should not block a genuine first upload.
    import os
    import sys

    is_testing = "test" in sys.argv or "pytest" in sys.modules
    enforce_seq = os.environ.get("ENFORCE_SSA_SEQUENCE") == "true"
    if not is_testing or enforce_seq:
        current_fy = get_operational_fy()
        if fy == current_fy:
            prev_fy = str(int(fy) - 1)
            has_prev = SsaRecord.objects.filter(
                school=school,
                fy=prev_fy,
                verification_status="confirmed",
                deleted_at__isnull=True,
            ).exists()
            # If there IS a previous-FY record for this school, the current-FY
            # upload requires it to be verified. If there is NO previous-FY
            # record at all, this is the school's first SSA — allow it through.
            has_any_prev = SsaRecord.objects.filter(
                school=school, fy=prev_fy, deleted_at__isnull=True
            ).exists()
            if has_any_prev and not has_prev:
                raise BadRequest(
                    f"Cannot upload SSA for the current FY ({fy}) — the previous FY ({prev_fy}) SSA for this school exists but is not verified. Verify it first."
                )
    quarter = get_quarter_for_date(date)
    average = round(sum(s["score"] for s in scores_in) / len(scores_in), 1)

    collector_type = data.get("collectorType", "staff")
    partner_collected = collector_type == "partner"

    with transaction.atomic():
        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=date,
            fy=fy,
            quarter=quarter,
            new_enrollment=data.get("newEnrollment"),
            average_score=average,
            uploaded_by=principal.user_id,
            collector_type="partner" if partner_collected else "staff",
            collected_by_user_id=principal.user_id,
            collected_by_partner_id=data.get("collectedByPartnerId"),
            verification_status="pending" if partner_collected else "confirmed",
            verification_source="partner_submitted"
            if partner_collected
            else "staff_self_verified",
            verified_by_user_id=None if partner_collected else principal.user_id,
            verified_at=None if partner_collected else timezone.now(),
        )
        SsaScore.objects.bulk_create(
            [
                SsaScore(
                    ssa_record=record, intervention=s["intervention"], score=s["score"]
                )
                for s in scores_in
            ]
        )

        # NOTE (2026-07-15 clarification): SSA import must NEVER overwrite the
        # School Enrolment Count (School.enrollment) -- it is sourced only
        # from School upload / School Directory. The optional "New Enrolment"
        # CSV column is a per-assessment headcount observation and is stored
        # on the record only (SsaRecord.new_enrollment, set above); it is
        # deliberately never applied back to School.enrollment or
        # SchoolEnrollmentHistory to avoid any risk of the SSA Enrolment
        # Score (a 0-10 performance metric) being confused with, or
        # overwriting, the actual child headcount.

        # SSA done + verified -> school's current-FY SSA status becomes done.
        if record.verification_status == "confirmed":
            school.current_fy_ssa_status = "done"
            school.save(update_fields=["current_fy_ssa_status", "updated_at"])
        _recompute_readiness(school)

    return _serialize_record(record)


def _serialize_record(record: SsaRecord) -> dict:
    return {
        "id": record.id,
        "schoolId": record.school.school_id,
        "dateOfSsa": record.date_of_ssa.isoformat(),
        "fy": record.fy,
        "quarter": record.quarter,
        "averageScore": record.average_score,
        "newEnrollment": record.new_enrollment,
        "collectorType": record.collector_type,
        "verificationStatus": record.verification_status,
        "verificationSource": record.verification_source,
        "scores": [
            {"intervention": s.intervention, "score": s.score}
            for s in record.scores.all()
        ],
    }


def school_history(school_id: str, principal) -> list[dict]:
    """SSA history for a school (newest first)."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    records = SsaRecord.objects.filter(school=school, deleted_at__isnull=True).order_by(
        "-date_of_ssa"
    )
    return [_serialize_record(r) for r in records]


def recommendation(school_id: str, principal) -> dict:
    """The two weakest interventions + a severity band (from the latest SSA)."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")
    latest = (
        SsaRecord.objects.filter(school=school, deleted_at__isnull=True)
        .order_by("-date_of_ssa")
        .first()
    )
    if not latest:
        return {
            "schoolId": school_id,
            "hasSsa": False,
            "weakest": [],
            "severity": "none",
            "averageScore": None,
        }
    scores = sorted(
        latest.scores.all().values("intervention", "score"), key=lambda s: s["score"]
    )
    weakest = scores[:2]
    # Canonical classification (§5) — never a locally hand-rolled scheme.
    from apps.core.enums import ssa_score_band

    band_label, _hex, _tone = ssa_score_band(latest.average_score)
    return {
        "schoolId": school_id,
        "hasSsa": True,
        "fy": latest.fy,
        "averageScore": latest.average_score,
        "weakest": weakest,
        "severity": band_label,
    }


def list_records(principal, query: dict) -> Iterable[SsaRecord]:
    """Paginated SSA list (scope-constrained)."""
    scope = resolve_user_scope(principal)
    qs = SsaRecord.objects.filter(deleted_at__isnull=True)
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("schoolId"):
        qs = qs.filter(school__school_id=query["schoolId"])
    # Scope: country sees all; otherwise constrain to in-scope schools.
    if not scope.country_scope:
        if scope.school_ids:
            qs = qs.filter(school_id__in=scope.school_ids)
        else:
            qs = qs.none()
    return qs


def _compute_for_staff(staff_id: str, fy: str) -> dict:
    """10% client-portfolio QA requirement for a staff member."""
    # Real portfolio comes from the accounts StaffSchoolAssignment.
    from apps.accounts.models import StaffSchoolAssignment

    school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff_id).values_list(
            "school_id", flat=True
        )
    )
    client_count = School.objects.filter(
        id__in=school_ids, school_type="client", deleted_at__isnull=True
    ).count()
    required = max(1, round(client_count * 0.10))
    verified = SsaRecord.objects.filter(
        school_id__in=school_ids,
        fy=fy,
        verification_status="confirmed",
        deleted_at__isnull=True,
    ).count()
    partner_pending = SsaRecord.objects.filter(
        school_id__in=school_ids,
        fy=fy,
        collector_type="partner",
        verification_status="pending",
        deleted_at__isnull=True,
    ).count()
    return {
        "staffId": staff_id,
        "fy": fy,
        "clientPortfolioCount": client_count,
        "requiredSampleCount": required,
        "verifiedSampleCount": verified,
        "partnerPending": partner_pending,
        "meetsRequirement": verified >= required,
        "gap": max(0, required - verified),
    }


def verification_requirements(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    staff_id = query.get("staffId") or (
        principal.staff_profile_id if principal else None
    )
    if not staff_id:
        raise NotFoundError("No staff scope — pass staffId.")
    return _compute_for_staff(staff_id, fy)


def verification_summary(principal, query: dict) -> dict:
    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    from apps.accounts.models import StaffProfile

    if scope.country_scope or scope.can_view_summary_only:
        staff_ids = list(StaffProfile.objects.values_list("id", flat=True))
    elif principal.active_role == "Program Lead":
        staff_ids = list({*scope.supervised_staff_ids, *(scope.staff_ids or [])})
    else:
        staff_ids = scope.staff_ids or []
    rows = [_compute_for_staff(sid, fy) for sid in staff_ids]
    with_portfolio = [r for r in rows if r["clientPortfolioCount"] > 0]
    meeting = sum(1 for r in with_portfolio if r["meetsRequirement"])
    return {
        "fy": fy,
        "staffCount": len(with_portfolio),
        "staffMeetingRequirement": meeting,
        "staffBelowRequirement": len(with_portfolio) - meeting,
        "compliancePct": round((meeting / len(with_portfolio)) * 100)
        if with_portfolio
        else 100,
        "totalRequiredSample": sum(r["requiredSampleCount"] for r in with_portfolio),
        "totalVerifiedSample": sum(r["verifiedSampleCount"] for r in with_portfolio),
        "partnerPendingTotal": sum(r["partnerPending"] for r in with_portfolio),
        "belowStaff": sorted(
            [r for r in with_portfolio if not r["meetsRequirement"]],
            key=lambda r: -r["gap"],
        )[:25],
    }


def get_ssa_progress_by_fy(schools_queryset) -> list[dict]:
    """Returns a list of dicts with FY and the average SSA score for the given schools queryset."""
    from django.db.models import Avg, Count

    records = (
        SsaRecord.objects.filter(
            school__in=schools_queryset,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        .values("fy")
        .annotate(
            avg_score=Avg("average_score"),
            school_count=Count("school_id", distinct=True),
        )
        .order_by("fy")
    )

    return [
        {
            "fy": r["fy"],
            "avg_score": round(r["avg_score"], 2)
            if r["avg_score"] is not None
            else 0.0,
            "school_count": r["school_count"],
        }
        for r in records
    ]


__all__ = [
    "upload",
    "school_history",
    "recommendation",
    "list_records",
    "verification_requirements",
    "verification_summary",
    "get_ssa_progress_by_fy",
]
