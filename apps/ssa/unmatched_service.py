"""Unmatched SSA queue — pagination, filtering, and fuzzy school-match
suggestion for /ssa/unmatched (Issue 5 of the audit).

Before this fix, the view loaded EVERY pending/hold UnmatchedSSARecord with
no pagination, then looped over all of them running one
`School.objects.filter(name__icontains=...).first()` query per record (a
full-table ILIKE scan each time) to suggest a match — unbounded on both
axes: N unmatched records x an unindexed scan of the whole School table.

compute_suggested_match() is the ONE place a School match is suggested for
an unmatched SSA row — called ONCE at upload time
(apps.ssa.upload_service.upload_ssa_file) and stored on
suggested_school/match_confidence, never recomputed per page view. It
narrows candidates by district_raw first (when present) before ranking by
trigram similarity (pg_trgm — apps/schools/migrations/0013_enable_pg_trgm.py
+ the GIN index on School.name), so even that one-time computation never
scans the full table. If pg_trgm is unavailable at runtime for any reason,
it falls back to a Python difflib ranking over a bounded candidate pool —
the feature degrades gracefully rather than hard-failing.

get_unmatched_queue() is the read path: filters (status / upload batch /
district / suspected School ID / minimum confidence / uploaded date range)
+ real pagination, zero per-row queries (suggested_school is select_related).
"""

from __future__ import annotations

import difflib

from django.core.paginator import Paginator
from django.db import DatabaseError, transaction

from apps.core.exceptions import BadRequest, NotFoundError

DEFAULT_PAGE_SIZE = 50
CANDIDATE_LIMIT = 200  # hard cap on the Python-fallback candidate pool


def transition_unmatched_record(record_id: str, target: str, actor, *, on_match=None):
    """Own unmatched-SSA triage, including the matched-record side effect."""
    if target not in {"matched", "hold", "ignored"}:
        raise BadRequest("Select match, hold, or ignore.")
    if target == "matched" and on_match is None:
        raise BadRequest("A matched SSA record must be imported.")

    from apps.schools.models import UnmatchedSSARecord

    with transaction.atomic():
        record = (
            UnmatchedSSARecord.objects.select_for_update().filter(id=record_id).first()
        )
        if not record:
            raise NotFoundError("Unmatched SSA record not found.")
        if record.status not in {"pending", "hold"}:
            raise BadRequest(f"This SSA record is already {record.status}.")
        result = on_match(record) if on_match is not None else None
        record.status = target
        record.save(update_fields=["status", "updated_at"])

        from apps.audit.services import log as audit_log

        audit_log(
            action=f"ssa.unmatched_{target}",
            subject_kind="UnmatchedSSARecord",
            subject_id=record.id,
            actor_id=actor.id,
            actor_role=getattr(actor, "active_role", None),
            payload={"schoolIdRaw": record.school_id},
        )
    return record, result


def compute_suggested_match(school_name_raw: str | None, district_raw: str | None):
    """Returns (school_id_or_None, confidence_0_to_1_or_None) for one
    unmatched row. Never queries more than a district-narrowed (or capped)
    candidate pool — no full unindexed School table scan."""
    if not (school_name_raw or "").strip():
        return None, None

    from apps.geography.models import District
    from apps.schools.models import School

    candidates = School.objects.filter(deleted_at__isnull=True)
    if district_raw:
        district_ids = list(
            District.objects.filter(name__icontains=district_raw).values_list(
                "id", flat=True
            )
        )
        if district_ids:
            candidates = candidates.filter(district_id__in=district_ids)

    try:
        from django.contrib.postgres.search import TrigramSimilarity

        best = (
            candidates.annotate(sim=TrigramSimilarity("name", school_name_raw))
            .filter(sim__gt=0.15)
            .order_by("-sim")
            .values_list("id", "sim")
            .first()
        )
        if best:
            return best[0], round(float(best[1]), 3)
        return None, None
    except DatabaseError:
        pass  # pg_trgm unavailable on this connection -- Python fallback below.

    pool = list(candidates.values_list("id", "name")[:CANDIDATE_LIMIT])
    needle = school_name_raw.strip().lower()
    best_id, best_ratio = None, 0.0
    for sid, name in pool:
        ratio = difflib.SequenceMatcher(None, needle, (name or "").lower()).ratio()
        if ratio > best_ratio:
            best_id, best_ratio = sid, ratio
    if best_id and best_ratio >= 0.5:
        return best_id, round(best_ratio, 3)
    return None, None


