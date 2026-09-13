"""A Programme Lead's coaching of the officers they supervise (owner, 2026-09-13).

The Programme Lead's role description asks them to give "line-management,
supervision, leadership, and support to CCEOs" and to "participate in
performance reviews and professional coaching for assigned CCEOs". The
Regional Lead's engagement log (services.py) coaches Programme Leads; these
records carry the same practice one level down. Like an engagement, none of it
is planned work: no cost, no fund request, no calendar entry.

Who may do what:

* The Programme Lead records coaching for an officer on their team
  (apps.hr.team_roster.team_members), corrects it until the officer has
  acknowledged it, shares it, and closes the follow-up on the actions agreed.
  They read only what they wrote, and only for officers still on their team.
* The officer reads what was shared with them and acknowledges it with a
  response. Drafts stay with the lead who wrote them.
* The Country Director reads the shared coaching in their country, the
  Regional Lead the shared coaching in the countries of their region, and
  Admin everything. None of them writes.

The cadence is one monthly one-to-one with every officer each calendar month.
From the tenth an officer without one is due: the To-Do, the Coaching page and
the dashboard all read `monthly_one_to_ones`, so they agree.

Every write is audit-logged and every handoff notifies the person it hands to.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

from .models import OBSERVATION_CRITERIA, CceoCoaching, CoachingKind
from .services import (
    ADMIN,
    COUNTRY_DIRECTOR,
    PROGRAM_LEAD,
    REGIONAL_LEAD,
    _audit,
    _parse_date,
    _role,
    _staff_country,
    _staff_id,
    _uid,
    feedback_visible_to,
    reach_countries,
    training_label,
)

CCEO = "CCEO"

EVENT_SHARED = "cceo_coaching_shared"
EVENT_ACKNOWLEDGED = "cceo_coaching_acknowledged"

# The monthly one-to-one is due from this day of the month when not yet held.
ONE_TO_ONE_DUE_DAY = 10
# A draft older than this is a note the officer should already have.
DRAFT_REMINDER_DAYS = 2
# Work a lead can point a coaching record at: recent or imminent activities,
# and the field debriefs of the last two months.
ACTIVITY_LOOKBACK_DAYS = 120
ACTIVITY_LOOKAHEAD_DAYS = 14
DEBRIEF_LOOKBACK_DAYS = 60

# Kinds that watch the officer deliver and are rated on the observation
# rubric the Regional Lead uses (models.OBSERVATION_CRITERIA).
RATED_KINDS = (CoachingKind.FIELD_OBSERVATION, CoachingKind.TRAINING_OBSERVATION)
# Regional Lead feedback is never written by hand: it is passed on from an
# acknowledged observation (pass_feedback_to_cceo), with the ratings copied.
RECORDABLE_KINDS = tuple(
    kind for kind in CoachingKind.values if kind != CoachingKind.REGIONAL_FEEDBACK
)
KIND_LABELS = dict(CoachingKind.choices)

NOT_LIVE_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
)

# Register states, in the order a lead works them.
STATE_DRAFT = "draft"
STATE_AWAITING = "awaiting"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_FOLLOW_UP = "follow_up"
STATE_CHOICES = (
    (STATE_DRAFT, "Not shared yet"),
    (STATE_AWAITING, "Awaiting the officer"),
    (STATE_ACKNOWLEDGED, "Acknowledged"),
    (STATE_FOLLOW_UP, "Follow-up due"),
)


def _notify(event_type, *, title, body, record, recipients, priority="normal"):
    if not recipients:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="performance",
            priority=priority,
            title=title,
            body=body[:500],
            context_type="CceoCoaching",
            context_id=record.id,
            recipients=list(recipients),
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass


def _name(principal) -> str:
    return getattr(principal, "name", "") or "Your Programme Lead"


# ── The team and what the lead may read ──────────────────────────────────────
def _team(principal) -> list:
    from apps.hr.team_roster import team_members

    return team_members(principal)


def coaching_visible_to(principal, *, team_ids=None):
    """Coaching records a person may read (see the module docstring).

    `team_ids` lets a caller that already resolved a Programme Lead's team
    pass it in instead of resolving it again.
    """
    role = _role(principal)
    qs = CceoCoaching.objects.all()
    if role == ADMIN:
        return qs
    if role == PROGRAM_LEAD:
        if team_ids is None:
            team_ids = [member.id for member in _team(principal)]
        if not team_ids:
            return qs.none()
        return qs.filter(author_id=_uid(principal), cceo_staff_id__in=list(team_ids))
    shared = qs.filter(shared_at__isnull=False)
    if role == CCEO:
        staff_id = _staff_id(principal)
        mine = Q(cceo_user_id=_uid(principal))
        if staff_id:
            mine |= Q(cceo_staff_id=staff_id)
        return shared.filter(mine)
    if role == COUNTRY_DIRECTOR:
        country = _staff_country(principal)
        return shared.filter(country=country) if country else qs.none()
    if role == REGIONAL_LEAD:
        countries, _assigned = reach_countries(principal)
        return shared.filter(country__in=countries) if countries else qs.none()
    return qs.none()


def with_state(qs, state: str, *, today: date | None = None):
    """Narrow a coaching queryset to one register state."""
    today = today or timezone.localdate()
    if state == STATE_DRAFT:
        return qs.filter(shared_at__isnull=True)
    if state == STATE_AWAITING:
        return qs.filter(shared_at__isnull=False, acknowledged_at__isnull=True)
    if state == STATE_ACKNOWLEDGED:
        return qs.filter(acknowledged_at__isnull=False)
    if state == STATE_FOLLOW_UP:
        return qs.filter(follow_up_due__lte=today, follow_up_done_at__isnull=True)
    return qs


def state_of(record, *, today: date | None = None, officer_view=False):
    """A record's state as (label, tone) for a register cell."""
    today = today or timezone.localdate()
    if (
        record.follow_up_due
        and not record.follow_up_done_at
        and record.follow_up_due <= today
        and not officer_view
    ):
        return "Follow-up due", "danger"
    if record.acknowledged_at:
        return "Acknowledged", "success"
    if record.shared_at:
        return (
            ("Awaiting your acknowledgement", "warning")
            if officer_view
            else ("Awaiting the officer", "warning")
        )
    return "Not shared yet", "neutral"


