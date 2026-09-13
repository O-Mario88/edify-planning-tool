"""Partnership and capacity-building work with training organisations
(owner, 2026-09-13).

The Programme Lead "partners with regional leads, country directors, and local
training organizations to align goals and build capacity". Partner Oversight
tracks what a partner delivers; this log records the meetings, orientations
and quality follow-ups that improve how they deliver, the improvements agreed,
and whether they were followed up.

Who may do what:

* The Programme Lead and the Country Director record engagements with any
  active training partner, change their own records until the follow-up is
  closed or the record is shared with the partner, close the follow-up with a
  note, and optionally share the record with the partner organisation (its
  login is notified and reads it on its own profile).
* A Programme Lead reads the engagements they recorded; the Country Director
  reads every engagement in their country (every country when none is on
  their staff profile — the platform's country boundary); the Regional
  Programme Lead reads the countries of their region; Admin reads all.
* A partner login reads the engagements shared with its own organisation.
* Nobody writes on another person's record.

An engagement may name the Regional Lead's training observation that prompted
it. An observation of a partner-delivered training that recommends
strengthening or replacing it stays open, for the Programme Lead it was shared
with, until someone records an engagement with that partner on or after the
day it was observed (`open_observation_follow_ups`, the To-Do and the
Partner Oversight notice read it).

Every write is audit-logged.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

from .models import Partner, PartnerEngagement, PartnerEngagementKind

PROGRAM_LEAD = "Program Lead"
COUNTRY_DIRECTOR = "CountryDirector"
REGIONAL_LEAD = "RegionalProgramLead"
ADMIN = "Admin"
PARTNER_ROLES = ("PartnerAdmin", "PartnerFieldOfficer")

# The roles that engage a training partner on Edify's behalf.
RECORDER_ROLES = (PROGRAM_LEAD, COUNTRY_DIRECTOR)

EVENT_SHARED = "partner_engagement_shared"

KIND_LABELS = dict(PartnerEngagementKind.choices)

# The Regional Lead's recommendations that ask for work with the partner.
PARTNER_ACTION_RECOMMENDATIONS = ("strengthen", "replace")

# How many observations the drawer offers to link; the newest first.
OBSERVATION_OPTIONS_LIMIT = 50


def _uid(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _staff_country(principal) -> str:
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=_uid(principal))
        .values_list("country", flat=True)
        .first()
        or ""
    ).strip()


def _parse_date(value, label: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise BadRequest(f"Enter {label} as a date.") from exc


def _audit(action: str, engagement: PartnerEngagement, principal, payload=None):
    audit_log(
        action=action,
        subject_kind="PartnerEngagement",
        subject_id=engagement.id,
        actor_id=_uid(principal),
        actor_role=_role(principal),
        payload={"partner_id": engagement.partner_id, **(payload or {})},
    )


# ── Visibility ───────────────────────────────────────────────────────────────
def can_record(principal) -> bool:
    return _role(principal) in RECORDER_ROLES


def engagements_visible_to(principal):
    """The engagements a person may read (see the module docstring)."""
    role = _role(principal)
    qs = PartnerEngagement.objects.select_related("partner", "source_engagement")
    if role == ADMIN:
        return qs
    if role == PROGRAM_LEAD:
        return qs.filter(author_id=_uid(principal))
    if role == COUNTRY_DIRECTOR:
        country = _staff_country(principal)
        return qs.filter(country=country) if country else qs
    if role == REGIONAL_LEAD:
        from apps.cce_leadership.services import reach_countries

        countries, _assigned = reach_countries(principal)
        return qs.filter(country__in=countries) if countries else qs.none()
    if role in PARTNER_ROLES:
        from apps.core.scoping import resolve_partner_ids

        return qs.filter(
            partner_id__in=resolve_partner_ids(principal),
            shared_with_partner_at__isnull=False,
        )
    return qs.none()


def recordable_partners(principal) -> list[Partner]:
    """The training partners an engagement may be recorded with: every active
    organisation in the directory (partners are not country-bound yet)."""
    if not can_record(principal):
        return []
    return list(
        Partner.objects.filter(deleted_at__isnull=True, active_status=True).order_by(
            "name"
        )[:500]
    )


def linkable_observations(principal, partner_id: str | None = None):
    """Regional Lead observations of partner-delivered trainings the reader
    may read, newest first — the ones an engagement can answer."""
    from apps.cce_leadership.services import feedback_visible_to
    from apps.core.enums import DeliveryType

    qs = feedback_visible_to(principal).filter(
        activity__delivery_type=DeliveryType.PARTNER,
        activity__assigned_partner_id__isnull=False,
    )
    if partner_id:
        qs = qs.filter(activity__assigned_partner_id=partner_id)
    return qs.order_by("-held_on", "-created_at")


# ── Writes ───────────────────────────────────────────────────────────────────
def _require_recorder(principal) -> None:
    if not can_record(principal):
        raise Forbidden(
            "Only a Programme Lead or the Country Director records partner engagements."
        )


def _clean(principal, data: dict, *, instance: PartnerEngagement | None = None):
    kind = (data.get("kind") or "").strip()
    if kind not in PartnerEngagementKind.values:
        raise BadRequest("Choose what kind of engagement this was.")

    partner_id = (data.get("partner_id") or "").strip()
    if instance is not None and not partner_id:
        partner_id = instance.partner_id
    partner = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if partner is None:
        raise BadRequest("Choose the training partner you engaged.")
    if (
        instance is None or instance.partner_id != partner.id
    ) and not partner.active_status:
        raise BadRequest(f"{partner.name} is inactive; choose an active partner.")

    today = timezone.localdate()
    held_on = _parse_date(data.get("held_on"), "the date it was held")
    if held_on is None:
        raise BadRequest("Enter the date it was held.")
    if held_on > today:
        raise BadRequest(
            "Record an engagement once it has happened: choose today or an earlier date."
        )
    follow_up_due = _parse_date(data.get("follow_up_due"), "the follow-up date")
    if follow_up_due and follow_up_due < held_on:
        raise BadRequest("The follow-up date cannot be before the engagement.")

    subject = (data.get("subject") or "").strip()[:255]
    if not subject:
        raise BadRequest("Give the engagement a subject.")
    agreed = (data.get("agreed_improvements") or "").strip()
    if follow_up_due and not agreed:
        raise BadRequest(
            "Say which improvements were agreed — the follow-up checks on them."
        )

    source = None
    source_id = (data.get("source_engagement_id") or "").strip()
    if source_id:
        source = (
            linkable_observations(principal, partner.id).filter(id=source_id).first()
        )
        if source is None and instance and instance.source_engagement_id == source_id:
            source = instance.source_engagement
        if source is None:
            raise BadRequest(
                f"Choose a Regional Lead observation of a training {partner.name} delivered."
            )

    return {
        "partner": partner,
        "kind": kind,
        "held_on": held_on,
        "fy": get_operational_fy(held_on),
        "subject": subject,
        "notes": (data.get("notes") or "").strip(),
        "agreed_improvements": agreed,
        "follow_up_due": follow_up_due,
        "source_engagement": source,
    }


def record_engagement(principal, data: dict) -> PartnerEngagement:
    _require_recorder(principal)
    cleaned = _clean(principal, data)
    engagement = PartnerEngagement.objects.create(
        author_id=_uid(principal),
        author_role=_role(principal),
        country=_staff_country(principal),
        **cleaned,
    )
    _audit(
        "partner.engagement_recorded",
        engagement,
        principal,
        {"kind": engagement.kind, "held_on": engagement.held_on.isoformat()},
    )
    return engagement


def own_engagement(principal, engagement_id: str) -> PartnerEngagement:
    """The engagement, only for the person who recorded it."""
    engagement = engagements_visible_to(principal).filter(id=engagement_id).first()
    if engagement is None:
        raise NotFoundError("Engagement not found.")
    if engagement.author_id != _uid(principal):
        raise Forbidden("Only the person who recorded an engagement changes it.")
    return engagement


def is_editable(engagement: PartnerEngagement) -> bool:
    """A record stays the author's draft until its follow-up is closed or the
    partner has read it; after that it is what was agreed."""
    return not engagement.follow_up_done_at and not engagement.shared_with_partner_at


def update_engagement(principal, engagement_id: str, data: dict) -> PartnerEngagement:
    engagement = own_engagement(principal, engagement_id)
    if not is_editable(engagement):
        raise BadRequest(
            "This engagement was shared with the partner or its follow-up is closed, "
            "so it can no longer be changed."
        )
    for field, value in _clean(principal, data, instance=engagement).items():
        setattr(engagement, field, value)
    engagement.save()
    _audit("partner.engagement_updated", engagement, principal)
    return engagement


def complete_follow_up(principal, engagement_id: str, note: str) -> PartnerEngagement:
    engagement = own_engagement(principal, engagement_id)
    if not engagement.follow_up_due:
        raise BadRequest("This engagement has no follow-up to close.")
    if engagement.follow_up_done_at:
        raise BadRequest("The follow-up is already closed.")
    note = (note or "").strip()
    if not note:
        raise BadRequest(
            "Say what the follow-up found: were the agreed improvements made?"
        )
    engagement.follow_up_done_at = timezone.now()
    engagement.follow_up_note = note
    engagement.save(update_fields=["follow_up_done_at", "follow_up_note", "updated_at"])
    _audit("partner.engagement_follow_up_done", engagement, principal)
    return engagement


def share_with_partner(principal, engagement_id: str) -> PartnerEngagement:
    """Send the record to the partner organisation's login."""
    engagement = own_engagement(principal, engagement_id)
    if engagement.shared_with_partner_at:
        raise BadRequest("This engagement is already shared with the partner.")
    partner = engagement.partner
    if not partner.user_id:
        raise BadRequest(
            f"{partner.name} has no login on the platform, so the record cannot "
            "reach them here. Share the agreed improvements with them directly."
        )
    engagement.shared_with_partner_at = timezone.now()
    engagement.save(update_fields=["shared_with_partner_at", "updated_at"])
    _audit("partner.engagement_shared", engagement, principal)
    author = getattr(principal, "name", None) or "Edify"
    body = engagement.subject
    if engagement.agreed_improvements:
        body = f"{body} — agreed: {engagement.agreed_improvements}"
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=EVENT_SHARED,
            category="planning",
            priority="normal",
            title=f"{author} shared a partnership record with {partner.name}",
            body=body[:500],
            context_type="Partner",
            context_id=partner.id,
            recipients=[partner.user_id],
        )
    except Exception:  # noqa: BLE001 - never fail the share over a notice
        pass
    return engagement


