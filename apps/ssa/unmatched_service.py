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
from django.db import DatabaseError

DEFAULT_PAGE_SIZE = 25
CANDIDATE_LIMIT = 200  # hard cap on the Python-fallback candidate pool


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
    filters: dict | None = None, page=1, page_size: int = DEFAULT_PAGE_SIZE
):
    """Filtered, paginated UnmatchedSSARecord queryset — a Django Page
    object. select_related covers suggested_school/batch so rendering the
    page issues zero additional per-row queries."""
    from apps.schools.models import UnmatchedSSARecord

    filters = filters or {}
    qs = UnmatchedSSARecord.objects.select_related("batch", "suggested_school")

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


def batch_options():
    """(id, label) pairs for the upload-batch filter dropdown — only
    batches that actually have unmatched rows."""
    from apps.schools.models import SSAImportBatch

    return list(
        SSAImportBatch.objects.filter(unmatched_records__isnull=False)
        .distinct()
        .order_by("-created_at")
        .values_list("id", "file_name")
    )