def officer_for(principal, cceo_id: str):
    """The team member a lead names, by StaffProfile id or User id."""
    cceo_id = (cceo_id or "").strip()
    if not cceo_id:
        return None
    for member in _team(principal):
        if cceo_id in (member.id, member.user_id):
            return member
    return None


def _owner_ids(member) -> list[str]:
    return [i for i in (member.id, member.user_id) if i]


def officer_activities(members, *, today: date | None = None):
    """Recent or imminent activities the officers deliver or monitor."""
    from apps.activities.models import Activity

    today = today or timezone.localdate()
    owners = [i for member in members for i in _owner_ids(member)]
    if not owners:
        return Activity.objects.none()
    return (
        Activity.objects.filter(
            Q(responsible_staff_id__in=owners) | Q(monitored_by_staff_id__in=owners),
            deleted_at__isnull=True,
            planned_date__gte=today - timedelta(days=ACTIVITY_LOOKBACK_DAYS),
            planned_date__lte=today + timedelta(days=ACTIVITY_LOOKAHEAD_DAYS),
        )
        .exclude(status__in=NOT_LIVE_STATUSES)
        .select_related("school", "cluster")
        .order_by("-planned_date", "id")
    )


def officer_debriefs(members, *, today: date | None = None):
    """Field debriefs the officers submitted in the last two months."""
    from apps.debriefs.models import DailyDebrief

    today = today or timezone.localdate()
    user_ids = [member.user_id for member in members if member.user_id]
    if not user_ids:
        return DailyDebrief.objects.none()
    return DailyDebrief.objects.filter(
        submitted_by_user_id__in=user_ids,
        deleted_at__isnull=True,
        date__date__gte=today - timedelta(days=DEBRIEF_LOOKBACK_DAYS),
    ).order_by("-date", "id")