# ── Derived state ────────────────────────────────────────────────────────────
def follow_up_state(engagement: PartnerEngagement, today: date) -> tuple[str, str]:
    """The follow-up in words and a tone, for registers."""
    if not engagement.follow_up_due:
        return "No follow-up", "neutral"
    if engagement.follow_up_done_at:
        return "Followed up", "success"
    if engagement.follow_up_due < today:
        return f"Overdue since {engagement.follow_up_due:%-d %b}", "danger"
    if engagement.follow_up_due == today:
        return "Due today", "warning"
    return f"Due {engagement.follow_up_due:%-d %b}", "info"


def open_observation_follow_ups(principal, *, limit: int | None = None) -> list[dict]:
    """Regional Lead observations still waiting on work with the partner.

    For a Programme Lead: observations shared with them of a partner-delivered
    training, recommending strengthening or replacing it, with no engagement
    with that partner recorded — by anyone — on or after the day it was
    observed, and none that names the observation. Three queries whatever the
    number of observations.
    """
    if _role(principal) != PROGRAM_LEAD:
        return []
    observations = list(
        linkable_observations(principal)
        .filter(recommendation__in=PARTNER_ACTION_RECOMMENDATIONS)
        .select_related("activity")
        .order_by("held_on", "created_at")
    )
    if not observations:
        return []
    partner_ids = {o.activity.assigned_partner_id for o in observations}
    engagements = PartnerEngagement.objects.filter(partner_id__in=partner_ids)
    latest = dict(
        engagements.values("partner_id")
        .annotate(last=Max("held_on"))
        .values_list("partner_id", "last")
    )
    answered = set(
        engagements.filter(source_engagement_id__isnull=False).values_list(
            "source_engagement_id", flat=True
        )
    )
    names = dict(Partner.objects.filter(id__in=partner_ids).values_list("id", "name"))
    out = []
    for observation in observations:
        partner_id = observation.activity.assigned_partner_id
        last = latest.get(partner_id)
        if observation.id in answered or (last and last >= observation.held_on):
            continue
        out.append(
            {
                "observation": observation,
                "partner_id": partner_id,
                "partner_name": names.get(partner_id, "the partner"),
                "recommendation": observation.get_recommendation_display(),
            }
        )
        if limit and len(out) >= limit:
            break
    return out


