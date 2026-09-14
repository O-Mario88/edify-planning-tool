"""SSA collection To-Dos (IA review, owner, 2026-09-13).

Impact Assessment coordinates baseline and follow-up collection across the
country but owns no school portfolio, so its To-Do list had nothing about
collection at all: `_school_quality_todos` reads the officer's own schools
(none), and the project To-Dos only the enrolments they created. These rows
come from the collection worklist (apps.analytics.ia_collection):

- Impact Assessment: schools with no confirmed SSA this year, GROUPED per
  account owner (a district for schools nobody owns) — one row per owner, not
  394 single rows — each opening the Collection view filtered to that owner,
  where "Ask owner to collect" sends the no_ssa TeamAction. Nothing here
  schedules into anybody's portfolio.
- Impact Assessment and Admin: import rows blocked in their own recent SSA
  batches, which only the uploader can re-file.
- Anyone who keys SSA scores: records a verifier returned to them.
- The Country Director: SSA scores an Impact Assessment officer collected,
  which the Director confirms as the fallback verifier.

The country-wide pending-verification and unmatched-row queues are Impact
Assessment's queue rows (apps.activities.ia_todos), so they are not repeated
here. Rows are derived and self-closing, built from aggregate queries, and a
failure never breaks the queue.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, Min
from django.utils import timezone

logger = logging.getLogger(__name__)

CATEGORY = "Baseline & Field Data"
SOURCE = "SSA Collection"

#: Owners listed one row each; the rest fold into one summary row.
MAX_OWNER_ROWS = 8
#: The roles that key SSA scores, and so can have them returned.
KEYING_ROLES = frozenset(
    {
        "CCEO",
        "Program Lead",
        "ImpactAssessment",
        "Admin",
        "PartnerAdmin",
        "PartnerFieldOfficer",
    }
)
#: How far back an uploader is reminded of their blocked rows.
BLOCKED_ROWS_DAYS = 30


def _row(
    key,
    *,
    title,
    description,
    url,
    action,
    linked,
    today,
    due=None,
    priority="medium",
    tone="warning",
):
    late = due is not None and due < today
    return {
        "id": key,
        "title": title,
        "description": description,
        "category": CATEGORY,
        "priority": "high" if late else priority,
        "status_key": "overdue" if late else "waiting_me",
        "status_label": "Overdue" if late else "Waiting on Me",
        "status_tone": "danger" if late else tone,
        "due_label": f"Since {due:%-d %b}" if due else "—",
        "due_tone": "danger" if late else "neutral",
        "linked": linked,
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": SOURCE,
        "_due_sort": due or today,
    }


def collection_todos(principal, role, today) -> list[dict]:
    """Registered in MODULE_TODO_BUILDERS (apps.command_center.todo_service)."""
    try:
        out: list[dict] = []
        if role == "ImpactAssessment":
            out.extend(_owner_rows(principal, today))
        if role in ("ImpactAssessment", "Admin"):
            out.extend(_blocked_rows(principal, today))
        if role == "CountryDirector":
            out.extend(_fallback_rows(principal, today))
        if role in KEYING_ROLES:
            out.extend(_returned_rows(principal, today))
        return out
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("SSA collection To-Dos failed")
        return []


def _owner_rows(principal, today) -> list[dict]:
    from apps.analytics.ia_collection import (
        FOLLOW_UP_DUE,
        NEVER_ASSESSED,
        VISIT_WITHOUT_SCORES,
        _owner_names,
        annotate_states,
        collection_schools,
    )

    needing = annotate_states(collection_schools(principal)).filter(
        collection_state__in=(NEVER_ASSESSED, FOLLOW_UP_DUE, VISIT_WITHOUT_SCORES)
    )
    groups = list(
        needing.order_by()
        .values("account_owner_id", "district_id", "district__name")
        .annotate(n=Count("id"))
    )
    by_owner: dict[str, int] = {}
    unowned: dict[tuple[str, str], int] = {}
    for group in groups:
        owner = group["account_owner_id"] or ""
        if owner:
            by_owner[owner] = by_owner.get(owner, 0) + group["n"]
        else:
            key = (
                str(group["district_id"] or ""),
                group["district__name"] or "No district",
            )
            unowned[key] = unowned.get(key, 0) + group["n"]
    names = _owner_names(by_owner)

    ranked = sorted(by_owner.items(), key=lambda item: (-item[1], item[0]))
    rows = []
    for owner_id, n in ranked[:MAX_OWNER_ROWS]:
        name = names.get(str(owner_id), "an unmatched owner")
        rows.append(
            _row(
                f"ssa-collect-owner-{owner_id}",
                title=f"{n} school{'s' if n != 1 else ''} without this year's SSA · {name}",
                description=(
                    "No confirmed SSA this financial year. Ask the owner to collect: "
                    "the request closes itself when a confirmed SSA lands."
                ),
                url="/ia/dashboard/?"
                + urlencode({"view": "collection", "owner": owner_id}),
                action="Open Collection",
                linked=f"{n} school{'s' if n != 1 else ''}",
                today=today,
            )
        )
    rest = sum(n for _owner, n in ranked[MAX_OWNER_ROWS:])
    if rest:
        rows.append(
            _row(
                "ssa-collect-owner-rest",
                title=f"{rest} more school{'s' if rest != 1 else ''} without this year's SSA",
                description="Across the other account owners in your country.",
                url="/ia/dashboard/?view=collection",
                action="Open Collection",
                linked=f"{rest} school{'s' if rest != 1 else ''}",
                today=today,
                priority="low",
            )
        )
    for (district_id, district_name), n in sorted(
        unowned.items(), key=lambda item: -item[1]
    )[:MAX_OWNER_ROWS]:
        query = {"view": "collection"}
        if district_id:
            query["district"] = district_id
        rows.append(
            _row(
                f"ssa-collect-unowned-{district_id or 'none'}",
                title=f"{n} unowned school{'s' if n != 1 else ''} without this year's SSA · {district_name}",
                description=(
                    "Nobody owns these schools, so nobody can be asked. Request an "
                    "SSA visit, or have the account owner matched first."
                ),
                url="/ia/dashboard/?" + urlencode(query),
                action="Open Collection",
                linked=f"{n} school{'s' if n != 1 else ''}",
                today=today,
                priority="low",
            )
        )
    return rows


def _blocked_rows(principal, today) -> list[dict]:
    from apps.schools.models import SSAImportRow

    uid = str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))
    if not uid:
        return []
    since = timezone.now() - timedelta(days=BLOCKED_ROWS_DAYS)
    blocked = SSAImportRow.objects.filter(
        status="blocked", batch__uploaded_by=uid, batch__created_at__gte=since
    ).aggregate(
        n=Count("id"),
        batches=Count("batch_id", distinct=True),
        oldest=Min("batch__created_at"),
    )
    if not blocked["n"]:
        return []
    n = blocked["n"]
    return [
        _row(
            "ssa-import-blocked-mine",
            title=f"Re-file {n} blocked SSA row{'s' if n != 1 else ''} from your uploads",
            description=(
                "Rows your files carried that could not be imported: missing or "
                "invalid scores, a duplicate date, or a school outside your country."
            ),
            url="/ssa/upload/history/?has_blocked=1",
            action="Open Upload History",
            linked=f"{blocked['batches']} batch{'es' if blocked['batches'] != 1 else ''}",
            today=today,
            due=timezone.localdate(blocked["oldest"]) if blocked["oldest"] else None,
        )
    ]


def _returned_rows(principal, today) -> list[dict]:
    from apps.core.scoping import owner_ids
    from apps.ssa.models import SsaRecord

    own = [str(i) for i in owner_ids(principal) if i]
    if not own:
        return []
    returned = SsaRecord.objects.filter(
        deleted_at__isnull=True,
        verification_status="returned",
        collected_by_user_id__in=own,
    ).aggregate(n=Count("id"), oldest=Min("returned_at"))
    if not returned["n"]:
        return []
    n = returned["n"]
    return [
        _row(
            "ssa-returned-mine",
            title=f"Correct {n} SSA record{'s' if n != 1 else ''} returned to you",
            description=(
                "A verifier sent the scores back with a reason. Re-key them on the "
                "visit, or enter a corrected assessment."
            ),
            url="/ssa/verification/?status=returned&mine=1",
            action="Open Returned SSA",
            linked=f"{n} record{'s' if n != 1 else ''}",
            today=today,
            due=(timezone.localdate(returned["oldest"]) + timedelta(days=7))
            if returned["oldest"]
            else None,
            priority="high",
        )
    ]


def _fallback_rows(principal, today) -> list[dict]:
    from apps.ssa.services import verifiable_records

    pending = verifiable_records(principal).aggregate(
        n=Count("id"), oldest=Min("created_at")
    )
    if not pending["n"]:
        return []
    n = pending["n"]
    return [
        _row(
            "ssa-cd-fallback",
            title=f"Confirm {n} SSA record{'s' if n != 1 else ''} Impact Assessment collected",
            description=(
                "Scores an Impact Assessment officer keyed cannot be confirmed by "
                "that officer; you are the fallback verifier."
            ),
            url="/ssa/verification/",
            action="Open SSA Verification",
            linked=f"{n} record{'s' if n != 1 else ''}",
            today=today,
            due=(timezone.localdate(pending["oldest"]) + timedelta(days=7))
            if pending["oldest"]
            else None,
            priority="high",
        )
    ]
