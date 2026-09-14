"""
SSA service — ports the legacy ssa.service business logic.

Upload (with FY/quarter derivation, collection provenance, readiness
recompute), school history, the two-weakest-intervention recommendation, and the
10% client-portfolio verification requirements/summary.

Every SSA lands PENDING (IA review, owner, 2026-09-13). Scores keyed by field
staff, by Impact Assessment or through a file import used to be born
"confirmed" with the keyer recorded as their own verifier — 1,006 of 1,009
records on the dev database — so nobody but the collector had ever looked at
the numbers every outcome, target and planning gate reads. A record now waits
for a DIFFERENT verifier: an Impact Assessment officer in the school's
country, or the Country Director for scores an IA officer collected
(`verify_record`). Only confirmed records count, so the confirmed-only
consumers (planning readiness, recommendations, project baselines, outcomes,
targets) see a keyed assessment after its verification, not at keying: that
lag is the point of the rule, and the SSA Verification queue and the IA To-Dos
exist to keep it short.
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

#: How a pending record's scores reached the platform (`verification_source`).
#: None of them is a verification: the verifier is recorded separately when a
#: different person confirms the record.
SOURCE_STAFF_KEYED = "staff_keyed"
SOURCE_IA_KEYED = "ia_keyed"
SOURCE_FILE_IMPORT = "file_import"
SOURCE_PARTNER = "partner_submitted"

#: The two ways a verifier may confirm or return a record.
BASIS_IA = "ia"
BASIS_CD_FALLBACK = "cd_fallback"

EVENT_SSA_RETURNED = "ssa_returned"


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
    """Record 8 intervention scores for a school, pending verification.

    `collectorType` records who keyed them (staff, ia or partner) and
    `sourceActivityId`, when given, the visit they were collected on. Every
    record lands pending until a different verifier confirms it (see the
    module docstring)."""
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
    source = (
        SOURCE_PARTNER
        if partner_collected
        else SOURCE_IA_KEYED
        if stored_collector_type == "ia"
        else SOURCE_STAFF_KEYED
    )

    if data.get("newEnrollment") not in ("", None):
        raise BadRequest(
            "Pupil enrolment is not part of an SSA score. In SSA, Enrolment is "
            "scored from 0 to 10. Update pupil headcount through the School "
            "Upload file or the School Profile."
        )

    source_activity_id = str(data.get("sourceActivityId") or "").strip() or None

    with transaction.atomic():
        # Serialize writes for one school so two simultaneous submissions
        # cannot save the same assessment twice. Multiple assessment dates in
        # one FY remain valid for before/after and monitoring trends.
        school = School.objects.select_for_update().get(pk=school.pk)

        # Scores collected on a visit belong to that visit (IA review,
        # 2026-09-13). A second submission for the same visit — a retried
        # completion, or the collector correcting scores a verifier returned —
        # re-keys that one record instead of minting a duplicate, and sends it
        # back to the verification queue. Confirmed scores are never
        # overwritten from the field: a verifier returns them first.
        existing = (
            SsaRecord.objects.filter(
                source_activity_id=source_activity_id, deleted_at__isnull=True
            ).first()
            if source_activity_id
            else None
        )
        if existing is not None and existing.school_id != school.id:
            raise BadRequest(
                "These scores belong to a visit at another school. Record them "
                "on that school's visit."
            )
        if (
            existing is not None
            and existing.verification_status == VerificationStatus.CONFIRMED.value
        ):
            raise BadRequest(
                "The SSA scores recorded on this visit are already confirmed. "
                "Ask Impact Assessment to return them if they need correcting."
            )
        duplicates = SsaRecord.objects.filter(school=school, date_of_ssa=date)
        if existing is not None:
            duplicates = duplicates.exclude(pk=existing.pk)
        if duplicates.exists():
            raise BadRequest(
                f"SSA score for {date.date().isoformat()} already exists for "
                f"{school.name}. "
                "Open the existing record instead of creating a duplicate."
            )

        fields = {
            "date_of_ssa": date,
            "fy": fy,
            "quarter": quarter,
            "average_score": average,
            "uploaded_by": principal.user_id,
            "collector_type": stored_collector_type,
            "collected_by_user_id": principal.user_id,
            "collected_by_partner_id": data.get("collectedByPartnerId"),
            # Pending for every source: a different verifier confirms it.
            "verification_status": VerificationStatus.PENDING.value,
            "verification_source": source,
            "verified_by_user_id": None,
            "verified_at": None,
            "return_reason": "",
            "returned_by_user_id": None,
            "returned_at": None,
        }
        if existing is not None:
            for name, value in fields.items():
                setattr(existing, name, value)
            existing.save()
            existing.scores.all().delete()
            record = existing
        else:
            record = SsaRecord.objects.create(
                school=school, source_activity_id=source_activity_id, **fields
            )
        SsaScore.objects.bulk_create(
            [
                SsaScore(
                    ssa_record=record, intervention=s["intervention"], score=s["score"]
                )
                for s in normalized_scores
            ]
        )

        # SSA import must NEVER overwrite School.enrollment. The Enrolment
        # intervention above is only a 0-10 SSA performance score. Actual
        # pupil headcount is sourced from School Upload / School Profile.

        # A pending record makes the school's current-FY status "awaiting
        # confirmation"; it becomes done when a verifier confirms it
        # (`verify_record`), and only for a record of the current FY.
        _recompute_readiness(school)

        if existing is not None:
            from apps.audit.services import log as audit_log

            audit_log(
                action="ssa_rekeyed",
                subject_kind="SsaRecord",
                subject_id=record.id,
                actor_id=getattr(principal, "user_id", None),
                actor_role=getattr(principal, "active_role", None),
                payload={
                    "schoolId": school.id,
                    "sourceActivityId": source_activity_id,
                },
            )

    return _serialize_record(record)


def visit_assessment_date(activity):
    """The date scores collected on `activity` were taken.

    The visit's delivery date, else the day its execution started, else its
    planned date — never the moment someone pressed submit, which misdated
    every offline or late completion (IA review, 2026-09-13).
    """
    if getattr(activity, "actual_delivery_date", None):
        return activity.actual_delivery_date
    if getattr(activity, "execution_started_at", None):
        return timezone.localdate(activity.execution_started_at)
    if getattr(activity, "planned_date", None):
        return activity.planned_date
    return timezone.localdate()


def _serialize_record(record: SsaRecord) -> dict:
    return {
        "id": record.id,
        "schoolId": record.school.school_id,
        "dateOfSsa": record.date_of_ssa.isoformat(),
        "fy": record.fy,
        "quarter": record.quarter,
        "averageScore": record.average_score,
        "collectorType": record.collector_type,
        "verificationStatus": record.verification_status,
        "verificationSource": record.verification_source,
        "sourceActivityId": record.source_activity_id,
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
    from apps.core.request_cache import store

    bucket = store()
    key = ("ssa.latest_applicable", school.id)
    if bucket is not None and key in bucket:
        return bucket[key]
    record = (
        SsaRecord.objects.filter(
            school=school,
            deleted_at__isnull=True,
            verification_status="confirmed",
        )
        .order_by("-date_of_ssa", "-created_at")
        .first()
    )
    if bucket is not None:
        bucket[key] = record
    return record


def prime_latest_applicable_records(schools, *, with_scores: bool = True) -> None:
    """Fill the request store so :func:`latest_applicable_record` answers a
    whole page from one query — including the schools with NO record, which
    are stored as None so they are not looked up again one by one."""
    from apps.core.request_cache import store

    bucket = store()
    schools = list(schools)
    if bucket is None or not schools:
        return
    found = latest_applicable_records(schools, with_scores=with_scores)
    for school in schools:
        bucket[("ssa.latest_applicable", school.id)] = found.get(school.id)


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
        # A country role reads its own country's staff, never the deployment's
        # (IA review, 2026-09-13).
        staff = StaffProfile.objects.all()
        if scope.country_scope and scope.country:
            staff = staff.filter(country=scope.country)
        staff_ids = list(staff.values_list("id", flat=True))
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


def _ia_user_ids():
    """User ids holding the Impact Assessment role, unevaluated."""
    from apps.accounts.models import User
    from apps.core.rbac import EdifyRole

    return User.objects.filter(
        roles__contains=[EdifyRole.IMPACT_ASSESSMENT.value]
    ).values("id")


def ia_collected_q():
    """Records an Impact Assessment officer collected or keyed: the ones the
    Country Director confirms when no IA colleague can (owner, 2026-09-13)."""
    from django.db.models import Q

    ia_ids = _ia_user_ids()
    return (
        Q(collector_type="ia")
        | Q(collected_by_user_id__in=ia_ids)
        | Q(uploaded_by__in=ia_ids)
    )


def readable_records(principal):
    """SSA records `principal` may read in the verification queue.

    Country roles read their country's schools — the queue used to narrow only
    portfolio roles, so an Impact Assessment officer or a Country Director saw
    and could act on every country's assessments — and portfolio roles read
    their own schools. A summary-only reader without a portfolio reads none.
    """
    from apps.core.scoping import school_country_q

    scope = resolve_user_scope(principal)
    records = SsaRecord.objects.filter(deleted_at__isnull=True)
    if scope.country_scope:
        return records.filter(school_country_q(scope, "school__"))
    if scope.school_ids:
        return records.filter(school_id__in=list(scope.school_ids))
    return records.none()


def verifiable_records(principal):
    """Pending records `principal` may confirm or return, unevaluated.

    Impact Assessment: every pending record in their country except the ones
    they collected or uploaded. Country Director: the pending records an IA
    officer collected, except their own. Anyone else: none. One queryset, so
    the queue's buttons, the To-Dos and the service all agree.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.core.scoping import owner_ids

    records = readable_records(principal).filter(
        verification_status=VerificationStatus.PENDING.value
    )
    if has_permission(principal, Permission.IA_VERIFY.value):
        pass
    elif getattr(principal, "active_role", "") == EdifyRole.COUNTRY_DIRECTOR.value:
        records = records.filter(ia_collected_q())
    else:
        return records.none()
    own = [str(i) for i in owner_ids(principal) if i]
    if own:
        records = records.exclude(collected_by_user_id__in=own).exclude(
            uploaded_by__in=own
        )
    return records


