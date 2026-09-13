"""Priority guidance a Programme Lead issues to their officers (owner, 2026-09-13).

The Programme Lead's role description opens with "Strategic Direction — lead
priority setting, planning, and communication for CCE initiatives at the
country level". The country priorities are set above the lead (the RVP and the
Country Director) and distributed as targets (Impact Assessment, then the lead
among the team); what the lead adds is the communication: what the team should
do about a priority this term and the change expected in the schools. Before
this module that lived in meetings and chat groups, with no record of who had
heard it.

Who may do what:

* The Programme Lead drafts guidance (title, the instruction, the change
  expected, an optional country priority or milestone it serves, an optional
  review date) for every officer on their team or for the ones they choose
  (apps.hr.team_roster.team_members), corrects it while it is a draft, issues
  it, reviews the responses once the review date arrives, and withdraws it.
  They read only what they wrote.
* Each officer it was issued to reads it on their Priorities page and
  acknowledges it with a response — what they will do. Drafts and withdrawn
  guidance never reach them.
* Admin reads everything and writes nothing.

Issuing notifies each officer (team_guidance_issued → /priorities); an
acknowledgement notifies the lead (team_guidance_acknowledged →
/priorities/guidance). The To-Dos in guidance_todos.py are derived from the
same records, so they close the moment the work is done.

Every write is audit-logged.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

from .models import TeamGuidance, TeamGuidanceReceipt
from .services import ADMIN, PROGRAM_LEAD, _audit, _parse_date, _role, _uid

CCEO = "CCEO"

EVENT_ISSUED = "team_guidance_issued"
EVENT_ACKNOWLEDGED = "team_guidance_acknowledged"

LEAD_URL = "/priorities/guidance"
OFFICER_URL = "/priorities"

# Register states, in the order a lead works them.
STATE_DRAFT = "draft"
STATE_AWAITING = "awaiting"
STATE_ACKNOWLEDGED = "acknowledged"
STATE_REVIEW = "review"
STATE_WITHDRAWN = "withdrawn"
STATE_CHOICES = (
    (STATE_DRAFT, "Draft, not issued"),
    (STATE_AWAITING, "Awaiting officers"),
    (STATE_ACKNOWLEDGED, "Acknowledged by every officer"),
    (STATE_REVIEW, "Review due"),
    (STATE_WITHDRAWN, "Withdrawn"),
)

TITLE_MAX = 200


def _notify(event_type, *, title, body, guidance, recipients, priority="normal"):
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
            context_type="TeamGuidance",
            context_id=guidance.id,
            recipients=list(recipients),
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass


def _resolve_notices(event_type, guidance_id, recipient_ids=None):
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            event_type, "TeamGuidance", guidance_id, recipient_ids=recipient_ids
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass


def _name(principal) -> str:
    return getattr(principal, "name", "") or "Your Programme Lead"


def _team(principal) -> list:
    from apps.hr.team_roster import team_members

    return team_members(principal)


def _require_program_lead(principal):
    if _role(principal) != PROGRAM_LEAD:
        raise Forbidden("Only a Programme Lead issues guidance to their officers.")


# ── What each person may read ────────────────────────────────────────────────
def guidance_visible_to(principal):
    """Guidance a person may read in the lead's register: their own as a
    Programme Lead, everything for Admin, nothing for anyone else (an
    officer reads their receipts through `receipts_for_officer`)."""
    role = _role(principal)
    qs = TeamGuidance.objects.all()
    if role == ADMIN:
        return qs
    if role == PROGRAM_LEAD:
        return qs.filter(author_id=_uid(principal))
    return qs.none()


def _officer_match(principal) -> Q:
    mine = Q(recipient_user_id=_uid(principal))
    staff_id = getattr(principal, "staff_profile_id", None)
    if staff_id:
        mine |= Q(recipient_staff_id=str(staff_id))
    return mine


def receipts_for_officer(principal):
    """The officer's receipts for guidance that reached them and still
    stands: issued and not withdrawn."""
    if _role(principal) != CCEO:
        return TeamGuidanceReceipt.objects.none()
    return TeamGuidanceReceipt.objects.filter(
        _officer_match(principal),
        guidance__issued_at__isnull=False,
        guidance__withdrawn_at__isnull=True,
    )


def with_receipt_counts(qs):
    """Annotate recipients and acknowledgements in the same query."""
    return qs.annotate(
        recipient_count=Count("receipts", distinct=True),
        acknowledged_count=Count(
            "receipts",
            filter=Q(receipts__acknowledged_at__isnull=False),
            distinct=True,
        ),
    )


def with_state(qs, state: str, *, today: date | None = None):
    """Narrow a guidance queryset to one register state. Awaiting and
    acknowledged read the annotations `with_receipt_counts` adds."""
    today = today or timezone.localdate()
    live = Q(issued_at__isnull=False, withdrawn_at__isnull=True)
    if state == STATE_DRAFT:
        return qs.filter(issued_at__isnull=True, withdrawn_at__isnull=True)
    if state == STATE_WITHDRAWN:
        return qs.filter(withdrawn_at__isnull=False)
    review_due = Q(review_on__isnull=False, review_on__lte=today)
    if state == STATE_REVIEW:
        return qs.filter(live & review_due)
    # A piece whose review date has arrived reads "Review due" in the register
    # (state_of), so the awaiting and acknowledged filters leave it out: the
    # filter and the State column always agree.
    if state == STATE_AWAITING:
        return (
            qs.filter(live)
            .exclude(review_due)
            .filter(acknowledged_count__lt=F("recipient_count"))
        )
    if state == STATE_ACKNOWLEDGED:
        return (
            qs.filter(live, recipient_count__gt=0)
            .exclude(review_due)
            .filter(acknowledged_count=F("recipient_count"))
        )
    return qs


def state_of(guidance, *, today: date | None = None) -> tuple[str, str]:
    """A guidance record's state as (label, tone) for a register cell. Reads
    the counts `with_receipt_counts` annotates."""
    today = today or timezone.localdate()
    if guidance.withdrawn_at:
        return "Withdrawn", "neutral"
    if not guidance.issued_at:
        return "Draft, not issued", "neutral"
    if guidance.review_on and guidance.review_on <= today:
        return "Review due", "danger"
    recipients = getattr(guidance, "recipient_count", 0)
    acknowledged = getattr(guidance, "acknowledged_count", 0)
    if recipients and acknowledged >= recipients:
        return "Acknowledged by every officer", "success"
    return "Awaiting officers", "warning"


# ── Options the drawer offers ────────────────────────────────────────────────
def priority_choices(principal, fy: str):
    """The country priorities of the year and their milestones, for the
    lead's country when it has its own plan (else every country plan)."""
    from apps.hr.models import PriorityMilestone, StrategicPriority

    country = _country_of(principal)
    priorities = StrategicPriority.objects.filter(
        fy=fy, level="country", cycle__isnull=False
    )
    if country and priorities.filter(country_id=country).exists():
        priorities = priorities.filter(country_id=country)
    priorities = list(priorities.order_by("sequence", "title"))
    milestones = list(
        PriorityMilestone.objects.filter(priority__in=priorities)
        .select_related("priority")
        .order_by("priority__sequence", "source_order", "title")
    )
    return priorities, milestones


