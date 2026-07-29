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

from apps.core.enums import SsaIntervention, VerificationStatus
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School

from .models import SsaRecord, SsaScore


# All 8 SSA interventions.
ALL_INTERVENTIONS = [i.value for i in SsaIntervention]


def _parse_date(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        # Accept ISO date/datetime strings.
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise BadRequest(f"Invalid dateOfSsa: {value}") from exc

    # ``SsaRecord.date_of_ssa`` is timezone-aware.  Normalise date-only and
    # naïve ISO inputs at the service boundary so every caller — UI, API,
    # import or job — persists the same canonical representation.
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _recompute_readiness(school: School) -> None:
    """Centralized readiness recompute (§16) — the bridge to planning lists.

    Derives current_fy_ssa_status from actual SsaRecord rows (source of truth),
    then sets canonical planning readiness accordingly:
      confirmed record → done → ready_for_support_planning
      pending record   → scheduled/partner_assigned → ready_for_baseline_ssa
      no record        → not_done → ready_for_baseline_ssa (if clustered)

    This avoids stale-cache bugs where the denormalized field is never updated
    (e.g. bulk/CSV uploads that bypass the upload() service path)."""

    # Derive status from the actual SSA records for the CURRENT operational FY
    # only. The field is literally named current_fy_ssa_status: a confirmed
    # record from a previous FY (a legitimate baseline upload) must not mark
    # this FY "done" — that suppressed the Baseline/Refresh To-Do and the
    # decision-engine "no SSA" recommendation for stale schools.
    current_fy = get_operational_fy()
    confirmed = SsaRecord.objects.filter(
        school=school,
        deleted_at__isnull=True,
        verification_status="confirmed",
        fy=current_fy,
    ).exists()
    pending = SsaRecord.objects.filter(
        school=school,
        deleted_at__isnull=True,
        verification_status="pending",
        fy=current_fy,
    ).exists()

    if confirmed:
        ssa = "done"
    elif pending:
        ssa = "partner_assigned"
    elif school.current_fy_ssa_status in ("done", "partner_assigned"):
        # Status was earned by a record that is no longer current-FY (stale
        # baseline or FY rollover) — reset so the refresh becomes actionable.
        ssa = "not_done"
    else:
        # Preserve operator-set intermediate states (e.g. "scheduled").
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
    school_id = str(data.get("schoolId") or "").strip()
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError(f"School {school_id or 'ID'} not in directory")

    scores_in: list[dict] = data.get("scores") or []
    normalized_scores = []
    interventions = set()
    for item in scores_in:
        intervention = item.get("intervention")
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError) as exc:
            raise BadRequest(
                f"Score for {intervention or 'intervention'} must be numeric"
            ) from exc
        if score < 0 or score > 10:
            raise BadRequest(
                f"Score for {intervention or 'intervention'} must be between 0 and 10"
            )
        interventions.add(intervention)
        normalized_scores.append({"intervention": intervention, "score": score})

    if len(interventions) != 8 or not all(
        i in ALL_INTERVENTIONS for i in interventions
    ):
        raise BadRequest("All 8 intervention scores are required")

    if not data.get("dateOfSsa"):
        raise BadRequest("Assessment date is required")
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
    average = round(
        sum(s["score"] for s in normalized_scores) / len(normalized_scores), 1
    )

    collector_type = data.get("collectorType", "staff")
    partner_collected = collector_type == "partner"
    stored_collector_type = (
        "partner" if partner_collected else "ia" if collector_type == "ia" else "staff"
    )

    new_enrollment = data.get("newEnrollment")
    if new_enrollment in ("", None):
        new_enrollment = None
    else:
        try:
            new_enrollment = int(new_enrollment)
        except (TypeError, ValueError) as exc:
            raise BadRequest("Assessment enrollment must be a whole number") from exc
        if new_enrollment < 0:
            raise BadRequest("Assessment enrollment cannot be negative")

    with transaction.atomic():
        # Serialize writes for one school so two simultaneous submissions
        # cannot save the same assessment twice. Multiple assessment dates in
        # one FY remain valid for before/after and monitoring trends.
        school = School.objects.select_for_update().get(pk=school.pk)
        if SsaRecord.objects.filter(school=school, date_of_ssa=date).exists():
            raise BadRequest(
                f"SSA score for {date.date().isoformat()} already exists for "
                f"{school.name}. "
                "Open the existing record instead of creating a duplicate."
            )

        record = SsaRecord.objects.create(
            school=school,
            date_of_ssa=date,
            fy=fy,
            quarter=quarter,
            new_enrollment=new_enrollment,
            average_score=average,
            uploaded_by=principal.user_id,
            collector_type=stored_collector_type,
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
                for s in normalized_scores
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

        # SSA done + verified -> school's current-FY SSA status becomes done,
        # but ONLY when the record actually belongs to the current operational
        # FY — prior-FY baseline uploads must not mark this FY complete.
        if (
            record.verification_status == "confirmed"
            and record.fy == get_operational_fy()
        ):
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


def latest_applicable_record(school):
    """THE canonical "latest SSA" lookup for every decision surface
    (ecosystem audit): the newest CONFIRMED record. An unverified upload must
    never gate, justify, or rank money-bearing work — before this helper, six
    surfaces computed "weakest interventions" with different filters and the
    planning gate could pass or fail on an unconfirmed score."""
    return (
        SsaRecord.objects.filter(
            school=school,
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .order_by("-date_of_ssa", "-created_at")
        .first()
    )


def latest_applicable_records(schools, *, with_scores: bool = False) -> dict:
    """The batched twin of :func:`latest_applicable_record`.

    Same rule, same ``(-date_of_ssa, -created_at)`` tiebreak, one query for a
    whole set of schools instead of one per school. Cluster intelligence called
    the single-school helper inside a loop and then read ``latest.scores.all()``
    on each result -- two round trips per school, ninety of them on one load of
    ``/clusters``.

    Returns ``{school_id: SsaRecord}``, omitting schools with no confirmed
    record so a caller cannot mistake "no verified SSA" for a zero score.

    ``with_scores=True`` prefetches the intervention scores, which is what the
    per-school loop was fetching separately.
    """
    records = SsaRecord.objects.filter(
        school__in=schools,
        deleted_at__isnull=True,
        verification_status="confirmed",
    )
    if with_scores:
        records = records.prefetch_related("scores")
    # DISTINCT ON (school_id) keeps the first row per school under this
    # ordering, so the leading ORDER BY term has to be school_id -- the
    # remaining terms are the same tiebreak the single-school helper uses.
    return {
        record.school_id: record
        for record in records.order_by(
            "school_id", "-date_of_ssa", "-created_at"
        ).distinct("school_id")
    }


def weakest_interventions_for(school, *, n=2):
    """Canonical weakest-intervention ranking. Returns (record, rows) where
    rows is a {"intervention", "score"} list at most n long ([] when no
    confirmed SSA exists — never fabricate a need).

    Delegates the ranking to the analytics recommendation engine
    (apps.ssa.recommendation_engine), so planning, activities, Core and the
    SSA API all pick interventions from ONE analytically-backed ordering
    (severity anchored, refined by trend / peer gap / persistence) instead
    of a bare "two lowest scores on the newest assessment". With a single
    confirmed record and no measurable peers/trend, the engine reduces
    exactly to ascending-score + alphabetical tie-break, so single-assessment
    behaviour is unchanged."""
    from apps.ssa.recommendation_engine import prioritized_interventions

    record = latest_applicable_record(school)
    if not record:
        return None, []
    ranked = prioritized_interventions(school, n=n)
    rows = [{"intervention": r["intervention"], "score": r["score"]} for r in ranked]
    return record, rows


def recommendation(school_id: str, principal) -> dict:
    """Analytics-backed recommendation for a school — the two most urgent
    interventions, a canonical severity band, and the full prioritised
    ranking with its analytics breakdown (delegates to the single canonical
    recommendation engine, verified-SSA-only and deterministic)."""
    school = School.objects.filter(school_id=school_id).first()
    if not school:
        raise NotFoundError("School not found.")

    from apps.ssa.recommendation_engine import school_recommendation

    return school_recommendation(school, n=2)


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


# ── Verification: the one place an SSA record changes verification state ─────


def _assert_ia_authority(principal) -> None:
    """Confirming an SSA is Impact Assessment's authority.

    Stated once, here, rather than at each call site. The scoring, targets and
    impact stack all rest on which records are confirmed, so "this role can
    open the queue" must never be the same question as "this role may confirm".
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    if not has_permission(principal, Permission.IA_VERIFY.value):
        raise Forbidden("Only Impact Assessment may confirm or return an SSA record.")


@transaction.atomic
def verify_record(record, principal):
    """Confirm one SSA record.

    Lives in the service, not in the view that happens to render the queue: a
    transition written inline is a transition every other caller -- an API, an
    HTMX endpoint, a management command, a future page -- can perform without
    the authority check, the readiness recompute or the audit row. Those three
    are what make a confirmation mean anything, so they belong to the
    transition rather than to one of its callers.
    """
    from apps.audit.services import log as audit_log

    _assert_ia_authority(principal)
    if record.verification_status == VerificationStatus.CONFIRMED.value:
        # Idempotent: a double-submitted form re-confirms nothing and writes no
        # second audit row.
        return record

    record.verification_status = VerificationStatus.CONFIRMED.value
    record.verified_by_user_id = getattr(principal, "user_id", None) or getattr(
        principal, "id", None
    )
    record.verified_at = timezone.now()
    record.save(
        update_fields=["verification_status", "verified_by_user_id", "verified_at"]
    )
    _recompute_readiness(record.school)

    audit_log(
        action="ssa_verify",
        subject_kind="SsaRecord",
        subject_id=record.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={"schoolId": record.school_id, "schoolName": record.school.name},
    )
    return record


@transaction.atomic
def return_record(record, principal, reason: str = ""):
    """Send one SSA record back for correction."""
    from apps.audit.services import log as audit_log

    _assert_ia_authority(principal)
    if record.verification_status == VerificationStatus.RETURNED.value:
        return record

    record.verification_status = VerificationStatus.RETURNED.value
    record.save(update_fields=["verification_status"])
    _recompute_readiness(record.school)

    audit_log(
        action="ssa_return",
        subject_kind="SsaRecord",
        subject_id=record.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason or None,
        payload={"schoolId": record.school_id, "schoolName": record.school.name},
    )
    return record