def engagement_summary(principal, fy: str) -> dict:
    """The Programme Lead dashboard's collaboration figures.

    `recorded` and `partners_engaged` count the reader's visible engagements
    held in the FY; `follow_ups_due` counts open follow-ups whose date has
    arrived whatever the year they were agreed in (an overdue follow-up does
    not stop being owed at the year end); `latest` is the five most recent
    engagements in the FY. Two queries.
    """
    today = timezone.localdate()
    counts = engagement_counts(principal, fy=fy)
    in_fy = engagements_visible_to(principal).filter(fy=fy)
    latest = []
    for engagement in in_fy.order_by("-held_on", "-created_at")[:5]:
        state, tone = follow_up_state(engagement, today)
        latest.append(
            {
                "id": engagement.id,
                "subject": engagement.subject,
                "partner_id": engagement.partner_id,
                "partner_name": engagement.partner.name,
                "kind_label": KIND_LABELS.get(engagement.kind, engagement.kind),
                "held_on": engagement.held_on,
                "follow_up": state,
                "follow_up_tone": tone,
                "url": f"/partners/{engagement.partner_id}?engagement={engagement.id}",
            }
        )
    return {
        "recorded": counts["recorded"],
        "follow_ups_due": counts["follow_ups_due"],
        "partners_engaged": counts["partners_engaged"],
        "latest": latest,
    }


def engagement_counts(principal, *, fy: str, partner_id: str | None = None) -> dict:
    """Engagements held in the FY, partners engaged in it, and open follow-ups
    whose date has arrived (any year) — one aggregate query."""

    today = timezone.localdate()
    visible = engagements_visible_to(principal)
    if partner_id:
        visible = visible.filter(partner_id=partner_id)
    counts = visible.aggregate(
        recorded=Count("id", filter=Q(fy=fy)),
        partners_engaged=Count("partner_id", filter=Q(fy=fy), distinct=True),
        follow_ups_due=Count(
            "id", filter=Q(follow_up_due__lte=today, follow_up_done_at__isnull=True)
        ),
    )
    return {key: value or 0 for key, value in counts.items()}
