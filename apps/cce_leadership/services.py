"""Rules for the CCE Regional Lead's engagement log, training feedback and
monthly report (owner, 2026-09-13).

Who may do what:

* The Regional Programme Lead records their own engagements and observations
  in their region, shares observation feedback — and the notes of a coaching
  conversation — with the Programme Lead it concerns, and writes and submits
  their monthly report.
* The Programme Lead the feedback names acknowledges it and says what they
  will change; their Country Director reads the feedback on their country.
  Coaching the Regional Lead shares stays between the two of them (owner,
  2026-09-13: the Programme Lead "partners with regional leads … to build
  capacity").
* The RVP reads the reports of the Regional Leads whose countries they
  oversee and acknowledges or returns them.
* Admin reads everything and writes nothing on another person's behalf.

Every write is audit-logged and every handoff notifies the person it hands to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy

from .models import (
    OBSERVATION_CRITERIA,
    REPORT_SECTIONS,
    EngagementKind,
    ObservationRecommendation,
    RegionalCceReport,
    RegionalEngagement,
    ReportStatus,
)

REGIONAL_LEAD = "RegionalProgramLead"
PROGRAM_LEAD = "Program Lead"
COUNTRY_DIRECTOR = "CountryDirector"
RVP = "RegionalVicePresident"
ADMIN = "Admin"

# Monthly reports are expected from the month the report was introduced: the
# first one due is September 2026's, by 10 October. A month before it was never
# owed through the platform, so it is never counted as overdue.
REPORTING_STARTS = date(2026, 9, 1)

# Trainings observed are recent or imminent ones: a lead watches a training
# while it happens or records it just after.
OBSERVATION_LOOKBACK_DAYS = 120
OBSERVATION_LOOKAHEAD_DAYS = 14

EVENT_FEEDBACK_SHARED = "cce_training_feedback_shared"
EVENT_FEEDBACK_ACKNOWLEDGED = "cce_training_feedback_acknowledged"
EVENT_REPORT_SUBMITTED = "cce_report_submitted"
EVENT_REPORT_REVIEWED = "cce_report_reviewed"
EVENT_PL_COACHING_SHARED = "cce_pl_coaching_shared"
EVENT_PL_COACHING_ACKNOWLEDGED = "cce_pl_coaching_acknowledged"

# What the Regional Lead hands to a Programme Lead to acknowledge: the feedback
# on a training they observed, and the notes of a coaching conversation.
SHAREABLE_KINDS = (EngagementKind.TRAINING_OBSERVATION, EngagementKind.PL_COACHING)

NOT_LIVE_STATUSES = (
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
)


def _uid(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _staff_id(principal) -> str | None:
    staff_id = getattr(principal, "staff_profile_id", None)
    if staff_id:
        return str(staff_id)
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=_uid(principal))
        .values_list("id", flat=True)
        .first()
    )


def _staff_country(principal) -> str:
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=_uid(principal))
        .values_list("country", flat=True)
        .first()
        or ""
    ).strip()


def _audit(action: str, subject_kind: str, subject_id: str, principal, payload=None):
    audit_log(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_id=_uid(principal),
        actor_role=_role(principal),
        payload=payload or {},
    )


def _notify(
    event_type, *, title, body, context_type, context_id, recipients, priority="normal"
):
    if not recipients:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="leadership",
            priority=priority,
            title=title,
            body=body[:500],
            context_type=context_type,
            context_id=context_id,
            recipients=list(recipients),
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass


def _parse_date(value, label: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise BadRequest(f"Enter {label} as a date.") from exc


# ── Reach ────────────────────────────────────────────────────────────────────
@dataclass
class LeadReach:
    countries: list[str]
    assigned: bool
    leads: list[dict]
    directors: list[dict]


def reach_countries(principal) -> tuple[list[str], bool]:
    """The countries a Regional Lead serves, and whether any are assigned.

    The role's operational reach (apps.core.scoping `_regional_reach`): the
    countries of the regions assigned to the lead, or every country when none
    is assigned yet. Admin reads every country.
    """
    from apps.core.scoping import resolve_user_scope

    if _role(principal) == ADMIN:
        from apps.geography.models import Region

        countries = sorted(
            {c for c in Region.objects.values_list("country", flat=True) if c}
        )
        return countries, False
    scope = resolve_user_scope(principal)
    return list(scope.region_countries or ()), bool(scope.region_assigned)


def lead_reach(principal) -> LeadReach:
    """The countries a Regional Lead serves and the country leaders in them."""
    from apps.accounts.models import StaffProfile

    countries, assigned = reach_countries(principal)

    people = (
        StaffProfile.objects.filter(
            user__status="active",
            user__deleted_at__isnull=True,
            country__in=countries,
        )
        .select_related("user")
        .order_by("country", "user__name")
    )

    def entry(profile):
        return {
            "staff_id": profile.id,
            "user_id": profile.user_id,
            "name": profile.user.name or profile.user.email,
            "country": profile.country or "",
        }

    return LeadReach(
        countries=countries,
        assigned=assigned,
        leads=[entry(p) for p in people.filter(user__roles__contains=[PROGRAM_LEAD])],
        directors=[
            entry(p) for p in people.filter(user__roles__contains=[COUNTRY_DIRECTOR])
        ],
    )


def _rvp_countries(principal) -> list[str] | None:
    """The countries an RVP oversees; None when they oversee every country."""
    from apps.core.scoping import resolve_user_scope
    from apps.geography.models import Region

    scope = resolve_user_scope(principal)
    if not scope.rvp_region_scoped:
        return None
    return sorted(
        {
            c
            for c in Region.objects.filter(id__in=scope.region_ids).values_list(
                "country", flat=True
            )
            if c
        }
    )


def _rvps_for(countries: list[str]) -> list[str]:
    """The RVPs a report goes to: those whose assigned regions reach its
    countries, or every active RVP when none is assigned to them."""
    from apps.accounts.models import StaffGeographyAssignment, User
    from apps.geography.models import Region

    rvps = list(
        User.objects.filter(
            deleted_at__isnull=True,
            status="active",
            roles__contains=[RVP],
        ).values_list("id", flat=True)
    )
    if not rvps:
        return []
    links = list(
        StaffGeographyAssignment.objects.filter(
            staff__user_id__in=rvps, region_id__isnull=False
        ).values_list("staff__user_id", "region_id")
    )
    country_of = dict(
        Region.objects.filter(
            id__in={region_id for _uid, region_id in links}
        ).values_list("id", "country")
    )
    assigned: dict[str, set[str]] = {}
    for user_id, region_id in links:
        assigned.setdefault(user_id, set()).add(country_of.get(region_id, ""))
    matching = [uid for uid in rvps if assigned.get(uid, set()) & set(countries)]
    unassigned = [uid for uid in rvps if uid not in assigned]
    return matching or unassigned or rvps


# ── Visibility ───────────────────────────────────────────────────────────────
def engagements_visible_to(principal):
    role = _role(principal)
    qs = RegionalEngagement.objects.select_related("activity")
    if role == ADMIN:
        return qs
    if role == REGIONAL_LEAD:
        return qs.filter(author_id=_uid(principal))
    return qs.none()


def feedback_visible_to(principal):
    """Observations a person may read.

    The Programme Lead reads feedback shared with them, their Country Director
    reads the feedback shared on their country, the lead reads their own and
    Admin reads all. Unshared drafts stay with the lead who wrote them.
    """
    role = _role(principal)
    qs = RegionalEngagement.objects.filter(
        kind=EngagementKind.TRAINING_OBSERVATION
    ).select_related("activity", "activity__school", "activity__cluster")
    if role == ADMIN:
        return qs
    if role == REGIONAL_LEAD:
        return qs.filter(author_id=_uid(principal))
    shared = qs.filter(feedback_shared_at__isnull=False)
    if role == PROGRAM_LEAD:
        staff_id = _staff_id(principal)
        return (
            shared.filter(program_lead_ids__contains=[staff_id])
            if staff_id
            else qs.none()
        )
    if role == COUNTRY_DIRECTOR:
        country = _staff_country(principal)
        return shared.filter(country=country) if country else qs.none()
    return qs.none()


def regional_coaching_visible_to(principal):
    """Coaching conversations the Regional Lead held with Programme Leads.

    The Programme Lead reads the ones shared with them, the lead reads their
    own and Admin reads all. Unlike training feedback, nothing reaches the
    Country Director: a coaching conversation is about the Programme Lead's
    own practice, and the engagement log stays the Regional Lead's.
    """
    role = _role(principal)
    qs = RegionalEngagement.objects.filter(kind=EngagementKind.PL_COACHING)
    if role == ADMIN:
        return qs
    if role == REGIONAL_LEAD:
        return qs.filter(author_id=_uid(principal))
    if role == PROGRAM_LEAD:
        staff_id = _staff_id(principal)
        if not staff_id:
            return qs.none()
        return qs.filter(
            feedback_shared_at__isnull=False, program_lead_ids__contains=[staff_id]
        )
    return qs.none()


def reports_visible_to(principal):
    role = _role(principal)
    qs = RegionalCceReport.objects.all()
    if role == ADMIN:
        return qs
    if role == REGIONAL_LEAD:
        return qs.filter(author_id=_uid(principal))
    if role == RVP:
        sent = qs.exclude(status=ReportStatus.DRAFT)
        countries = _rvp_countries(principal)
        return sent if countries is None else sent.filter(countries__overlap=countries)
    return qs.none()


def _require_lead(principal):
    if _role(principal) != REGIONAL_LEAD:
        raise Forbidden(
            "Only the Regional Programme Lead records CCE engagements and reports."
        )


# ── Trainings a lead can observe ─────────────────────────────────────────────
def activities_in_countries(countries: list[str]) -> Q:
    """Activities whose school, or whose cluster when it has no school, lies in
    one of `countries`."""
    return (
        Q(school__region__country__in=countries)
        | Q(school__isnull=True, cluster__district__region__country__in=countries)
        | Q(school__isnull=True, cluster__region__country__in=countries)
    )


def observable_trainings(principal, *, today: date | None = None):
    from apps.activities.models import Activity
    from apps.core.activity_types import TRAINING_TYPES

    today = today or timezone.localdate()
    reach = lead_reach(principal)
    return (
        Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type__in=[str(t) for t in TRAINING_TYPES],
            planned_date__gte=today - timedelta(days=OBSERVATION_LOOKBACK_DAYS),
            planned_date__lte=today + timedelta(days=OBSERVATION_LOOKAHEAD_DAYS),
        )
        .exclude(status__in=NOT_LIVE_STATUSES)
        .filter(activities_in_countries(reach.countries))
        .select_related(
            "school__region", "cluster__district__region", "cluster__region"
        )
        .order_by("-planned_date", "id")
    )


def training_label(activity) -> str:
    name = activity.activity_name_snapshot or activity.get_activity_type_display()
    place = (
        activity.school.name
        if activity.school_id
        else (activity.cluster.name if activity.cluster_id else "")
    )
    when = f"{activity.planned_date:%-d %b}" if activity.planned_date else "Undated"
    return " · ".join(part for part in (when, name, place) if part)


def activity_country(activity) -> str:
    if activity.school_id and activity.school.region_id:
        return activity.school.region.country or ""
    if activity.cluster_id:
        cluster = activity.cluster
        if cluster.district_id and cluster.district.region_id:
            return cluster.district.region.country or ""
        if cluster.region_id:
            return cluster.region.country or ""
    return ""


def supervising_leads(activity, reach: LeadReach) -> list[str]:
    """The Programme Leads accountable for a training: the lead of whoever
    delivers or monitors it, or that person when they are a Programme Lead."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    owners = {
        str(v)
        for v in (activity.responsible_staff_id, activity.monitored_by_staff_id)
        if v
    }
    if not owners:
        return []
    staff_ids = set(
        StaffProfile.objects.filter(
            Q(id__in=owners) | Q(user_id__in=owners)
        ).values_list("id", flat=True)
    )
    in_reach = {lead["staff_id"] for lead in reach.leads}
    leads = {sid for sid in staff_ids if sid in in_reach}
    leads.update(
        sid
        for sid in StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=staff_ids
        ).values_list("supervisor_id", flat=True)
        if sid in in_reach
    )
    return sorted(leads)