def _is_offered(principal, priority) -> bool:
    """Whether the drawer offers this priority to the lead: the same rule as
    `priority_choices` — their own country's plan when it has one for that
    year, else any country plan. A posted id outside it is refused, so a lead
    cannot tie guidance to another country's priority by editing the form."""
    from apps.hr.models import StrategicPriority

    country = _country_of(principal)
    if not country or (priority.country_id or "") == country:
        return True
    return not StrategicPriority.objects.filter(
        fy=priority.fy, level="country", cycle__isnull=False, country_id=country
    ).exists()


# ── Writing ──────────────────────────────────────────────────────────────────
def _clean(principal, data: dict, *, instance: TeamGuidance | None = None) -> dict:
    from apps.hr.models import PriorityMilestone, StrategicPriority

    title = (data.get("title") or "").strip()
    if not title:
        raise BadRequest("Give the guidance a title the officers will recognise.")
    if len(title) > TITLE_MAX:
        raise BadRequest(f"Keep the title to {TITLE_MAX} characters.")
    instruction = (data.get("instruction") or "").strip()
    if not instruction:
        raise BadRequest("Write the instruction: what the officers should do.")
    expected_change = (data.get("expected_change") or "").strip()

    fy = (data.get("fy") or "").strip()
    if not (fy.isdigit() and len(fy) == 4):
        fy = instance.fy if instance is not None else get_operational_fy()

    priority = None
    priority_id = (data.get("priority_id") or "").strip()
    if priority_id:
        priority = StrategicPriority.objects.filter(
            id=priority_id, level="country", cycle__isnull=False
        ).first()
        if priority is None:
            raise BadRequest("Choose a country priority from the list.")
    milestone = None
    milestone_id = (data.get("milestone_id") or "").strip()
    if milestone_id:
        milestone = (
            PriorityMilestone.objects.select_related("priority")
            .filter(
                id=milestone_id,
                priority__level="country",
                priority__cycle__isnull=False,
            )
            .first()
        )
        if milestone is None:
            raise BadRequest("Choose a milestone from the list.")
        if priority is not None and milestone.priority_id != priority.id:
            raise BadRequest(
                "The milestone belongs to a different priority. Choose the "
                "milestone's own priority, or leave the priority empty."
            )
        priority = milestone.priority
    if priority is not None:
        if not _is_offered(principal, priority):
            raise BadRequest("Choose a priority from your country's plan.")
        fy = priority.fy

    today = timezone.localdate()
    review_on = _parse_date(data.get("review_on"), "the review date")
    if (
        review_on
        and review_on < today
        and (instance is None or instance.review_on != review_on)
    ):
        raise BadRequest("Choose a review date from today onwards.")

    members = _team(principal)
    by_id = {}
    for member in members:
        by_id[str(member.id)] = member
        if member.user_id:
            by_id[str(member.user_id)] = member
    if data.get("all_officers") in ("1", "on", "true", True):
        recipients = list(members)
    else:
        raw = data.get("recipients") or []
        if isinstance(raw, str):
            raw = [raw]
        recipients = []
        for value in raw:
            member = by_id.get(str(value).strip())
            if member is None:
                if str(value).strip():
                    raise BadRequest("Choose officers on your team.")
                continue
            if member not in recipients:
                recipients.append(member)
    if not recipients:
        raise BadRequest(
            "Choose the officers this guidance is for, or send it to every "
            "officer on your team."
            if members
            else "No officers are assigned to you yet, so there is nobody to guide."
        )
    return {
        "recipients": recipients,
        "fields": {
            "title": title,
            "instruction": instruction,
            "expected_change": expected_change,
            "fy": fy,
            "priority": priority,
            "milestone": milestone,
            "review_on": review_on,
        },
    }


