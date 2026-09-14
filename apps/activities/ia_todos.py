"""Impact Assessment's data-quality To-Dos (IA review, owner, 2026-09-13).

The verification desk has more queues than activity verification, and until
now none of them reached the To-Do list: SSA records waiting for a verifier,
imported SSA rows no school matched, activities flagged as potential
duplicates, sample checks waiting for a second verifier, and returned work
nobody has corrected for a week. Each is one summary row that opens the queue
which resolves it — the counts the dashboard already shows, bounded the same
way: the verifier's country, and never work the verifier may not decide
because it is their own (a colleague decides it, or the Country Director as
fallback verifier).

Rows are derived, never stored: when a queue empties its row stops appearing.
Five aggregate queries, whatever the size of the queues.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

#: How long returned work may wait for its correction before IA chases it.
RETURNED_CHASE_DAYS = 7

#: The same category the activity verification rows carry
#: (apps.command_center.todo_service.IA_TODO_CATEGORY).
CATEGORY = "Data Quality & Verification"


def unmatched_ssa_for_scope(scope):
    """Imported SSA rows still pending or on hold, inside `scope`'s country.

    An unmatched row has no school, so it is placed by who uploaded its batch
    or, failing that, by the school the importer suggested. A legacy row with
    neither belongs to no country and is counted only for an unbounded reader.
    """
    from apps.core.scoping import country_bound, country_user_ids
    from apps.schools.models import UnmatchedSSARecord

    rows = UnmatchedSSARecord.objects.filter(status__in=("pending", "hold"))
    if country_bound(scope):
        rows = rows.filter(
            Q(batch__uploaded_by__in=country_user_ids(scope))
            | Q(suggested_school__region__country=scope.country)
        )
    return rows


def pending_ssa_for_verifier(principal, scope):
    """SSA records waiting for verification that `principal` may verify: in
    their schools' country, and neither collected nor uploaded by them."""
    from apps.core.scoping import owner_ids, scoped_school_queryset
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord

    schools = scoped_school_queryset(
        scope, School.objects.filter(deleted_at__isnull=True)
    )
    records = SsaRecord.objects.filter(
        deleted_at__isnull=True, verification_status="pending", school__in=schools
    )
    own = [str(i) for i in owner_ids(principal) if i]
    if own:
        records = records.exclude(collected_by_user_id__in=own).exclude(
            uploaded_by__in=own
        )
    return records


def _row(
    key,
    *,
    title,
    description,
    url,
    action,
    count,
    oldest,
    today,
    priority="high",
    late_after_days=None,
):
    """One summary row in the queue's shape. `oldest` dates the longest wait;
    past `late_after_days` the row reads as overdue."""
    oldest_day = timezone.localdate(oldest) if oldest else None
    late = (
        late_after_days is not None
        and oldest_day is not None
        and (today - oldest_day).days > late_after_days
    )
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": CATEGORY,
        "priority": "critical" if late else priority,
        "status_key": "overdue" if late else "waiting_me",
        "status_label": "Overdue" if late else "Waiting on Me",
        "status_tone": "danger" if late else "warning",
        "due_label": f"Oldest {oldest_day:%-d %b}" if oldest_day else "—",
        "due_tone": "danger" if late else "neutral",
        "linked": f"{count} waiting",
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": "Impact Assessment",
        "_due_sort": oldest_day or today,
    }


def ia_queue_todos(principal, role, today) -> list[dict]:
    """The verification desk's queues, as To-Dos, for an Impact Assessment
    officer (registered in MODULE_TODO_BUILDERS)."""
    if role != "ImpactAssessment":
        return []
    try:
        return _ia_queue_todos(principal, today)
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Impact Assessment queue To-Dos failed")
        return []