# ── Engagements ──────────────────────────────────────────────────────────────
def _clean_engagement(principal, data, *, instance: RegionalEngagement | None = None):
    reach = lead_reach(principal)
    kind = (data.get("kind") or (instance.kind if instance else "")).strip()
    if kind not in EngagementKind.values:
        raise BadRequest("Choose what kind of engagement this was.")
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

    leads_by_id = {lead["staff_id"]: lead for lead in reach.leads}
    lead_ids = [str(i) for i in (data.get("program_lead_ids") or []) if str(i).strip()]
    unknown = [i for i in lead_ids if i not in leads_by_id]
    if unknown:
        raise BadRequest("Choose Programme Leads who work in your region.")
    country = (data.get("country") or "").strip()
    if country and country not in reach.countries:
        raise BadRequest("Choose a country in your region.")

    cleaned = {
        "kind": kind,
        "held_on": held_on,
        "fy": get_operational_fy(held_on),
        "follow_up_due": follow_up_due,
        "notes": (data.get("notes") or "").strip(),
        "agreed_actions": (data.get("agreed_actions") or "").strip(),
    }

    if kind == EngagementKind.TRAINING_OBSERVATION:
        activity_id = (data.get("activity_id") or "").strip()
        if not activity_id:
            raise BadRequest("Choose the training you observed.")
        activity = observable_trainings(principal).filter(id=activity_id).first()
        if activity is None and instance and instance.activity_id == activity_id:
            activity = instance.activity
        if activity is None:
            raise BadRequest(
                "Choose a training in your region from the last four months."
            )
        ratings = {}
        for field, label, _hint in OBSERVATION_CRITERIA:
            raw = data.get(field)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise BadRequest(f"Rate “{label}” from 1 to 4.") from None
            if not 1 <= value <= 4:
                raise BadRequest(f"Rate “{label}” from 1 to 4.")
            ratings[field] = value
        recommendation = (data.get("recommendation") or "").strip()
        if recommendation not in ObservationRecommendation.values:
            raise BadRequest("Choose what you recommend for this training.")
        feedback = (data.get("feedback") or "").strip()
        if not feedback:
            raise BadRequest(
                "Write the feedback for the Programme Lead: what worked and what to change."
            )
        lead_ids = lead_ids or supervising_leads(activity, reach)
        cleaned.update(
            activity=activity,
            country=activity_country(activity) or country,
            program_lead_ids=lead_ids,
            recommendation=recommendation,
            feedback=feedback,
            subject=(data.get("subject") or "").strip()[:255]
            or f"Observed: {training_label(activity)}"[:255],
            **ratings,
        )
        return cleaned

    if kind == EngagementKind.PL_COACHING and not lead_ids:
        raise BadRequest("Choose the Programme Lead you met.")
    if (
        kind in (EngagementKind.CD_QUARTERLY_REVIEW, EngagementKind.CD_ANNUAL_PLANNING)
        and not country
    ):
        raise BadRequest("Choose the country whose Country Director you met.")
    if kind == EngagementKind.PL_COACHING and not country:
        countries = {leads_by_id[i]["country"] for i in lead_ids} - {""}
        country = countries.pop() if len(countries) == 1 else ""
    subject = (data.get("subject") or "").strip()[:255]
    if not subject:
        names = ", ".join(leads_by_id[i]["name"] for i in lead_ids)
        label = EngagementKind(kind).label
        subject = f"{label} · {names or country}" if (names or country) else label
    cleaned.update(country=country, program_lead_ids=lead_ids, subject=subject[:255])
    return cleaned