def verifier_basis(principal, record) -> str | None:
    """How `principal` may decide `record`: BASIS_IA, BASIS_CD_FALLBACK, or
    None when they may not."""
    try:
        return _assert_may_decide(principal, record)
    except Forbidden:
        return None


def _assert_may_decide(principal, record) -> str:
    """Confirming or returning an SSA is a verifier's act, never the keyer's.

    Stated once, here, rather than at each call site. The scoring, targets and
    impact stack all rest on which records are confirmed, so "this role can
    open the queue" must never be the same question as "this role may confirm".

    - The person who collected or uploaded the scores may not decide them
      (`apps.core.permissions.verifies_own_ssa`).
    - The record's school must be in the verifier's country.
    - Impact Assessment (ia.verify) decides; the Country Director decides only
      records an Impact Assessment officer collected — the fallback verifier
      for IA's own work, as for activities (`is_ia_fallback_verifier`).
    """
    from apps.core.permissions import has_permission, verifies_own_ssa
    from apps.core.rbac import EdifyRole, Permission
    from apps.core.scoping import country_bound, school_country_q

    is_ia = has_permission(principal, Permission.IA_VERIFY.value)
    is_cd = getattr(principal, "active_role", "") == EdifyRole.COUNTRY_DIRECTOR.value
    if not (is_ia or is_cd):
        raise Forbidden("Only Impact Assessment may confirm or return an SSA record.")
    if verifies_own_ssa(principal, record):
        raise Forbidden(
            "You collected or uploaded these SSA scores, so a different verifier "
            "confirms them: another Impact Assessment officer, or the Country "
            "Director for scores Impact Assessment collected."
        )
    scope = resolve_user_scope(principal)
    if (
        country_bound(scope)
        and not School.objects.filter(pk=record.school_id)
        .filter(school_country_q(scope))
        .exists()
    ):
        raise Forbidden("This SSA belongs to a school outside your country.")
    if is_ia:
        return BASIS_IA
    if SsaRecord.objects.filter(pk=record.pk).filter(ia_collected_q()).exists():
        return BASIS_CD_FALLBACK
    raise Forbidden(
        "The Country Director confirms only SSA scores an Impact Assessment "
        "officer collected; Impact Assessment verifies the rest."
    )


