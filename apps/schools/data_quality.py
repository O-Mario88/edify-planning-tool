"""Data-quality reconciliation, duplicate detection and the nightly scan.

Phase 1b of the operations roadmap: automation quality is bounded by
directory quality, so the directory's defects become owned, durable,
self-closing exception queues *before* the autopilot builds on them.

Three rules govern this module:

- **Reconcile, never delete-and-recreate.** An issue that persists keeps
  its row and its ``assigned_to``; an issue whose condition cleared is
  resolved with a timestamp; only genuinely new conditions create rows.
  Identity is ``DataQualityIssue.condition_key`` (the TeamAction pattern),
  DB-enforced unique among open rows.
- **Detection writes facts, people decide.** The duplicate detector
  proposes ``SchoolDuplicateCandidate`` pairs and flags ``potential`` —
  resolution stays with the humans holding SCHOOL_RESOLVE_DUPLICATE, and a
  pair a person marked not-duplicate is never re-proposed.
- **Batch paths never N+1.** The nightly scan prefetches the location
  overrides once and reconciles in bulk.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

# Trigram similarity at or above this proposes a duplicate pair. Chosen
# conservative: at 0.62 "Bright Future Primary" ≈ "Bright Future Primary
# School" matches while ordinary same-district names do not.
DUPLICATE_SIMILARITY_THRESHOLD = 0.62


def _location_override_ids() -> set[str]:
    from apps.routes.models import SchoolGeoPoint

    return set(SchoolGeoPoint.objects.values_list("school_id", flat=True))


@transaction.atomic
def reconcile_issues(schools, *, location_override_ids=None) -> dict:
    """Reconcile the open DataQualityIssue rows for the given schools."""

    from apps.schools.models import DataQualityIssue, build_data_quality_issues

    schools = [school for school in schools if school.pk]
    if not schools:
        return {"created": 0, "resolved": 0, "updated": 0}
    if location_override_ids is None and len(schools) > 1:
        location_override_ids = _location_override_ids()
    fresh: dict[str, DataQualityIssue] = {}
    for school in schools:
        has_location = None
        if location_override_ids is not None:
            has_location = bool(
                (school.latitude is not None and school.longitude is not None)
                or school.id in location_override_ids
            )
        for issue in build_data_quality_issues(school, has_location=has_location):
            fresh[issue.condition_key] = issue
    open_rows = {
        row.condition_key: row
        for row in DataQualityIssue.objects.filter(
            school_id__in=[school.id for school in schools], status="open"
        )
    }
    now = timezone.now()
    to_resolve = [row for key, row in open_rows.items() if key not in fresh]
    for row in to_resolve:
        row.status = "resolved"
        row.resolved_at = now
    if to_resolve:
        DataQualityIssue.objects.bulk_update(
            to_resolve, ["status", "resolved_at", "updated_at"]
        )
    to_update = []
    for key, row in open_rows.items():
        built = fresh.get(key)
        if built is None:
            continue
        if (
            row.severity != built.severity
            or row.current_value != built.current_value
            or row.suggested_fix != built.suggested_fix
        ):
            row.severity = built.severity
            row.current_value = built.current_value
            row.suggested_fix = built.suggested_fix
            to_update.append(row)
    if to_update:
        DataQualityIssue.objects.bulk_update(
            to_update,
            ["severity", "current_value", "suggested_fix", "updated_at"],
        )
    # A condition that persists after a human "resolved" it REOPENS its row
    # (keeping the assignee) rather than spawning a fresh anonymous one —
    # the audit found regeneration silently discarding ownership here.
    missing_keys = [key for key in fresh if key not in open_rows]
    reopenable = {
        row.condition_key: row
        for row in DataQualityIssue.objects.filter(
            condition_key__in=missing_keys, status="resolved"
        ).order_by("resolved_at")
    }
    to_reopen = []
    for key, row in reopenable.items():
        built = fresh[key]
        row.status = "open"
        row.resolved_at = None
        row.severity = built.severity
        row.current_value = built.current_value
        row.suggested_fix = built.suggested_fix
        to_reopen.append(row)
    if to_reopen:
        DataQualityIssue.objects.bulk_update(
            to_reopen,
            [
                "status",
                "resolved_at",
                "severity",
                "current_value",
                "suggested_fix",
                "updated_at",
            ],
        )
    reopened_keys = set(reopenable)
    to_create = [
        issue
        for key, issue in fresh.items()
        if key not in open_rows and key not in reopened_keys
    ]
    if to_create:
        DataQualityIssue.objects.bulk_create(to_create, batch_size=1000)
    return {
        "created": len(to_create),
        "resolved": len(to_resolve),
        "updated": len(to_update),
        "reopened": len(to_reopen),
    }


def detect_duplicate_candidates(
    *, threshold: float = DUPLICATE_SIMILARITY_THRESHOLD
) -> dict:
    """Propose SchoolDuplicateCandidate pairs by trigram name similarity
    within a district (the school_name_trgm_idx GIN index carries this).

    Proposes only — never resolves, never overrides a human decision:
    resolved pairs are skipped, and duplicate_status flips to ``potential``
    only from ``none``. The queryset .update() path is deliberate: a
    ``School.save()`` here would cascade its recompute/reconcile side
    effects across every flagged school.
    """

    from django.contrib.postgres.search import TrigramSimilarity

    from apps.schools.models import School, SchoolDuplicateCandidate

    eligible = School.objects.filter(deleted_at__isnull=True).exclude(
        duplicate_status__in=("merged", "confirmed")
    )
    existing_pairs = {
        frozenset(pair)
        for pair in SchoolDuplicateCandidate.objects.values_list(
            "school_id", "candidate_id"
        )
    }
    created = 0
    flagged_ids: set[str] = set()
    for school in eligible.only(
        "id", "name", "district_id", "duplicate_status"
    ).iterator(chunk_size=500):
        if not school.name or len(school.name) < 4 or not school.district_id:
            continue
        matches = (
            eligible.filter(district_id=school.district_id)
            .exclude(id=school.id)
            .annotate(similarity=TrigramSimilarity("name", school.name))
            .filter(similarity__gte=threshold)
            .order_by("-similarity")
            .values_list("id", "similarity")[:3]
        )
        for candidate_id, similarity in matches:
            pair = frozenset((school.id, candidate_id))
            if pair in existing_pairs:
                continue
            existing_pairs.add(pair)
            SchoolDuplicateCandidate.objects.create(
                school_id=school.id,
                candidate_id=candidate_id,
                score=int(similarity * 100),
                reasons=["name_similarity", "same_district"],
            )
            created += 1
            flagged_ids.update(pair)
    if flagged_ids:
        School.objects.filter(id__in=flagged_ids, duplicate_status="none").update(
            duplicate_status="potential"
        )
    return {"candidates_created": created, "schools_flagged": len(flagged_ids)}


def over_capacity_staff() -> list[dict]:
    """Staff carrying more direct schools than their governed capacity.

    Mirrors the assignment drawer's rule exactly (apps.assignment.services):
    the CD/IA-set StaffSupportCapacity for the operational FY, with the same
    default of 10 when no capacity row exists — the two surfaces must never
    disagree about who is over.
    """

    from apps.accounts.models import StaffSchoolAssignment, StaffSupportCapacity
    from apps.core.fy import get_operational_fy

    fy = get_operational_fy(timezone.now())
    limits = {
        staff_id: limit
        for staff_id, limit in StaffSupportCapacity.objects.filter(
            fy=fy, is_active=True
        ).values_list("staff_id", "max_direct_schools_supported")
    }
    usage = (
        StaffSchoolAssignment.objects.values("staff_id")
        .annotate(used=Count("id"))
        .order_by()
    )
    over = []
    for row in usage:
        limit = limits.get(row["staff_id"], 10)
        if row["used"] > limit:
            over.append(
                {
                    "staff_id": str(row["staff_id"]),
                    "used": row["used"],
                    "limit": limit,
                }
            )
    return over


def scan_all(*, batch_size: int = 500) -> dict:
    """The nightly sweep: propose duplicates first (so the duplicate_risk
    issue reflects them), then reconcile every operating school's issues."""

    from apps.schools.models import School

    duplicates = detect_duplicate_candidates()
    location_override_ids = _location_override_ids()
    totals = {"created": 0, "resolved": 0, "updated": 0, "reopened": 0, "schools": 0}
    queryset = School.objects.filter(
        deleted_at__isnull=True,
        operational_status__in=("active", "reopened"),
    )
    batch: list = []
    for school in queryset.iterator(chunk_size=batch_size):
        batch.append(school)
        if len(batch) >= batch_size:
            result = reconcile_issues(
                batch, location_override_ids=location_override_ids
            )
            for key in ("created", "resolved", "updated", "reopened"):
                totals[key] += result[key]
            totals["schools"] += len(batch)
            batch = []
    if batch:
        result = reconcile_issues(batch, location_override_ids=location_override_ids)
        for key in ("created", "resolved", "updated", "reopened"):
            totals[key] += result[key]
        totals["schools"] += len(batch)
    return {**totals, **duplicates}


def data_quality_summary() -> dict:
    """Aggregate counts for System Health — queue sizes and their owners."""

    from apps.schools.models import DataQualityIssue, SchoolDuplicateCandidate

    open_issues = DataQualityIssue.objects.filter(status="open")
    by_severity = {
        row["severity"]: row["count"]
        for row in open_issues.values("severity").annotate(count=Count("id")).order_by()
    }
    return {
        "openIssues": sum(by_severity.values()),
        "critical": by_severity.get("critical", 0),
        "warning": by_severity.get("warning", 0),
        "info": by_severity.get("info", 0),
        "missingCoordinates": open_issues.filter(issue_type="no_coordinates").count(),
        "unassignedOpenIssues": open_issues.filter(
            Q(assigned_to__isnull=True) | Q(assigned_to="")
        ).count(),
        "pendingDuplicatePairs": SchoolDuplicateCandidate.objects.filter(
            resolved=False
        ).count(),
        "overCapacityStaff": len(over_capacity_staff()),
    }