def _country_of(principal) -> str:
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=_uid(principal))
        .values_list("country", flat=True)
        .first()
        or ""
    ).strip()


def _set_recipients(guidance: TeamGuidance, recipients) -> None:
    keep = {str(member.id) for member in recipients}
    guidance.receipts.exclude(recipient_staff_id__in=keep).delete()
    existing = set(guidance.receipts.values_list("recipient_staff_id", flat=True))
    TeamGuidanceReceipt.objects.bulk_create(
        [
            TeamGuidanceReceipt(
                guidance=guidance,
                recipient_staff_id=str(member.id),
                recipient_user_id=str(member.user_id or ""),
            )
            for member in recipients
            if str(member.id) not in existing
        ]
    )


def draft_guidance(principal, data: dict) -> TeamGuidance:
    """Write guidance as a draft; `data["issue"]` issues it straight away."""
    _require_program_lead(principal)
    cleaned = _clean(principal, data)
    with transaction.atomic():
        guidance = TeamGuidance.objects.create(
            author_id=_uid(principal),
            country=_country_of(principal),
            **cleaned["fields"],
        )
        _set_recipients(guidance, cleaned["recipients"])
        _audit(
            "cce.team_guidance_drafted",
            "TeamGuidance",
            guidance.id,
            principal,
            {
                "fy": guidance.fy,
                "recipients": [str(m.id) for m in cleaned["recipients"]],
                "priority_id": guidance.priority_id,
                "milestone_id": guidance.milestone_id,
            },
        )
    if data.get("issue") in ("1", "on", "true", True):
        return issue_guidance(principal, guidance.id)
    return guidance


def _own_guidance(principal, guidance_id: str, *, lock=False) -> TeamGuidance:
    qs = guidance_visible_to(principal)
    if lock:
        qs = qs.select_for_update(of=("self",))
    guidance = qs.filter(id=guidance_id).first()
    if guidance is None:
        raise NotFoundError("Guidance not found.")
    if guidance.author_id != _uid(principal):
        raise Forbidden("Only the Programme Lead who wrote this guidance changes it.")
    return guidance