def debrief_label(debrief) -> str:
    when = f"{debrief.date:%-d %b}" if debrief.date else "Undated"
    return " · ".join(part for part in (when, debrief.title or "Field debrief") if part)


# ── Recording ────────────────────────────────────────────────────────────────
def _require_program_lead(principal):
    if _role(principal) != PROGRAM_LEAD:
        raise Forbidden("Only the officer's Programme Lead records coaching.")


def _clean(principal, data: dict, *, instance: CceoCoaching | None = None) -> dict:
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.debriefs.models import DailyDebrief

    if instance is None:
        member = officer_for(principal, data.get("cceo_staff_id"))
        if member is None:
            raise BadRequest("Choose an officer on your team.")
        kind = (data.get("kind") or "").strip()
        if kind not in RECORDABLE_KINDS:
            raise BadRequest("Choose what kind of coaching this was.")
    else:
        member = (
            StaffProfile.objects.select_related("user")
            .filter(id=instance.cceo_staff_id)
            .first()
        )
        if member is None:
            raise NotFoundError("The officer on this record no longer exists.")
        kind = instance.kind

    today = timezone.localdate()
    held_on = _parse_date(data.get("held_on"), "the date it was held")
    if held_on is None:
        raise BadRequest("Enter the date it was held.")
    if held_on > today:
        raise BadRequest(
            "Record coaching once it has happened: choose today or an earlier date."
        )
    follow_up_due = _parse_date(data.get("follow_up_due"), "the follow-up date")
    if follow_up_due and follow_up_due < held_on:
        raise BadRequest("The follow-up date cannot be before the coaching.")

    strengths = (data.get("strengths") or "").strip()
    growth_areas = (data.get("growth_areas") or "").strip()
    agreed_actions = (data.get("agreed_actions") or "").strip()
    if not (strengths or growth_areas or agreed_actions):
        raise BadRequest(
            "Write what the coaching covered: strengths, areas to grow or the actions agreed."
        )
    if follow_up_due and not agreed_actions:
        raise BadRequest("Write the actions agreed before setting a follow-up date.")

    owners = _owner_ids(member)
    activity = None
    activity_id = (data.get("activity_id") or "").strip()
    if activity_id:
        if instance is not None and instance.activity_id == activity_id:
            activity = instance.activity
        else:
            activity = (
                Activity.objects.filter(id=activity_id, deleted_at__isnull=True)
                .filter(
                    Q(responsible_staff_id__in=owners)
                    | Q(monitored_by_staff_id__in=owners)
                )
                .first()
            )
        if activity is None:
            raise BadRequest("Choose an activity this officer delivered or monitored.")
    if kind == CoachingKind.TRAINING_OBSERVATION and activity is None:
        raise BadRequest("Choose the training you observed.")

    debrief = None
    debrief_id = (data.get("debrief_id") or "").strip()
    if debrief_id:
        if instance is not None and instance.debrief_id == debrief_id:
            debrief = instance.debrief
        else:
            debrief = DailyDebrief.objects.filter(
                id=debrief_id,
                deleted_at__isnull=True,
                submitted_by_user_id=member.user_id,
            ).first()
        if debrief is None:
            raise BadRequest("Choose a field debrief this officer submitted.")

    ratings = {}
    if kind in RATED_KINDS:
        for field, label, _hint in OBSERVATION_CRITERIA:
            try:
                value = int(data.get(field))
            except (TypeError, ValueError):
                raise BadRequest(f"Rate “{label}” from 1 to 4.") from None
            if not 1 <= value <= 4:
                raise BadRequest(f"Rate “{label}” from 1 to 4.")
            ratings[field] = value
    elif instance is None:
        ratings = {field: None for field, _l, _h in OBSERVATION_CRITERIA}

    name = getattr(member.user, "name", "") or "officer"
    subject = (data.get("subject") or "").strip()[:255] or (
        f"{KIND_LABELS.get(kind, 'Coaching')} · {name}"
    )[:255]
    return {
        "member": member,
        "fields": {
            "kind": kind,
            "held_on": held_on,
            "fy": get_operational_fy(held_on),
            "country": member.country or "",
            "subject": subject,
            "strengths": strengths,
            "growth_areas": growth_areas,
            "agreed_actions": agreed_actions,
            "follow_up_due": follow_up_due,
            "activity": activity,
            "debrief": debrief,
            **ratings,
        },
    }