def record_engagement(principal, data: dict) -> RegionalEngagement:
    _require_lead(principal)
    cleaned = _clean_engagement(principal, data)
    engagement = RegionalEngagement.objects.create(author_id=_uid(principal), **cleaned)
    _audit(
        "cce.engagement_recorded",
        "RegionalEngagement",
        engagement.id,
        principal,
        {"kind": engagement.kind, "held_on": engagement.held_on.isoformat()},
    )
    return engagement


def _own_engagement(principal, engagement_id: str) -> RegionalEngagement:
    engagement = engagements_visible_to(principal).filter(id=engagement_id).first()
    if engagement is None:
        raise NotFoundError("Engagement not found.")
    if engagement.author_id != _uid(principal):
        raise Forbidden("Only the Regional Lead who recorded an engagement changes it.")
    return engagement


def update_engagement(principal, engagement_id: str, data: dict) -> RegionalEngagement:
    _require_lead(principal)
    engagement = _own_engagement(principal, engagement_id)
    if engagement.feedback_shared_at:
        raise Forbidden(
            "This has been shared with the Programme Lead, so it can no longer be changed."
        )
    cleaned = _clean_engagement(
        principal, {**data, "kind": engagement.kind}, instance=engagement
    )
    for field, value in cleaned.items():
        setattr(engagement, field, value)
    engagement.save()
    _audit("cce.engagement_updated", "RegionalEngagement", engagement.id, principal)
    return engagement


