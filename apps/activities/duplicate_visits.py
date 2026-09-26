"""One client school visit per school, per day, per kind of visit.

Owner, 2026-09-26: "I noticed a lot of users created duplicate client school
visits. can you look and make sure all the duplicate visits on the same day
same month all deleted from the database just like you did with duplicate
assignment to partner."

The only guard was create()'s double-click check, keyed on the same activity
type, the same owner AND the same partner. A second planner, a partner booking
beside a staff visit, or a reschedule onto a day that was already taken each
produced a second copy of the same visit. ``assert_not_duplicate_client_visit``
now runs wherever a client visit gets its day (create, partner scheduling,
reschedule), migration activities/0058 removes the copies already in the data
through ``remove_duplicate_client_visits``, and
``manage.py remove_duplicate_client_visits`` lists anything left (and removes
it with --apply).

WHAT COUNTS AS A DUPLICATE
Two or more live visits at the same client-rule school, on the same day, of
the same kind (activity type and Activity Catalogue item), whoever planned or
delivers them. "Visit" is the visit gate's definition
(visit_gate._client_visit_q) less the in-school training's companion visit,
which is the training. Different kinds of work on one day are not duplicates
of each other. Live means not tombstoned and not already called off or
returned (GONE_STATUSES).

WHICH ONE STAYS
A copy that has gone past planning (started, evidence, a Salesforce ID, IA
review, money moved, a training pair, any status beyond scheduled) is delivery
history and is never removed. When a group holds such copies, all of them stay
and only the still-planned copies go. Otherwise one planned copy stays: the
one a partner holds through a handover, then the furthest along, then the
earliest.

HOW A COPY IS REMOVED
The way the platform's own Cancel removes work (activities.services
._cancel_or_defer), then tombstoned. Activities are never hard-deleted
(core.models.SoftDeleteModel): a DELETE would cascade into evidence and
advance requests and is refused by the PROTECT links. So the copy leaves every
page, count and total; its un-moved advances are deleted; its draft weekly
and monthly fund requests and its daily visit batch are rebuilt without it;
its open notices are archived; a partner that held it is told; and
last_reason names the copy that stays.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

logger = logging.getLogger(__name__)

# Work called off or sent back is not a visit on the calendar.
GONE_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "returned",
    "returned_by_ia",
)
# Still only a plan, and which plan to keep when every copy is one.
PLAN_STATUS_RANK = {
    "partner_scheduled": 0,
    "scheduled": 0,
    "rescheduled": 0,
    "assigned_to_partner": 1,
    "planned": 2,
    "awaiting_owner_approval": 3,
}


@dataclass
class VisitCopy:
    id: str
    status: str
    created_at: object
    delivery_type: str
    responsible_staff_id: str | None
    assigned_partner_id: str | None
    partner_linked: bool = False
    # Why this copy may not be removed; "" for a plain plan.
    history: str = ""
    who: str = ""


@dataclass
class DuplicateGroup:
    school_id: str
    school_name: str
    school_code: str
    day: date
    activity_type: str
    catalogue_item_id: str | None
    kind: str
    kept: list[VisitCopy] = field(default_factory=list)
    removed: list[VisitCopy] = field(default_factory=list)

    def describe(self) -> str:
        where = f"{self.school_name} ({self.school_code})"
        return f"{where} · {self.day:%d %b %Y} · {self.kind}"


def _is_client_visit_kind(activity_type, catalogue_item=None, purpose_type=None):
    """Mirrors the row filter in ``_visit_rows`` for a row not saved yet."""
    from apps.planning.visit_gate import COMPANION_VISIT_PURPOSE, FOLLOW_UP_VISIT_TYPES

    if purpose_type == COMPANION_VISIT_PURPOSE:
        return False
    if catalogue_item is not None and getattr(
        catalogue_item, "counts_toward_client_visit", False
    ):
        return True
    return activity_type in FOLLOW_UP_VISIT_TYPES


def _visit_rows(Activity):
    from apps.planning.visit_gate import (
        CLIENT_RULE_SCHOOL_TYPES,
        COMPANION_VISIT_PURPOSE,
        _client_visit_q,
    )

    return (
        Activity._base_manager.filter(
            deleted_at__isnull=True,
            school__isnull=False,
            school__school_type__in=CLIENT_RULE_SCHOOL_TYPES,
        )
        .filter(_client_visit_q())
        .exclude(status__in=GONE_STATUSES)
        .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
        .order_by()
    )


def _day(row) -> date | None:
    if row["planned_date"]:
        return row["planned_date"]
    if row["scheduled_date"]:
        return timezone.localtime(row["scheduled_date"]).date()
    return None


def _history(row, *, evidence, money_moved, paired) -> str:
    if row["status"] not in PLAN_STATUS_RANK:
        return f"status {row['status']}"
    if row["salesforce_activity_id"]:
        return "Salesforce ID"
    if row["evidence_status"] not in (None, "", "none") or row["id"] in evidence:
        return "evidence"
    if row["execution_started_at"] or row["actual_delivery_date"]:
        return "started"
    if row["submitted_to_ia_at"] or row["ia_verification_status"] not in (
        None,
        "",
        "pending",
    ):
        return "IA review"
    if row["payment_status"] not in (None, "", "none") or row["id"] in money_moved:
        return "money moved"
    if row["paired_school_visit_id"] or row["id"] in paired:
        return "paired with a training"
    return ""


def find_duplicate_client_visits(registry=None) -> list[DuplicateGroup]:
    """Every school-day holding more than one live copy of a client visit,
    with the copies to keep and to remove. Reads only.

    ``registry`` is the app registry to take models from: the migration
    passes its historical one, so this runs against the schema of the moment.
    """
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES

    registry = registry or django_apps
    Activity = registry.get_model("activities", "Activity")
    rows = _visit_rows(Activity).values(
        "id",
        "school_id",
        "school__name",
        "school__school_id",
        "planned_date",
        "scheduled_date",
        "activity_type",
        "catalogue_item_id",
        "activity_name_snapshot",
        "status",
        "delivery_type",
        "responsible_staff_id",
        "assigned_partner_id",
        "created_at",
        "salesforce_activity_id",
        "evidence_status",
        "execution_started_at",
        "actual_delivery_date",
        "submitted_to_ia_at",
        "ia_verification_status",
        "payment_status",
        "paired_school_visit_id",
    )
    buckets: dict[tuple, list[dict]] = {}
    for row in rows.iterator(chunk_size=2000):
        day = _day(row)
        if day is None:
            continue
        key = (row["school_id"], day, row["activity_type"], row["catalogue_item_id"])
        buckets.setdefault(key, []).append(row)
    buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    if not buckets:
        return []

    ids = [row["id"] for group in buckets.values() for row in group]
    EvidenceRecord = registry.get_model("evidence", "EvidenceRecord")
    AdvanceRequest = registry.get_model("fund_requests", "AdvanceRequest")
    PartnerAssignment = registry.get_model("partners", "PartnerAssignment")
    evidence = set(
        EvidenceRecord._base_manager.filter(activity_id__in=ids).values_list(
            "activity_id", flat=True
        )
    )
    money_moved = set(
        AdvanceRequest._base_manager.filter(
            activity_id__in=ids, status__in=list(MONEY_MOVED_ADVANCE_STATUSES)
        ).values_list("activity_id", flat=True)
    )
    paired = set(
        Activity._base_manager.filter(
            paired_school_visit_id__in=ids, deleted_at__isnull=True
        ).values_list("paired_school_visit_id", flat=True)
    )
    partner_linked = set(
        PartnerAssignment._base_manager.filter(
            scheduled_activity_id__in=ids
        ).values_list("scheduled_activity_id", flat=True)
    )
    names = _names(registry, [row for group in buckets.values() for row in group])

    groups = []
    for (school_id, day, activity_type, item_id), group in sorted(
        buckets.items(), key=lambda kv: (kv[0][1], kv[1][0]["school__name"] or "")
    ):
        copies = [
            VisitCopy(
                id=row["id"],
                status=row["status"],
                created_at=row["created_at"],
                delivery_type=row["delivery_type"],
                responsible_staff_id=row["responsible_staff_id"],
                assigned_partner_id=row["assigned_partner_id"],
                partner_linked=row["id"] in partner_linked,
                history=_history(
                    row, evidence=evidence, money_moved=money_moved, paired=paired
                ),
                who=names.get(row["id"], ""),
            )
            for row in group
        ]
        delivered = [c for c in copies if c.history]
        plans = [c for c in copies if not c.history]
        if delivered:
            kept, removed = delivered, plans
        else:
            plans.sort(
                key=lambda c: (
                    not c.partner_linked,
                    PLAN_STATUS_RANK[c.status],
                    c.created_at,
                    c.id,
                )
            )
            kept, removed = plans[:1], plans[1:]
        if not removed:
            continue
        first = group[0]
        groups.append(
            DuplicateGroup(
                school_id=school_id,
                school_name=first["school__name"] or "",
                school_code=first["school__school_id"] or "",
                day=day,
                activity_type=activity_type,
                catalogue_item_id=item_id,
                kind=first["activity_name_snapshot"]
                or activity_type.replace("_", " ").title(),
                kept=kept,
                removed=removed,
            )
        )
    return groups


def _names(registry, rows) -> dict[str, str]:
    """Who each copy belongs to, for the report: the staff member or partner."""
    StaffProfile = registry.get_model("accounts", "StaffProfile")
    Partner = registry.get_model("partners", "Partner")
    staff = dict(
        StaffProfile._base_manager.filter(
            id__in={
                r["responsible_staff_id"] for r in rows if r["responsible_staff_id"]
            }
        ).values_list("id", "user__name")
    )
    partners = dict(
        Partner._base_manager.filter(
            id__in={r["assigned_partner_id"] for r in rows if r["assigned_partner_id"]}
        ).values_list("id", "name")
    )
    out = {}
    for r in rows:
        if r["delivery_type"] == "partner" and r["assigned_partner_id"]:
            out[r["id"]] = partners.get(r["assigned_partner_id"]) or "a partner"
        elif r["responsible_staff_id"]:
            out[r["id"]] = staff.get(r["responsible_staff_id"]) or "a staff member"
    return out


def _label(copy: VisitCopy) -> str:
    detail = ", ".join(p for p in (copy.status, copy.who, copy.history) if p)
    return f"{copy.id} ({detail})"


def report(groups: list[DuplicateGroup]) -> list[str]:
    lines = []
    for g in groups:
        lines.append(f"  {g.describe()}")
        lines.append(f"    keep:   {'; '.join(_label(c) for c in g.kept)}")
        lines.append(f"    remove: {'; '.join(_label(c) for c in g.removed)}")
    return lines


def remove_duplicate_client_visits(groups=None, *, out=print) -> dict:
    """Remove every copy ``find_duplicate_client_visits`` marks for removal.

    Each copy goes in its own transaction (a savepoint inside the migration's),
    re-read under a row lock, and is skipped if it is no longer a plain plan by
    then. A copy that fails is rolled back alone and named in the output, so
    one odd row cannot stop a deploy; the command removes it once repaired."""
    groups = find_duplicate_client_visits() if groups is None else groups
    removed, skipped, failed = [], [], []
    for g in groups:
        keeper = g.kept[0]
        for copy in g.removed:
            try:
                done = _remove_copy(copy.id, g, keeper)
            except Exception as exc:  # noqa: BLE001 - reported below
                logger.exception("could not remove duplicate visit %s", copy.id)
                failed.append(f"{copy.id}: {exc}")
                continue
            (removed if done else skipped).append(copy.id)
    if removed or skipped or failed:
        out(
            f"\n  Removed {len(removed)} duplicate client school visit(s) "
            f"across {len(groups)} school-day(s):"
        )
        for line in report(groups):
            out(line)
        if skipped:
            out(f"  Left in place (changed since they were read): {skipped}")
        for line in failed:
            out(f"  NOT removed, failed: {line}")
    return {
        "groups": len(groups),
        "removed": removed,
        "skipped": skipped,
        "failed": failed,
    }


def _remove_copy(activity_id: str, group: DuplicateGroup, keeper: VisitCopy) -> bool:
    from apps.activities.models import Activity, ActivityScheduleCostLine
    from apps.activities.services import (
        _detach_from_daily_visit_batch,
        _notify_frozen_weekly_request,
    )
    from apps.fund_requests.models import (
        MONEY_MOVED_ADVANCE_STATUSES,
        AdvanceRequest,
        WeeklyFundRequest,
    )
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
    from apps.fund_requests.weekly_service import (
        REBUILDABLE_WEEKLY_STATUSES,
        sync_weekly_requests_for_activity,
    )
    from apps.notifications.models import Notification

    reason = (
        f"Duplicate of {keeper.id}: the same {group.kind} at "
        f"{group.school_name} on {group.day:%d %b %Y}. Removed "
        f"{timezone.localdate():%d %b %Y}."
    )[:512]
    with transaction.atomic():
        a = Activity.objects.select_for_update().filter(pk=activity_id).first()
        if a is None or a.status not in PLAN_STATUS_RANK or a.salesforce_activity_id:
            return False
        if AdvanceRequest.objects.filter(
            activity=a, status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).exists():
            return False
        prior_buckets = list(
            ActivityScheduleCostLine.objects.filter(activity=a).values_list(
                "responsible_user", "fiscal_year", "month", "week_start_date"
            )
        )
        frozen_wfrs = list(
            WeeklyFundRequest.objects.filter(lines__activity_budget_line__activity=a)
            .exclude(status__in=REBUILDABLE_WEEKLY_STATUSES)
            .exclude(status__in=("disbursed", "accounted"))
            .distinct()
        )
        # Cancelled first, while the default manager can still see the row:
        # the batch detach and the fund-request rebuilds read it back.
        a.status = "cancelled"
        a.last_reason = reason
        a.save(update_fields=["status", "last_reason", "updated_at"])
        _detach_from_daily_visit_batch(a)
        AdvanceRequest.objects.filter(activity=a).exclude(
            status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).delete()
        sync_weekly_requests_for_activity(a, prior_buckets=prior_buckets)
        sync_monthly_drafts_for_activity(a, prior_buckets=prior_buckets)
        now = timezone.now()
        Notification.objects.filter(
            context_type__in=("activity", "Activity"),
            context_id=a.id,
            resolved_at__isnull=True,
        ).update(
            resolved_at=now, status="archived", action_required=False, updated_at=now
        )
        a.deleted_at = now
        a.save(update_fields=["deleted_at", "updated_at"])

    for frozen in frozen_wfrs:
        _notify_frozen_weekly_request(frozen, a, "removed as a duplicate")
    if a.delivery_type == "partner" and a.assigned_partner_id:
        _tell_partner(a, group)
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="remove_duplicate_client_visit",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id="system",
            actor_role="Admin",
            success=True,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 - the removal stands without its audit row
        logger.warning("could not audit duplicate visit removal %s", a.id)
    return True


def _tell_partner(a, group: DuplicateGroup) -> None:
    """The partner loses a booking from My Plan, so it is told why. No link:
    the removed copy no longer opens."""
    try:
        from apps.notifications.services import WorkflowNotificationService
        from apps.partners.models import Partner

        user_id = (
            Partner.objects.filter(id=a.assigned_partner_id)
            .values_list("user_id", flat=True)
            .first()
        )
        if user_id:
            WorkflowNotificationService.trigger(
                event_type="partner_booking_duplicate_removed",
                category="activity",
                priority="normal",
                title="A duplicate booking was removed",
                body=(
                    f"{group.kind} at {group.school_name} on "
                    f"{group.day:%-d %b %Y} was booked more than once. The "
                    "extra booking has been removed; the school keeps one "
                    "visit that day."
                ),
                recipients=[user_id],
            )
    except Exception:  # noqa: BLE001 - a notice never undoes the removal
        logger.warning("could not tell the partner about duplicate %s", a.id)


# ── Prevention ───────────────────────────────────────────────────────────────
def existing_same_day_visit(
    school,
    *,
    activity_type: str,
    day: date | None,
    catalogue_item=None,
    purpose_type: str | None = None,
    exclude_activity_id: str | None = None,
):
    """The live copy of this visit already at ``school`` on ``day``, if any."""
    from apps.activities.models import Activity
    from apps.planning.visit_gate import COMPANION_VISIT_PURPOSE, rule_for

    if school is None or day is None or rule_for(school.school_type) != "client":
        return None
    if not _is_client_visit_kind(activity_type, catalogue_item, purpose_type):
        return None
    qs = (
        Activity.objects.filter(
            school_id=school.pk,
            planned_date=day,
            activity_type=activity_type,
            catalogue_item_id=getattr(catalogue_item, "pk", None),
        )
        .exclude(status__in=GONE_STATUSES)
        .exclude(purpose_type=COMPANION_VISIT_PURPOSE)
    )
    if exclude_activity_id:
        qs = qs.exclude(pk=exclude_activity_id)
    return qs.order_by("created_at").first()


def assert_not_duplicate_client_visit(school, **kwargs) -> None:
    existing = existing_same_day_visit(school, **kwargs)
    if existing is None:
        return
    day = kwargs["day"]
    raise BadRequest(
        f"{school.name} already has this visit on {day:%-d %b %Y}. Open that "
        "visit instead of planning a second one for the same day."
    )