def record_coaching(principal, data: dict) -> CceoCoaching:
    _require_program_lead(principal)
    cleaned = _clean(principal, data)
    member = cleaned["member"]
    record = CceoCoaching.objects.create(
        author_id=_uid(principal),
        cceo_staff_id=member.id,
        cceo_user_id=member.user_id,
        **cleaned["fields"],
    )
    _audit(
        "cce.coaching_recorded",
        "CceoCoaching",
        record.id,
        principal,
        {
            "kind": record.kind,
            "cceo_staff_id": record.cceo_staff_id,
            "held_on": record.held_on.isoformat(),
        },
    )
    return record


def _own_record(principal, record_id: str, *, lock=False) -> CceoCoaching:
    qs = coaching_visible_to(principal).select_related("activity", "debrief")
    if lock:
        qs = qs.select_for_update(of=("self",))
    record = qs.filter(id=record_id).first()
    if record is None:
        raise NotFoundError("Coaching record not found.")
    if record.author_id != _uid(principal):
        raise Forbidden("Only the Programme Lead who wrote this coaching changes it.")
    return record


def update_coaching(principal, record_id: str, data: dict) -> CceoCoaching:
    """Correct a record until the officer has acknowledged it. A record the
    officer can already read tells them it changed."""
    _require_program_lead(principal)
    with transaction.atomic():
        record = _own_record(principal, record_id, lock=True)
        if record.acknowledged_at:
            raise Forbidden(
                "The officer has acknowledged this coaching, so it can no longer be changed."
            )
        cleaned = _clean(principal, data, instance=record)
        for field, value in cleaned["fields"].items():
            setattr(record, field, value)
        record.save()
        _audit("cce.coaching_updated", "CceoCoaching", record.id, principal)
    if record.shared_at:
        _notify(
            EVENT_SHARED,
            title=f"{_name(principal)} updated coaching notes shared with you",
            body=_notice_body(record),
            record=record,
            recipients=[record.cceo_user_id],
            priority="high",
        )
    return record


def _notice_body(record) -> str:
    parts = [f"{record.subject}."]
    if record.agreed_actions:
        parts.append(f"Agreed actions: {record.agreed_actions}")
    return " ".join(parts)


def share_coaching(principal, record_id: str) -> CceoCoaching:
    """Hand the record to the officer, who is asked to acknowledge it."""
    _require_program_lead(principal)
    with transaction.atomic():
        record = _own_record(principal, record_id, lock=True)
        if record.shared_at:
            raise BadRequest("This coaching was already shared with the officer.")
        record.shared_at = timezone.now()
        record.save(update_fields=["shared_at", "updated_at"])
        _audit(
            "cce.coaching_shared",
            "CceoCoaching",
            record.id,
            principal,
            {"cceo_staff_id": record.cceo_staff_id},
        )
    _notify(
        EVENT_SHARED,
        title=f"Coaching notes from {_name(principal)}",
        body=_notice_body(record),
        record=record,
        recipients=[record.cceo_user_id],
        priority="high",
    )
    return record