def share_feedback(principal, engagement_id: str) -> RegionalEngagement:
    """Hand a training observation's feedback, or a coaching conversation's
    notes, to the Programme Leads it names. Either way it can no longer be
    edited, and each lead is asked to acknowledge it."""
    _require_lead(principal)
    with transaction.atomic():
        engagement = _own_engagement(principal, engagement_id)
        engagement = RegionalEngagement.objects.select_for_update().get(
            id=engagement.id
        )
        if engagement.kind not in SHAREABLE_KINDS:
            raise BadRequest(
                "Only a training observation or a coaching conversation is shared "
                "with the Programme Lead."
            )
        if engagement.feedback_shared_at:
            raise BadRequest("This was already shared with the Programme Lead.")
        if not engagement.program_lead_ids:
            raise BadRequest(
                "Name the Programme Lead who should receive this before sharing it."
            )
        engagement.feedback_shared_at = timezone.now()
        engagement.save(update_fields=["feedback_shared_at", "updated_at"])
        _audit(
            "cce.training_feedback_shared"
            if engagement.is_observation
            else "cce.pl_coaching_shared",
            "RegionalEngagement",
            engagement.id,
            principal,
            {"program_lead_ids": engagement.program_lead_ids},
        )
    from apps.accounts.models import StaffProfile

    recipients = list(
        StaffProfile.objects.filter(id__in=engagement.program_lead_ids).values_list(
            "user_id", flat=True
        )
    )
    if engagement.is_observation:
        _notify(
            EVENT_FEEDBACK_SHARED,
            title="Training feedback from your Regional Lead",
            body=f"{engagement.subject}. {engagement.feedback}",
            context_type="RegionalEngagement",
            context_id=engagement.id,
            recipients=recipients,
            priority="high",
        )
    else:
        _notify(
            EVENT_PL_COACHING_SHARED,
            title="Coaching notes from your Regional Lead",
            body=" ".join(
                part
                for part in (
                    f"{engagement.subject}.",
                    engagement.agreed_actions
                    and f"Agreed actions: {engagement.agreed_actions}",
                )
                if part
            ),
            context_type="RegionalEngagement",
            context_id=engagement.id,
            recipients=recipients,
            priority="high",
        )
    return engagement