def update_guidance(principal, guidance_id: str, data: dict) -> TeamGuidance:
    """Correct a draft. Issued guidance is what the officers were told, so it
    is withdrawn and reissued rather than changed under them."""
    _require_program_lead(principal)
    with transaction.atomic():
        guidance = _own_guidance(principal, guidance_id, lock=True)
        if guidance.withdrawn_at:
            raise BadRequest("This guidance was withdrawn.")
        if guidance.issued_at:
            raise BadRequest(
                "This guidance has reached the officers, so it can no longer be "
                "changed. Withdraw it and issue new guidance instead."
            )
        cleaned = _clean(principal, data, instance=guidance)
        for field, value in cleaned["fields"].items():
            setattr(guidance, field, value)
        guidance.save()
        _set_recipients(guidance, cleaned["recipients"])
        _audit(
            "cce.team_guidance_updated",
            "TeamGuidance",
            guidance.id,
            principal,
            {"recipients": [str(m.id) for m in cleaned["recipients"]]},
        )
    if data.get("issue") in ("1", "on", "true", True):
        return issue_guidance(principal, guidance.id)
    return guidance


def issue_guidance(principal, guidance_id: str) -> TeamGuidance:
    """Send a draft to its officers. An officer who has left the team since
    it was drafted is dropped; guidance left with nobody is refused."""
    _require_program_lead(principal)
    with transaction.atomic():
        guidance = _own_guidance(principal, guidance_id, lock=True)
        if guidance.withdrawn_at:
            raise BadRequest("This guidance was withdrawn.")
        if guidance.issued_at:
            raise BadRequest("This guidance was already issued.")
        team_ids = {str(member.id) for member in _team(principal)}
        dropped = guidance.receipts.exclude(recipient_staff_id__in=team_ids)
        dropped_count = dropped.count()
        if dropped_count:
            dropped.delete()
        recipients = list(guidance.receipts.values_list("recipient_user_id", flat=True))
        if not recipients:
            raise BadRequest(
                "None of the officers chosen for this guidance is on your team "
                "any more. Edit the draft and choose who it is for."
            )
        guidance.issued_at = timezone.now()
        guidance.save(update_fields=["issued_at", "updated_at"])
        _audit(
            "cce.team_guidance_issued",
            "TeamGuidance",
            guidance.id,
            principal,
            {"recipients": len(recipients), "dropped": dropped_count},
        )
    body = guidance.instruction
    if guidance.review_on:
        body = f"{body} Review on {guidance.review_on:%-d %B %Y}."
    _notify(
        EVENT_ISSUED,
        title=f"Guidance from {_name(principal)}: {guidance.title}",
        body=body,
        guidance=guidance,
        recipients=[uid for uid in recipients if uid],
        priority="high",
    )
    return guidance


def acknowledge_guidance(principal, guidance_id: str, response: str):
    """The officer answers guidance issued to them."""
    if _role(principal) != CCEO:
        raise Forbidden("The officer the guidance was issued to acknowledges it.")
    response = (response or "").strip()
    if not response:
        raise BadRequest(
            "Say what you will do with this guidance: the change you will make "
            "and where."
        )
    with transaction.atomic():
        receipt = (
            receipts_for_officer(principal)
            .select_for_update(of=("self",))
            .select_related("guidance")
            .filter(guidance_id=guidance_id)
            .first()
        )
        if receipt is None:
            raise NotFoundError("Guidance not found.")
        if receipt.acknowledged_at:
            raise BadRequest("You already acknowledged this guidance.")
        receipt.acknowledged_at = timezone.now()
        receipt.response = response
        receipt.save(update_fields=["acknowledged_at", "response", "updated_at"])
        guidance = receipt.guidance
        _audit(
            "cce.team_guidance_acknowledged",
            "TeamGuidance",
            guidance.id,
            principal,
            {"receipt_id": receipt.id},
        )
    _notify(
        EVENT_ACKNOWLEDGED,
        title=f"{_name(principal)} acknowledged your guidance",
        body=f"{guidance.title}. {response}",
        guidance=guidance,
        recipients=[guidance.author_id],
    )
    _resolve_notices(EVENT_ISSUED, guidance.id, recipient_ids=[_uid(principal)])
    return receipt


def review_guidance(principal, guidance_id: str, next_review) -> TeamGuidance:
    """The lead has read the responses: set the next review date, or leave it
    empty when no further review is planned. Either closes the review To-Do."""
    _require_program_lead(principal)
    next_review = _parse_date(next_review, "the next review date")
    today = timezone.localdate()
    if next_review and next_review <= today:
        raise BadRequest("Choose a next review date after today, or leave it empty.")
    with transaction.atomic():
        guidance = _own_guidance(principal, guidance_id, lock=True)
        if guidance.withdrawn_at or not guidance.issued_at:
            raise BadRequest("Only issued guidance that still stands is reviewed.")
        if not guidance.review_on or guidance.review_on > today:
            raise BadRequest("This guidance is not due for review yet.")
        previous = guidance.review_on
        guidance.review_on = next_review
        guidance.save(update_fields=["review_on", "updated_at"])
        _audit(
            "cce.team_guidance_reviewed",
            "TeamGuidance",
            guidance.id,
            principal,
            {
                "reviewed_due": previous.isoformat() if previous else None,
                "next_review": next_review.isoformat() if next_review else None,
            },
        )
    _resolve_notices(EVENT_ACKNOWLEDGED, guidance.id, recipient_ids=[_uid(principal)])
    return guidance