def acknowledge_coaching(principal, record_id: str, response: str) -> CceoCoaching:
    """The officer answers coaching shared with them."""
    if _role(principal) != CCEO:
        raise Forbidden("The officer the coaching was shared with acknowledges it.")
    response = (response or "").strip()
    if not response:
        raise BadRequest(
            "Say what you will do with this coaching: what you will keep, change or try."
        )
    with transaction.atomic():
        record = (
            coaching_visible_to(principal)
            .select_for_update()
            .filter(id=record_id)
            .first()
        )
        if record is None:
            raise NotFoundError("Coaching not found.")
        if record.acknowledged_at:
            raise BadRequest("You already acknowledged this coaching.")
        record.acknowledged_at = timezone.now()
        record.cceo_response = response
        record.save(update_fields=["acknowledged_at", "cceo_response", "updated_at"])
        _audit("cce.coaching_acknowledged", "CceoCoaching", record.id, principal)
    _notify(
        EVENT_ACKNOWLEDGED,
        title=f"{_name(principal)} acknowledged your coaching",
        body=f"{record.subject}. {response}",
        record=record,
        recipients=[record.author_id],
    )
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            EVENT_SHARED, "CceoCoaching", record.id, recipient_ids=[_uid(principal)]
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass
    return record


def complete_follow_up(principal, record_id: str, note: str) -> CceoCoaching:
    """The lead closes the follow-up on the actions agreed, saying what they
    found."""
    _require_program_lead(principal)
    note = (note or "").strip()
    if not note:
        raise BadRequest(
            "Say what you found when you followed up: done, in progress or not started."
        )
    with transaction.atomic():
        record = _own_record(principal, record_id, lock=True)
        if not record.follow_up_due:
            raise BadRequest("This coaching has no follow-up date to close.")
        if record.follow_up_done_at:
            raise BadRequest("This follow-up was already closed.")
        record.follow_up_done_at = timezone.now()
        record.follow_up_note = note
        record.save(update_fields=["follow_up_done_at", "follow_up_note", "updated_at"])
        _audit("cce.coaching_follow_up_closed", "CceoCoaching", record.id, principal)
    return record


# ── Regional Lead feedback, passed on ────────────────────────────────────────
def delivering_team_member(principal, activity):
    """The officer on this lead's team who delivered a training, if any.

    Partner-delivered trainings have no officer to pass feedback to: the
    Programme Lead takes that feedback up with the partner instead.
    """
    from apps.core.enums import DeliveryType

    if (
        activity is None
        or activity.delivery_type == DeliveryType.PARTNER
        or not activity.responsible_staff_id
    ):
        return None
    return officer_for(principal, activity.responsible_staff_id)


def pass_feedback_to_cceo(principal, engagement_id: str) -> CceoCoaching:
    """Pass the Regional Lead's acknowledged observation to the officer who
    delivered the training, as a shared coaching record with the ratings
    copied. The lead's response becomes the actions agreed."""
    _require_program_lead(principal)
    with transaction.atomic():
        engagement = (
            feedback_visible_to(principal)
            .select_for_update(of=("self",))
            .filter(id=engagement_id)
            .first()
        )
        if engagement is None:
            raise NotFoundError("Feedback not found.")
        if not engagement.acknowledged_at:
            raise BadRequest(
                "Acknowledge the Regional Lead's feedback before passing it on."
            )
        member = delivering_team_member(principal, engagement.activity)
        if member is None:
            raise BadRequest(
                "This training was not delivered by an officer on your team, so "
                "there is no one to pass the feedback to."
            )
        if CceoCoaching.objects.filter(
            source_engagement=engagement, cceo_staff_id=member.id
        ).exists():
            raise BadRequest("This feedback was already passed to the officer.")
        today = timezone.localdate()
        label = (
            training_label(engagement.activity)
            if engagement.activity_id
            else engagement.subject
        )
        record = CceoCoaching.objects.create(
            author_id=_uid(principal),
            cceo_staff_id=member.id,
            cceo_user_id=member.user_id,
            kind=CoachingKind.REGIONAL_FEEDBACK,
            held_on=today,
            fy=get_operational_fy(today),
            country=member.country or engagement.country or "",
            subject=f"Regional Lead feedback · {label}"[:255],
            growth_areas=engagement.feedback,
            agreed_actions=engagement.lead_response,
            activity=engagement.activity,
            source_engagement=engagement,
            shared_at=timezone.now(),
            **{
                field: getattr(engagement, field)
                for field, _l, _h in OBSERVATION_CRITERIA
            },
        )
        _audit(
            "cce.coaching_feedback_passed",
            "CceoCoaching",
            record.id,
            principal,
            {"source_engagement_id": engagement.id, "cceo_staff_id": member.id},
        )
    _notify(
        EVENT_SHARED,
        title=f"Regional Lead feedback passed on by {_name(principal)}",
        body=_notice_body(record),
        record=record,
        recipients=[record.cceo_user_id],
        priority="high",
    )
    return record