def acknowledge_feedback(
    principal, engagement_id: str, response: str
) -> RegionalEngagement:
    if _role(principal) != PROGRAM_LEAD:
        raise Forbidden(
            "The Programme Lead the feedback is addressed to acknowledges it."
        )
    response = (response or "").strip()
    if not response:
        raise BadRequest(
            "Say what you will change in the training, or why it stays as delivered."
        )
    with transaction.atomic():
        engagement = feedback_visible_to(principal).filter(id=engagement_id).first()
        if engagement is None:
            raise NotFoundError("Feedback not found.")
        engagement = RegionalEngagement.objects.select_for_update().get(
            id=engagement.id
        )
        if engagement.acknowledged_at:
            raise BadRequest("This feedback was already acknowledged.")
        engagement.acknowledged_at = timezone.now()
        engagement.acknowledged_by_id = _uid(principal)
        engagement.lead_response = response
        engagement.save(
            update_fields=[
                "acknowledged_at",
                "acknowledged_by_id",
                "lead_response",
                "updated_at",
            ]
        )
        _audit(
            "cce.training_feedback_acknowledged",
            "RegionalEngagement",
            engagement.id,
            principal,
        )
    _notify(
        EVENT_FEEDBACK_ACKNOWLEDGED,
        title="A Programme Lead acknowledged your training feedback",
        body=f"{engagement.subject}. {response}",
        context_type="RegionalEngagement",
        context_id=engagement.id,
        recipients=[engagement.author_id],
    )
    _resolve_notice(EVENT_FEEDBACK_SHARED, engagement.id, principal)
    return engagement


def acknowledge_regional_coaching(
    principal, engagement_id: str, response: str
) -> RegionalEngagement:
    """The Programme Lead answers a coaching conversation the Regional Lead
    shared with them: what they will do about the actions agreed."""
    if _role(principal) != PROGRAM_LEAD:
        raise Forbidden(
            "The Programme Lead the coaching was shared with acknowledges it."
        )
    response = (response or "").strip()
    if not response:
        raise BadRequest("Say what you will do about the actions agreed, and by when.")
    with transaction.atomic():
        engagement = (
            regional_coaching_visible_to(principal).filter(id=engagement_id).first()
        )
        if engagement is None:
            raise NotFoundError("Coaching not found.")
        engagement = RegionalEngagement.objects.select_for_update().get(
            id=engagement.id
        )
        if engagement.acknowledged_at:
            raise BadRequest("This coaching was already acknowledged.")
        engagement.acknowledged_at = timezone.now()
        engagement.acknowledged_by_id = _uid(principal)
        engagement.lead_response = response
        engagement.save(
            update_fields=[
                "acknowledged_at",
                "acknowledged_by_id",
                "lead_response",
                "updated_at",
            ]
        )
        _audit(
            "cce.pl_coaching_acknowledged",
            "RegionalEngagement",
            engagement.id,
            principal,
        )
    _notify(
        EVENT_PL_COACHING_ACKNOWLEDGED,
        title="A Programme Lead acknowledged your coaching notes",
        body=f"{engagement.subject}. {response}",
        context_type="RegionalEngagement",
        context_id=engagement.id,
        recipients=[engagement.author_id],
    )
    _resolve_notice(EVENT_PL_COACHING_SHARED, engagement.id, principal)
    return engagement