def get_unmatched_queue(
    filters: dict | None = None,
    page=1,
    page_size: int = DEFAULT_PAGE_SIZE,
    base=None,
):
    """Filtered, paginated UnmatchedSSARecord queryset — a Django Page
    object. select_related covers suggested_school/batch so rendering the
    page issues zero additional per-row queries.

    `base` bounds the queue to the rows a reader may see (the country-bound
    `apps.analytics.ia_collection.unmatched_rows_in_reach`, IA review
    2026-09-13); None keeps every row."""
    from apps.schools.models import UnmatchedSSARecord

    filters = filters or {}
    qs = UnmatchedSSARecord.objects.select_related("batch", "suggested_school")
    if base is not None:
        qs = qs.filter(id__in=base.values("id"))

    status = (filters.get("status") or "").strip()
    if status:
        qs = qs.filter(status=status)
    else:
        qs = qs.filter(status__in=["pending", "hold"])

    batch_id = (filters.get("batch") or "").strip()
    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    district = (filters.get("district") or "").strip()
    if district:
        qs = qs.filter(district_raw__icontains=district)

    school_id = (filters.get("school_id") or "").strip()
    if school_id:
        qs = qs.filter(school_id__icontains=school_id)

    min_confidence = filters.get("min_confidence")
    if min_confidence not in (None, ""):
        qs = qs.filter(match_confidence__gte=float(min_confidence))

    date_from = (filters.get("date_from") or "").strip()
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = (filters.get("date_to") or "").strip()
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    qs = qs.order_by("-created_at")
    paginator = Paginator(qs, page_size)
    page_number = page if (isinstance(page, int) and page > 0) else 1
    return paginator.get_page(page_number)


def batch_options(base=None):
    """(id, label) pairs for the upload-batch filter dropdown — only
    batches that actually have unmatched rows (in `base`, when given)."""
    from apps.schools.models import SSAImportBatch

    batches = SSAImportBatch.objects.all()
    if base is not None:
        batches = batches.filter(id__in=base.values("batch_id"))
    return list(
        batches.filter(unmatched_records__isnull=False)
        .distinct()
        .order_by("-created_at")
        .values_list("id", "file_name")
    )


# ── Filing a parked row once its school exists ──────────────────────────────
def refile_known(school_ids=None, *, apply: bool = True) -> dict:
    """File the parked SSA rows whose School ID now names a school.

    Owner, 2026-10-10: "all the schools that were assessed but the record had
    issues can be fixed and showed in the right place". On production that day
    88 rows of FY 2025/26 sat in this queue, every one for a School ID the
    directory did not hold. Such a row is a real assessment waiting for its
    school: the moment a school with exactly that School ID is added (an
    upload, a single create), the row is filed to it by the same writer every
    SSA goes through (`apps.ssa.services.upload`), in the name of whoever
    uploaded the batch, and waits for verification like any other.

    Exact School ID only — a name that merely looks alike is a person's
    decision, on the queue's own page. ``school_ids`` narrows the pass to the
    schools just added; ``apply=False`` reports what would be filed.

    ``{"filed": [...], "skipped": [...]}``, each entry the row's School ID
    with the reason it was left.
    """
    from apps.accounts.models import User
    from apps.schools.models import School, UnmatchedSSARecord
    from apps.ssa.services import upload

    parked = UnmatchedSSARecord.objects.filter(
        status__in=("pending", "hold")
    ).select_related("batch")
    if school_ids is not None:
        wanted = {str(value).strip() for value in school_ids if value}
        if not wanted:
            return {"filed": [], "skipped": []}
        parked = parked.filter(school_id__in=wanted)
    parked = list(parked.order_by("created_at", "id"))
    if not parked:
        return {"filed": [], "skipped": []}
    schools = {
        school.school_id: school
        for school in School.objects.filter(
            school_id__in={row.school_id.strip() for row in parked},
            deleted_at__isnull=True,
        )
    }
    uploaders = {
        user.id: user
        for user in User.objects.filter(
            id__in={row.batch.uploaded_by for row in parked if row.batch_id},
            is_active=True,
        )
    }
    filed, skipped = [], []
    for row in parked:
        school = schools.get(row.school_id.strip())
        if school is None:
            continue
        actor = uploaders.get(row.batch.uploaded_by) if row.batch_id else None
        if actor is None:
            skipped.append((row.school_id, "the uploader's account is not active"))
            continue
        if not apply:
            filed.append(row.school_id)
            continue

        def write(locked, school=school, actor=actor):
            return upload(
                {
                    "schoolId": school.school_id,
                    "dateOfSsa": locked.date_of_ssa,
                    "scores": [
                        {"intervention": key, "score": score}
                        for key, score in (locked.scores or {}).items()
                    ],
                    "collectorType": "ia"
                    if actor.active_role == "ImpactAssessment"
                    else "staff",
                },
                actor,
            )

        try:
            transition_unmatched_record(row.id, "matched", actor, on_match=write)
        except Exception as exc:  # noqa: BLE001 — one bad row never stops the rest
            skipped.append((row.school_id, f"{type(exc).__name__}: {exc}"[:200]))
        else:
            filed.append(row.school_id)
    return {"filed": filed, "skipped": skipped}


def refile_after_commit(school_ids) -> None:
    """Queue `refile_known` for schools just added, once they are committed.
    Never raises: a parked row that is not filed now is still in the queue."""
    import logging

    school_ids = [value for value in school_ids if value]
    if not school_ids:
        return

    def run() -> None:
        try:
            result = refile_known(school_ids)
            if result["filed"] or result["skipped"]:
                logging.getLogger("edify.ssa.unmatched").info(
                    "Parked SSA rows filed for new schools: %s", result
                )
        except Exception:  # noqa: BLE001
            logging.getLogger("edify.ssa.unmatched").exception(
                "Parked SSA rows could not be filed for %s", school_ids
            )

    transaction.on_commit(run)