def passed_engagement_ids(engagement_ids) -> set[str]:
    """Which observations have already been passed on to an officer."""
    ids = [i for i in engagement_ids if i]
    if not ids:
        return set()
    return set(
        CceoCoaching.objects.filter(source_engagement_id__in=ids).values_list(
            "source_engagement_id", flat=True
        )
    )


def _count_filters(today: date) -> dict:
    return {
        "drafts": Count("id", filter=Q(shared_at__isnull=True)),
        "awaiting": Count(
            "id", filter=Q(shared_at__isnull=False, acknowledged_at__isnull=True)
        ),
        "acknowledged": Count("id", filter=Q(acknowledged_at__isnull=False)),
        "follow_ups_due": Count(
            "id", filter=Q(follow_up_due__lte=today, follow_up_done_at__isnull=True)
        ),
        "follow_ups_open": Count(
            "id",
            filter=Q(follow_up_due__isnull=False, follow_up_done_at__isnull=True),
        ),
    }


def coaching_counts(visible, *, today: date | None = None) -> dict:
    """Drafts, records awaiting the officer, acknowledged records, follow-ups
    due (date arrived, not closed) and follow-ups open, in one query."""
    today = today or timezone.localdate()
    return visible.order_by().aggregate(**_count_filters(today))


def per_officer_counts(visible, *, today: date | None = None) -> dict[str, dict]:
    """The same counts per officer StaffProfile id, in one grouped query."""
    today = today or timezone.localdate()
    return {
        row.pop("cceo_staff_id"): row
        for row in visible.order_by()
        .values("cceo_staff_id")
        .annotate(**_count_filters(today))
    }


# ── Cadence and summaries ────────────────────────────────────────────────────
def _month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def monthly_one_to_ones(principal, *, today: date | None = None, members=None) -> dict:
    """This month's one-to-one with each officer on the lead's team.

    An officer is `held` once a one-to-one dated this month exists for them,
    whoever wrote it — a covering lead's conversation counts — and `due` from
    the tenth when none does. One query for the whole team.
    """
    today = today or timezone.localdate()
    members = list(_team(principal) if members is None else members)
    start, end = _month_bounds(today)
    due_from = start.replace(day=ONE_TO_ONE_DUE_DAY)
    held = (
        dict(
            CceoCoaching.objects.filter(
                kind=CoachingKind.ONE_TO_ONE,
                cceo_staff_id__in=[m.id for m in members],
                held_on__gte=start,
                held_on__lt=end,
            )
            .order_by()
            .values_list("cceo_staff_id")
            .annotate(last=Max("held_on"))
        )
        if members
        else {}
    )
    rows = []
    for member in members:
        held_on = held.get(member.id)
        if held_on:
            state, label, tone = "held", f"Held {held_on:%-d %b}", "success"
        elif today >= due_from:
            state, label, tone = "due", "Due", "danger"
        else:
            state, label, tone = (
                "not_yet",
                f"Due from {due_from:%-d %b}",
                "neutral",
            )
        rows.append(
            {
                "staff_id": member.id,
                "user_id": member.user_id,
                "name": getattr(member.user, "name", "") or "Officer",
                "held_on": held_on,
                "state": state,
                "state_label": label,
                "tone": tone,
            }
        )
    return {
        "month": start,
        "month_end": end - timedelta(days=1),
        "due_from": due_from,
        "rows": rows,
        "held": sum(1 for r in rows if r["state"] == "held"),
        "due": sum(1 for r in rows if r["state"] == "due"),
    }