def _resolve_notice(event_type: str, engagement_id: str, principal) -> None:
    """The acknowledgement closes the notice that asked for it."""
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(
            event_type,
            "RegionalEngagement",
            engagement_id,
            recipient_ids=[_uid(principal)],
        )
    except Exception:  # noqa: BLE001 - never fail the work over a notice
        pass


def delivered_by(activities) -> dict[str, str]:
    """Who delivered each training, by activity id: the training partner's
    name for partner delivery, otherwise the responsible officer's name.

    `responsible_staff_id` holds a StaffProfile id as often as a User id, so
    both are resolved, in one query each however many trainings there are.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.enums import DeliveryType
    from apps.partners.models import Partner

    activities = [a for a in activities if a is not None]
    partner_ids = {
        a.assigned_partner_id
        for a in activities
        if a.delivery_type == DeliveryType.PARTNER and a.assigned_partner_id
    }
    staff_ids = {
        a.responsible_staff_id
        for a in activities
        if a.delivery_type != DeliveryType.PARTNER and a.responsible_staff_id
    }
    partners = (
        dict(Partner.objects.filter(id__in=partner_ids).values_list("id", "name"))
        if partner_ids
        else {}
    )
    people: dict[str, str] = {}
    if staff_ids:
        for staff_id, user_id, name in StaffProfile.objects.filter(
            Q(id__in=staff_ids) | Q(user_id__in=staff_ids)
        ).values_list("id", "user_id", "user__name"):
            people[staff_id] = people[user_id] = name or ""
    out = {}
    for activity in activities:
        if activity.delivery_type == DeliveryType.PARTNER:
            name = partners.get(activity.assigned_partner_id, "")
            out[activity.id] = f"{name} · partner" if name else "Training partner"
        else:
            out[activity.id] = people.get(activity.responsible_staff_id, "") or "—"
    return out


# ── Monthly reports ──────────────────────────────────────────────────────────
def month_start(value: date) -> date:
    return value.replace(day=1)


def next_month(value: date) -> date:
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def start_report(principal, period) -> RegionalCceReport:
    _require_lead(principal)
    if isinstance(period, str) and len(period) == 7:
        period = f"{period}-01"
    period = _parse_date(period, "the month")
    if period is None:
        raise BadRequest("Choose the month the report covers.")
    period = month_start(period)
    if period > month_start(timezone.localdate()):
        raise BadRequest("A monthly report covers the current month or an earlier one.")
    reach = lead_reach(principal)
    report, created = RegionalCceReport.objects.get_or_create(
        author_id=_uid(principal),
        period=period,
        defaults={"fy": get_operational_fy(period), "countries": reach.countries},
    )
    if created:
        _audit(
            "cce.report_started",
            "RegionalCceReport",
            report.id,
            principal,
            {"period": period.isoformat()},
        )
    return report


def update_report(
    principal, report_id: str, data: dict, *, submit: bool = False
) -> RegionalCceReport:
    _require_lead(principal)
    with transaction.atomic():
        report = (
            reports_visible_to(principal)
            .select_for_update()
            .filter(id=report_id)
            .first()
        )
        if report is None:
            raise NotFoundError("Report not found.")
        if report.status not in (ReportStatus.DRAFT, ReportStatus.RETURNED):
            raise Forbidden(
                "This report is with the RVP. It can be edited again if they return it."
            )
        for field, _label, _hint in REPORT_SECTIONS:
            if field in data:
                setattr(report, field, (data.get(field) or "").strip())
        if submit:
            if not report.executive_summary:
                raise BadRequest(
                    "Write the executive summary before submitting the report."
                )
            report.metrics = report_metrics(principal, report.period)
            report.status = ReportStatus.SUBMITTED
            report.submitted_at = timezone.now()
            report.reviewed_at = None
            report.reviewed_by_id = None
        report.countries = report.countries or lead_reach(principal).countries
        report.save()
        _audit(
            "cce.report_submitted" if submit else "cce.report_saved",
            "RegionalCceReport",
            report.id,
            principal,
            {"period": report.period.isoformat(), "status": report.status},
        )
    if submit:
        author = getattr(principal, "name", "") or "A Regional Lead"
        _notify(
            EVENT_REPORT_SUBMITTED,
            title=f"{report.period:%B %Y} CCE report from {author}",
            body=report.executive_summary,
            context_type="RegionalCceReport",
            context_id=report.id,
            recipients=_rvps_for(report.countries),
            priority="high",
        )
    return report


def review_report(
    principal, report_id: str, decision: str, note: str = ""
) -> RegionalCceReport:
    if _role(principal) not in (RVP, ADMIN):
        raise Forbidden("The RVP reviews the Regional Lead's monthly report.")
    note = (note or "").strip()
    if decision not in ("acknowledge", "return"):
        raise BadRequest("Choose whether to acknowledge the report or return it.")
    if decision == "return" and not note:
        raise BadRequest("Say what the report needs before returning it.")
    with transaction.atomic():
        report = (
            reports_visible_to(principal)
            .select_for_update()
            .filter(id=report_id)
            .first()
        )
        if report is None:
            raise NotFoundError("Report not found.")
        if report.status != ReportStatus.SUBMITTED:
            raise BadRequest("Only a submitted report waits for a review.")
        report.status = (
            ReportStatus.ACKNOWLEDGED
            if decision == "acknowledge"
            else ReportStatus.RETURNED
        )
        report.reviewed_by_id = _uid(principal)
        report.reviewed_at = timezone.now()
        report.review_note = note
        report.save(
            update_fields=[
                "status",
                "reviewed_by_id",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )
        _audit(
            f"cce.report_{report.status}",
            "RegionalCceReport",
            report.id,
            principal,
            {"note": note},
        )
    _notify(
        EVENT_REPORT_REVIEWED,
        title=(
            f"Your {report.period:%B %Y} CCE report was acknowledged"
            if report.status == ReportStatus.ACKNOWLEDGED
            else f"Your {report.period:%B %Y} CCE report was returned"
        ),
        body=note or "The RVP acknowledged your monthly report.",
        context_type="RegionalCceReport",
        context_id=report.id,
        recipients=[report.author_id],
        priority="normal" if report.status == ReportStatus.ACKNOWLEDGED else "high",
    )
    return report


def report_metrics(principal, period: date) -> dict:
    """The region's figures for one month, as the report freezes them."""
    from django.db.models import Count, Sum

    from apps.activities.models import Activity
    from apps.analytics.rpl_dashboard_service import COACHING_FOLLOW_UP_TYPES
    from apps.core.activity_types import COMPLETED_WORK_STATUSES, TRAINING_TYPES
    from apps.ssa.models import SsaRecord
    from apps.ssa.plan_alignment import INFORMED, LIVE_PLAN_STATUSES

    reach = lead_reach(principal)
    start, end = month_start(period), next_month(period)
    in_region = activities_in_countries(reach.countries)
    delivered = Activity.objects.filter(
        in_region,
        deleted_at__isnull=True,
        status__in=COMPLETED_WORK_STATUSES,
        planned_date__gte=start,
        planned_date__lt=end,
    )
    trainings = delivered.filter(activity_type__in=[str(t) for t in TRAINING_TYPES])
    training_totals = trainings.aggregate(
        n=Count("id"),
        teachers=Sum("teachers_attended"),
        leaders=Sum("leaders_attended"),
    )
    by_country: dict[str, int] = {}
    for school_country, cluster_country in trainings.values_list(
        "school__region__country", "cluster__district__region__country"
    ):
        country = school_country or cluster_country or "Unplaced"
        by_country[country] = by_country.get(country, 0) + 1

    fy = get_operational_fy(start)
    verdicts = (
        Activity.objects.filter(
            in_region, deleted_at__isnull=True, fy=fy, status__in=LIVE_PLAN_STATUSES
        )
        .exclude(ssa_alignment="")
        .values_list("ssa_alignment", flat=True)
    )
    verdicts = list(verdicts)
    informed = sum(1 for v in verdicts if v in INFORMED)

    own = RegionalEngagement.objects.filter(
        author_id=_uid(principal), held_on__gte=start, held_on__lt=end
    )
    observations = [e for e in own if e.is_observation]
    ratings = [e.average_rating for e in observations if e.average_rating]
    return {
        "period": start.isoformat(),
        "countries": reach.countries,
        "trainings_delivered": training_totals["n"] or 0,
        "teachers_trained": training_totals["teachers"] or 0,
        "leaders_trained": training_totals["leaders"] or 0,
        "trainings_by_country": dict(sorted(by_country.items())),
        "coaching_follow_up_visits": delivered.filter(
            activity_type__in=COACHING_FOLLOW_UP_TYPES
        ).count(),
        "ssa_confirmed": SsaRecord.objects.filter(
            deleted_at__isnull=True,
            verification_status="confirmed",
            school__region__country__in=reach.countries,
            date_of_ssa__date__gte=start,
            date_of_ssa__date__lt=end,
        ).count(),
        "ssa_informed_plans_pct": round(informed * 100 / len(verdicts))
        if verdicts
        else None,
        "coaching_conversations": sum(
            1 for e in own if e.kind == EngagementKind.PL_COACHING
        ),
        "trainings_observed": len(observations),
        "average_observation_rating": round(sum(ratings) / len(ratings), 1)
        if ratings
        else None,
        "country_reviews": sum(
            1 for e in own if e.kind == EngagementKind.CD_QUARTERLY_REVIEW
        ),
    }