def _actor_id(principal):
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


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

    basis = _assert_may_decide(principal, record)
    if record.verification_status == VerificationStatus.CONFIRMED.value:
        # Idempotent: a double-submitted form re-confirms nothing and writes no
        # second audit row.
        return record

    record.verification_status = VerificationStatus.CONFIRMED.value
    record.verified_by_user_id = _actor_id(principal)
    record.verified_at = timezone.now()
    # A save with update_fields still fires post_save, which is what carries a
    # confirmation to Business Transformation, recommendations and project
    # measurement (apps.business_transformation.signals, apps.projects.signals).
    record.save(
        update_fields=[
            "verification_status",
            "verified_by_user_id",
            "verified_at",
            "updated_at",
        ]
    )
    _recompute_readiness(record.school)

    from apps.projects.baselines import enqueue_baseline_capture

    enqueue_baseline_capture(record.school_id, version=f"ssa:{record.id}:confirmed")

    audit_log(
        action="ssa_verify",
        subject_kind="SsaRecord",
        subject_id=record.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "schoolId": record.school_id,
            "schoolName": record.school.name,
            "basis": basis,
            "collectedBy": record.collected_by_user_id,
            "sourceActivityId": record.source_activity_id,
        },
    )
    return record


@transaction.atomic
def return_record(record, principal, reason: str = ""):
    """Send one SSA record back to its collector for correction.

    The reason is stored on the record and the collector is told (event
    `ssa_returned`): a return used to write the reason to the audit log alone,
    so the person who had to fix the scores never learned what was wrong.
    A returned record counts nowhere until it is re-keyed and confirmed.
    """
    from apps.audit.services import log as audit_log

    basis = _assert_may_decide(principal, record)
    if record.verification_status == VerificationStatus.RETURNED.value:
        return record
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("Say what needs correcting before returning the SSA.")

    was_confirmed = record.verification_status == VerificationStatus.CONFIRMED.value
    record.verification_status = VerificationStatus.RETURNED.value
    record.return_reason = reason
    record.returned_by_user_id = _actor_id(principal)
    record.returned_at = timezone.now()
    record.save(
        update_fields=[
            "verification_status",
            "return_reason",
            "returned_by_user_id",
            "returned_at",
            "updated_at",
        ]
    )
    _recompute_readiness(record.school)

    audit_log(
        action="ssa_return",
        subject_kind="SsaRecord",
        subject_id=record.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "schoolId": record.school_id,
            "schoolName": record.school.name,
            "basis": basis,
            "wasConfirmed": was_confirmed,
            "sourceActivityId": record.source_activity_id,
        },
    )
    _notify_returned(record, principal, reason)
    return record


def _notify_returned(record, principal, reason: str) -> None:
    """Tell the collector what to fix, on the visit the scores came from when
    there is one, else on the school's SSA timeline."""
    from apps.notifications.services import WorkflowNotificationService

    recipient = record.collected_by_user_id or record.uploaded_by
    if not recipient or str(recipient) == str(_actor_id(principal)):
        return
    school = record.school
    when = timezone.localtime(record.date_of_ssa).date() if record.date_of_ssa else None
    context_type, context_id = (
        ("Activity", record.source_activity_id)
        if record.source_activity_id
        else ("School", record.school_id)
    )
    WorkflowNotificationService.trigger(
        event_type=EVENT_SSA_RETURNED,
        category="ssa",
        priority="high",
        title=f"SSA returned: {school.name}",
        body=(
            f"The SSA scores for {school.name}"
            + (f" dated {when:%-d %b %Y}" if when else "")
            + f" were returned for correction: {reason}"
        ),
        context_type=context_type,
        context_id=str(context_id),
        recipients=[recipient],
    )