def last_coaching_by_cceo(
    principal, cceo_staff_ids, *, team_ids=None
) -> dict[str, dict]:
    """Per officer StaffProfile id: the latest coaching record the principal may
    read — {"held_on", "kind", "kind_label", "shared", "acknowledged",
    "open_follow_up"}. Officers never coached are absent.

    `open_follow_up` is true when any of the officer's readable records has a
    follow-up that is not closed, not only the latest. Two queries whatever
    the number of officers (plus the team, unless `team_ids` is passed).
    """
    ids = sorted({str(i) for i in (cceo_staff_ids or ()) if i})
    if not ids:
        return {}
    visible = coaching_visible_to(principal, team_ids=team_ids).filter(
        cceo_staff_id__in=ids
    )
    latest = (
        visible.order_by("cceo_staff_id", "-held_on", "-created_at")
        .distinct("cceo_staff_id")
        .values(
            "cceo_staff_id",
            "held_on",
            "kind",
            "shared_at",
            "acknowledged_at",
        )
    )
    open_follow_ups = dict(
        visible.filter(follow_up_due__isnull=False, follow_up_done_at__isnull=True)
        .order_by()
        .values_list("cceo_staff_id")
        .annotate(n=Count("id"))
    )
    return {
        row["cceo_staff_id"]: {
            "held_on": row["held_on"],
            "kind": row["kind"],
            "kind_label": KIND_LABELS.get(row["kind"], row["kind"]),
            "shared": row["shared_at"] is not None,
            "acknowledged": row["acknowledged_at"] is not None,
            "open_follow_up": bool(open_follow_ups.get(row["cceo_staff_id"])),
        }
        for row in latest
    }


def coaching_summary(principal, today=None) -> dict:
    """The lead's coaching at a glance: {"team_size", "coached_this_month",
    "awaiting_acknowledgement", "follow_ups_due", "drafts"}, plus
    "one_to_ones_due".

    For a Programme Lead `coached_this_month` counts the officers whose
    monthly one-to-one is held, so it agrees with the "Hold … one-to-one"
    To-Dos. For anyone else the counts cover the records they may read.
    """
    today = today or timezone.localdate()
    team_ids = None
    one_to_ones = None
    if _role(principal) == PROGRAM_LEAD:
        members = _team(principal)
        team_ids = [m.id for m in members]
        one_to_ones = monthly_one_to_ones(principal, today=today, members=members)
    visible = coaching_visible_to(principal, team_ids=team_ids)
    counts = coaching_counts(visible, today=today)
    if one_to_ones is not None:
        coached = one_to_ones["held"]
        due = one_to_ones["due"]
    else:
        start, end = _month_bounds(today)
        coached = (
            visible.filter(
                kind=CoachingKind.ONE_TO_ONE, held_on__gte=start, held_on__lt=end
            )
            .order_by()
            .values("cceo_staff_id")
            .distinct()
            .count()
        )
        due = 0
    return {
        "team_size": len(team_ids) if team_ids is not None else 0,
        "coached_this_month": coached,
        "awaiting_acknowledgement": counts["awaiting"],
        "follow_ups_due": counts["follow_ups_due"],
        "drafts": counts["drafts"],
        "one_to_ones_due": due,
    }