def _ia_queue_todos(principal, today) -> list[dict]:
    from apps.activities.ia_models import DuplicateActivity, VerificationSample
    from apps.activities.models import Activity
    from apps.core.enums import ActivityStatus
    from apps.core.scoping import (
        activity_country_q,
        owner_ids,
        resolve_user_scope,
        scoped_school_queryset,
    )
    from apps.schools.models import School

    scope = resolve_user_scope(principal)
    uid = str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))
    own = [str(i) for i in owner_ids(principal) if i]
    reach = Activity.objects.filter(deleted_at__isnull=True).filter(
        activity_country_q(scope)
    )
    out: list[dict] = []

    # SSA records a different verifier must confirm (owner, 2026-09-13).
    ssa = pending_ssa_for_verifier(principal, scope).aggregate(
        n=Count("id"), oldest=Min("created_at")
    )
    if ssa["n"]:
        out.append(
            _row(
                "ia-ssa-pending",
                title=f"Verify {ssa['n']} SSA record{'s' if ssa['n'] != 1 else ''}",
                description="Assessment scores wait for a verifier other than the "
                "person who collected or uploaded them.",
                url="/ssa/verification/",
                action="Open SSA Verification",
                count=ssa["n"],
                oldest=ssa["oldest"],
                today=today,
                late_after_days=7,
            )
        )

    unmatched = unmatched_ssa_for_scope(scope).aggregate(
        n=Count("id"), oldest=Min("created_at")
    )
    if unmatched["n"]:
        out.append(
            _row(
                "ia-ssa-unmatched",
                title=f"Match {unmatched['n']} imported SSA "
                f"row{'s' if unmatched['n'] != 1 else ''} to a school",
                description="Until a row is matched its scores belong to no school "
                "and enter no analysis.",
                url="/ssa/unmatched",
                action="Open Unmatched SSA",
                count=unmatched["n"],
                oldest=unmatched["oldest"],
                today=today,
                priority="medium",
            )
        )

    duplicates = DuplicateActivity.objects.filter(
        status="potential", activity_id__in=reach.values("id")
    ).aggregate(n=Count("activity_id", distinct=True), oldest=Min("created_at"))
    if duplicates["n"]:
        out.append(
            _row(
                "ia-duplicates",
                title=f"Review {duplicates['n']} potential duplicate "
                f"activit{'ies' if duplicates['n'] != 1 else 'y'}",
                description="A duplicate verified twice is counted twice in every "
                "delivery figure.",
                url="/ia/duplicates/",
                action="Open Duplicate Review",
                count=duplicates["n"],
                oldest=duplicates["oldest"],
                today=today,
            )
        )

    # Sample checks: a second verifier grades them, never the original one,
    # and nobody grades a check on their own field work.
    schools = scoped_school_queryset(
        scope, School.objects.filter(deleted_at__isnull=True)
    )
    samples = VerificationSample.objects.filter(status="pending").filter(
        Q(activity_id__in=reach.values("id")) | Q(ssa_record__school__in=schools)
    )
    if uid:
        samples = samples.exclude(original_verifier=uid)
    if own:
        samples = samples.exclude(activity__responsible_staff_id__in=own).exclude(
            ssa_record__collected_by_user_id__in=own
        )
    sample_counts = samples.aggregate(n=Count("id"), oldest=Min("sampled_at"))
    if sample_counts["n"]:
        out.append(
            _row(
                "ia-samples",
                title=f"Grade {sample_counts['n']} sample "
                f"check{'s' if sample_counts['n'] != 1 else ''}",
                description="Verified work drawn for a second look, waiting for a "
                "verifier other than the one who certified it.",
                url="/ia/samples/",
                action="Open Sample Checks",
                count=sample_counts["n"],
                oldest=sample_counts["oldest"],
                today=today,
                late_after_days=14,
            )
        )

    stale_before = timezone.now() - timedelta(days=RETURNED_CHASE_DAYS)
    returned = reach.filter(
        status=ActivityStatus.RETURNED_BY_IA, updated_at__lt=stale_before
    ).aggregate(n=Count("id"), oldest=Min("updated_at"))
    if returned["n"]:
        out.append(
            _row(
                "ia-returned-stale",
                title=f"Chase {returned['n']} correction"
                f"{'s' if returned['n'] != 1 else ''} returned over "
                f"{RETURNED_CHASE_DAYS} days ago",
                description="Work sent back for correction that its owner has not "
                "resubmitted.",
                url="/ia/returned/",
                action="Open Returned Activities",
                count=returned["n"],
                oldest=returned["oldest"],
                today=today,
                priority="medium",
            )
        )
    return out