# ── Summaries for the dashboard and the registers ────────────────────────────
def rhythm(principal, *, today: date | None = None) -> dict:
    """The lead's meeting rhythm against the role description (cadence.py)."""
    from apps.monthly_work_plan.models import CountryAnnualBudget

    from .cadence import Held, evaluate

    today = today or timezone.localdate()
    reach = lead_reach(principal)
    since = today - timedelta(days=400)
    held = [
        Held(kind, held_on, country, tuple(lead_ids or ()))
        for kind, held_on, country, lead_ids in RegionalEngagement.objects.filter(
            author_id=_uid(principal), held_on__gte=since
        ).values_list("kind", "held_on", "country", "program_lead_ids")
    ]
    next_fy = str(int(get_operational_fy(today)) + 1)
    submitted = set(
        CountryAnnualBudget.objects.filter(
            fy=next_fy,
            country_id__in=reach.countries,
            status__in=("submitted_to_rvp", "approved_by_rvp"),
        ).values_list("country_id", flat=True)
    )
    result = evaluate(
        held,
        today=today,
        leads=reach.leads,
        countries=reach.countries,
        budgets_submitted=submitted,
    )
    result["last_coaching"] = {
        row["lead_staff_id"]: row["last_held"]
        for row in result["rows"]
        if row.get("lead_staff_id")
    }
    return result