def withdraw_guidance(principal, guidance_id: str) -> TeamGuidance:
    """Take guidance back: it leaves every officer's Priorities page and
    their To-Do queue, and its open notices close."""
    _require_program_lead(principal)
    with transaction.atomic():
        guidance = _own_guidance(principal, guidance_id, lock=True)
        if guidance.withdrawn_at:
            raise BadRequest("This guidance was already withdrawn.")
        guidance.withdrawn_at = timezone.now()
        guidance.save(update_fields=["withdrawn_at", "updated_at"])
        _audit(
            "cce.team_guidance_withdrawn",
            "TeamGuidance",
            guidance.id,
            principal,
            {"was_issued": bool(guidance.issued_at)},
        )
    _resolve_notices([EVENT_ISSUED, EVENT_ACKNOWLEDGED], guidance.id)
    return guidance


# ── Reading ──────────────────────────────────────────────────────────────────
def receipts_by_guidance(guidance_ids) -> dict[str, list]:
    """Every receipt of the given guidance with the officer's name, in one
    query."""
    out: dict[str, list] = {}
    ids = [gid for gid in guidance_ids if gid]
    if not ids:
        return out
    from apps.accounts.models import StaffProfile

    receipts = list(
        TeamGuidanceReceipt.objects.filter(guidance_id__in=ids).order_by("created_at")
    )
    names = dict(
        StaffProfile.objects.filter(
            id__in={r.recipient_staff_id for r in receipts}
        ).values_list("id", "user__name")
    )
    for receipt in receipts:
        receipt.recipient_name = names.get(receipt.recipient_staff_id) or "Officer"
        out.setdefault(receipt.guidance_id, []).append(receipt)
    return out


def guidance_counts(visible, *, today: date | None = None) -> dict:
    """The register's headline counts over one queryset, in one query."""
    today = today or timezone.localdate()
    live = Q(issued_at__isnull=False, withdrawn_at__isnull=True)
    guidance = visible.aggregate(
        issued=Count("id", filter=live, distinct=True),
        drafts=Count("id", filter=Q(issued_at__isnull=True, withdrawn_at__isnull=True)),
        reviews_due=Count("id", filter=live & Q(review_on__lte=today), distinct=True),
    )
    receipts = TeamGuidanceReceipt.objects.filter(
        guidance__in=visible.filter(live).values("id")
    ).aggregate(
        acknowledged=Count("id", filter=Q(acknowledged_at__isnull=False)),
        awaiting=Count("id", filter=Q(acknowledged_at__isnull=True)),
    )
    return {
        "issued": guidance["issued"] or 0,
        "drafts": guidance["drafts"] or 0,
        "reviews_due": guidance["reviews_due"] or 0,
        "acknowledged": receipts["acknowledged"] or 0,
        "awaiting": receipts["awaiting"] or 0,
    }


def guidance_summary(principal) -> dict:
    """The Programme Lead dashboard's guidance card: every live piece of
    guidance the lead wrote, in any year.

    issued — guidance issued and not withdrawn; open — of those, the ones at
    least one officer has not acknowledged; acknowledged / awaiting —
    receipts on issued guidance; latest — the five most recent pieces,
    drafts included, with their acknowledgement count.
    """
    empty = {"issued": 0, "open": 0, "acknowledged": 0, "awaiting": 0, "latest": []}
    if _role(principal) != PROGRAM_LEAD:
        return empty
    visible = guidance_visible_to(principal).filter(withdrawn_at__isnull=True)
    counts = guidance_counts(visible)
    annotated = with_receipt_counts(visible)
    open_count = (
        annotated.filter(issued_at__isnull=False)
        .filter(acknowledged_count__lt=F("recipient_count"))
        .count()
    )
    latest = [
        {
            "id": row.id,
            "title": row.title,
            "issued_at": row.issued_at,
            "acknowledged": row.acknowledged_count,
            "recipients": row.recipient_count,
        }
        for row in annotated.order_by("-created_at")[:5]
    ]
    return {
        "issued": counts["issued"],
        "open": open_count,
        "acknowledged": counts["acknowledged"],
        "awaiting": counts["awaiting"],
        "latest": latest,
    }