def observation_summary(principal, *, fy: str, limit: int = 5) -> dict:
    observations = list(
        feedback_visible_to(principal).filter(fy=fy).order_by("-held_on", "-created_at")
    )
    ratings = [o.average_rating for o in observations if o.average_rating]
    recommendations = {
        value: sum(1 for o in observations if o.recommendation == value)
        for value in ObservationRecommendation.values
    }
    return {
        "count": len(observations),
        "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "recommendations": recommendations,
        "unshared": sum(1 for o in observations if not o.feedback_shared_at),
        "awaiting_acknowledgement": sum(
            1 for o in observations if o.feedback_shared_at and not o.acknowledged_at
        ),
        "rows": observations[:limit],
    }


def report_state(principal, *, today: date | None = None) -> dict:
    """Where this month's and last month's reports stand.

    Last month's report is due by the tenth of the month after it; this
    month's can be drafted as the month goes. Months before REPORTING_STARTS
    were never owed, so they are never overdue.
    """
    today = today or timezone.localdate()
    current = month_start(today)
    previous = month_start(current - timedelta(days=1))
    reports = {
        r.period: r
        for r in RegionalCceReport.objects.filter(
            author_id=_uid(principal), period__in=[current, previous]
        )
    }
    due_by = next_month(previous).replace(day=10)
    last = reports.get(previous)
    required = previous >= REPORTING_STARTS
    overdue = (
        required
        and (last is None or last.status in (ReportStatus.DRAFT, ReportStatus.RETURNED))
        and today > due_by
    )
    return {
        "current_period": current,
        "current": reports.get(current),
        "previous_period": previous,
        "previous": last,
        "previous_due_by": due_by,
        "previous_overdue": overdue,
        "previous_required": required,
        "reporting_starts": REPORTING_STARTS,
    }
