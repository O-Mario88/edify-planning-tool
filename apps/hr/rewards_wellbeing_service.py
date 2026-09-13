"""Rewards and wellbeing: compensation, safety, recognition and morale.

Programmes the Regional HR Director administers by name (owner, 2026-09-12)
that had no writer anywhere: compensation and benefits, occupational health
and safety, recognition, and staff morale. Every write is limited to the
countries the director oversees (apps.hr.reach) and leaves an audit row.

Pulse surveys are anonymous by construction: a response stores a keyed hash
of the survey and the respondent, never the person, and results appear only
once a group reaches PULSE_MIN_RESPONSES.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

_HR_ROLES = {"HumanResources", "Admin"}


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _assert_hr(principal) -> None:
    if _role(principal) not in _HR_ROLES:
        raise Forbidden("Only HR may record this.")


def _assert_country(principal, country: str | None, what: str) -> None:
    from apps.hr.reach import people_reach

    if not people_reach(principal).allows_country(country):
        raise Forbidden(f"You may only record {what} in the countries you oversee.")


def _audit(action, subject_kind, subject_id, principal, payload=None):
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload=payload or {},
    )


def _amount(value, label):
    raw = str(value or "").replace(",", "").strip()
    if not raw:
        return Decimal("0")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise BadRequest(f"{label} must be a number.") from exc
    if amount < 0:
        raise BadRequest(f"{label} cannot be negative.")
    return amount


# ── Compensation and benefits ────────────────────────────────────────────────
@transaction.atomic
def save_compensation(staff_profile, data: dict, principal):
    """Create or update one employee's compensation and benefits record.

    The audit row names what changed but never the amounts: pay is personal
    data, and the audit log is read more widely than this record.
    """
    from apps.hr.models import CompensationRecord, CompensationStatus, MedicalCover

    _assert_hr(principal)
    if staff_profile is None:
        raise BadRequest("Choose the employee.")
    _assert_country(principal, staff_profile.country, "compensation")
    if staff_profile.user_id and staff_profile.user_id == getattr(
        principal, "user_id", None
    ):
        raise Forbidden("You cannot set your own compensation.")

    status = data.get("status") or CompensationStatus.HR_REVIEW
    if status not in CompensationStatus.values:
        raise BadRequest("Choose a status from the list.")
    medical = data.get("medical_cover") or MedicalCover.NONE
    if medical not in MedicalCover.values:
        raise BadRequest("Choose the medical cover from the list.")

    record, created = CompensationRecord.objects.select_for_update().get_or_create(
        staff=staff_profile
    )
    changed = []
    updates = {
        "salary_band": (data.get("salary_band") or "").strip() or None,
        "currency": (data.get("currency") or "UGX").strip().upper()[:8],
        "base_salary": _amount(data.get("base_salary"), "Base salary"),
        "allowances": _amount(data.get("allowances"), "Allowances"),
        "medical_cover": medical,
        "pension_scheme": (data.get("pension_scheme") or "").strip(),
        "other_benefits": (data.get("other_benefits") or "").strip(),
        "effective_date": data.get("effective_date") or None,
        "next_review_date": data.get("next_review_date") or None,
        "status": status,
    }
    for field, value in updates.items():
        if getattr(record, field) != value:
            setattr(record, field, value)
            changed.append(field)
    record.save()
    _audit(
        "hr.compensation_created" if created else "hr.compensation_updated",
        "compensation_record",
        record.id,
        principal,
        {"staffId": staff_profile.id, "fieldsChanged": sorted(changed)},
    )
    return record


# ── Occupational health and safety ───────────────────────────────────────────
@transaction.atomic
def report_incident(data: dict, principal):
    from apps.accounts.models import StaffProfile
    from apps.hr.models import ERSeverity, SafetyIncident, SafetyIncidentCategory

    _assert_hr(principal)
    affected = None
    affected_id = (data.get("affected_staff_id") or "").strip()
    if affected_id:
        affected = StaffProfile.objects.filter(id=affected_id).first()
        if affected is None:
            raise BadRequest("That employee was not found.")
    country = (data.get("country") or "").strip() or getattr(affected, "country", "")
    if not country:
        raise BadRequest("Choose the country the incident happened in.")
    _assert_country(principal, country, "incidents")
    category = data.get("category")
    if category not in SafetyIncidentCategory.values:
        raise BadRequest("Choose what kind of incident this was.")
    severity = data.get("severity") or ERSeverity.MEDIUM
    if severity not in ERSeverity.values:
        raise BadRequest("Choose a severity from the list.")
    incident_date = data.get("incident_date")
    if not incident_date:
        raise BadRequest("Record the date of the incident.")
    if incident_date > date.today():
        raise BadRequest("An incident cannot be dated in the future.")
    description = (data.get("description") or "").strip()
    if not description:
        raise BadRequest("Describe what happened.")
    days_lost = data.get("days_lost") or 0
    try:
        days_lost = max(int(days_lost), 0)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Days lost must be a whole number.") from exc

    incident = SafetyIncident.objects.create(
        country=country,
        affected_staff=affected,
        reported_by_id=getattr(principal, "user_id", None),
        incident_date=incident_date,
        location=(data.get("location") or "").strip(),
        category=category,
        severity=severity,
        description=description,
        immediate_action=(data.get("immediate_action") or "").strip(),
        days_lost=days_lost,
    )
    _audit(
        "hr.safety_incident_reported",
        "safety_incident",
        incident.id,
        principal,
        {"category": category, "severity": severity, "country": country},
    )
    return incident


_INCIDENT_FLOW = {
    "reported": {"investigating", "closed"},
    "investigating": {"action", "closed"},
    "action": {"closed"},
}


def incident_transitions(incident) -> list[tuple[str, str]]:
    from apps.hr.models import SafetyIncidentStatus

    labels = dict(SafetyIncidentStatus.choices)
    allowed = _INCIDENT_FLOW.get(incident.status, set())
    return [(s, labels[s]) for s in SafetyIncidentStatus.values if s in allowed]


@transaction.atomic
def advance_incident(
    incident, principal, *, to_status: str, corrective_action: str = ""
):
    from apps.hr.models import SafetyIncidentStatus

    _assert_hr(principal)
    _assert_country(principal, incident.country, "incidents")
    if to_status not in _INCIDENT_FLOW.get(incident.status, set()):
        raise BadRequest("The incident cannot move to that state.")
    if to_status in (SafetyIncidentStatus.ACTION, SafetyIncidentStatus.CLOSED):
        note = (corrective_action or "").strip()
        if not note and not incident.corrective_action:
            raise BadRequest("Record the corrective action before closing or acting.")
        if note:
            incident.corrective_action = note
    incident.status = to_status
    if to_status == SafetyIncidentStatus.CLOSED:
        incident.closed_at = timezone.now()
    incident.save()
    _audit(f"hr.safety_incident_{to_status}", "safety_incident", incident.id, principal)
    return incident


# ── Recognition ──────────────────────────────────────────────────────────────
@transaction.atomic
def recognise(staff_profile, data: dict, principal):
    from apps.hr.models import RecognitionCategory, StaffRecognition

    _assert_hr(principal)
    if staff_profile is None:
        raise BadRequest("Choose the employee being recognised.")
    _assert_country(principal, staff_profile.country, "recognitions")
    if staff_profile.user_id and staff_profile.user_id == getattr(
        principal, "user_id", None
    ):
        raise Forbidden("You cannot recognise yourself.")
    category = data.get("category")
    if category not in RecognitionCategory.values:
        raise BadRequest("Choose what the recognition is for.")
    citation = (data.get("citation") or "").strip()
    if not citation:
        raise BadRequest("Write the citation: what they did and why it mattered.")
    recognition = StaffRecognition.objects.create(
        staff=staff_profile,
        country=staff_profile.country or "",
        category=category,
        citation=citation,
        awarded_by_id=getattr(principal, "user_id", None),
        awarded_on=data.get("awarded_on") or date.today(),
    )
    _audit(
        "hr.staff_recognised",
        "staff_recognition",
        recognition.id,
        principal,
        {"staffId": staff_profile.id, "category": category},
    )
    return recognition


# ── Pulse surveys ────────────────────────────────────────────────────────────
@transaction.atomic
def open_pulse_survey(data: dict, principal):
    """Open a survey and tell everyone in its countries it is waiting."""
    from apps.accounts.models import User
    from apps.hr.models import PulseSurvey
    from apps.hr.reach import people_reach

    _assert_hr(principal)
    title = (data.get("title") or "").strip()
    if not title:
        raise BadRequest("Give the survey a title.")
    reach = people_reach(principal)
    countries = [c for c in (data.get("countries") or []) if c]
    if not countries:
        countries = list(reach.filter_options())
    for country in countries:
        if not reach.allows_country(country):
            raise Forbidden("You may only survey the countries you oversee.")
    if not countries:
        raise BadRequest("Choose at least one country.")
    opens_on = data.get("opens_on") or date.today()
    closes_on = data.get("closes_on")
    if not closes_on:
        raise BadRequest("Choose when the survey closes.")
    if closes_on < opens_on:
        raise BadRequest("A survey cannot close before it opens.")

    survey = PulseSurvey.objects.create(
        title=title,
        countries=countries,
        opens_on=opens_on,
        closes_on=closes_on,
        created_by_id=getattr(principal, "user_id", None),
    )
    recipients = User.objects.filter(
        deleted_at__isnull=True,
        is_active=True,
        staff_profile__country__in=countries,
    ).exclude(roles__overlap=["PartnerAdmin", "PartnerFieldOfficer"])
    from apps.notifications.services import WorkflowNotificationService

    WorkflowNotificationService.trigger(
        event_type="hr.pulse_survey.opened",
        category="hr",
        priority="normal",
        title=f"Staff pulse: {title}",
        body=(
            "Five quick statements about your work at Edify. Your answers are "
            f"anonymous. Open until {closes_on:%d %b %Y}."
        ),
        context_type="pulse_survey",
        context_id=survey.id,
        recipients=recipients,
    )
    _audit(
        "hr.pulse_survey_opened",
        "pulse_survey",
        survey.id,
        principal,
        {"countries": countries, "closesOn": str(closes_on)},
    )
    return survey


def close_pulse_survey(survey, principal):
    from apps.hr.models import PulseSurveyStatus
    from apps.hr.reach import people_reach

    _assert_hr(principal)
    reach = people_reach(principal)
    if not all(reach.allows_country(c) for c in survey.countries):
        raise Forbidden("You may only close surveys for the countries you oversee.")
    survey.status = PulseSurveyStatus.CLOSED
    survey.save(update_fields=["status", "updated_at"])
    _audit("hr.pulse_survey_closed", "pulse_survey", survey.id, principal)
    return survey


def _respondent_key(survey_id: str, user_id: str) -> str:
    secret = str(getattr(settings, "SECRET_KEY", "")).encode()
    return hmac.new(
        secret, f"{survey_id}:{user_id}".encode(), hashlib.sha256
    ).hexdigest()


def is_open_for(survey, user) -> bool:
    from apps.hr.models import PulseSurveyStatus

    profile = getattr(user, "staff_profile", None)
    today = date.today()
    return (
        survey.status == PulseSurveyStatus.OPEN
        and survey.opens_on <= today <= survey.closes_on
        and profile is not None
        and (profile.country or "") in (survey.countries or [])
    )


def has_answered(survey, user) -> bool:
    return survey.responses.filter(
        respondent_key=_respondent_key(survey.id, user.id)
    ).exists()


def respond(survey, user, *, scores: dict, comment: str = ""):
    """Record one anonymous answer. A second answer is refused."""
    from apps.hr.models import PULSE_QUESTIONS, PulseResponse

    if not is_open_for(survey, user):
        raise BadRequest("This survey is not open to you.")
    clean = {}
    for key, _statement in PULSE_QUESTIONS:
        try:
            value = int(scores.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value not in (1, 2, 3, 4, 5):
            raise BadRequest("Answer every statement from 1 to 5.")
        clean[key] = value
    try:
        with transaction.atomic():
            return PulseResponse.objects.create(
                survey=survey,
                respondent_key=_respondent_key(survey.id, user.id),
                country=user.staff_profile.country or "",
                scores=clean,
                comment=(comment or "").strip()[:2000],
            )
    except IntegrityError as exc:
        raise BadRequest("You have already answered this survey.") from exc


def survey_results(survey) -> dict:
    """Average score per statement, shown only above the anonymity floor."""
    from apps.hr.models import PULSE_MIN_RESPONSES, PULSE_QUESTIONS

    responses = list(survey.responses.values_list("scores", flat=True))
    count = len(responses)
    if count < PULSE_MIN_RESPONSES:
        return {"count": count, "shown": False, "rows": [], "overall": None}
    rows = []
    totals = []
    for key, statement in PULSE_QUESTIONS:
        values = [r.get(key) for r in responses if r.get(key)]
        average = round(sum(values) / len(values), 1) if values else None
        if average is not None:
            totals.append(average)
        favourable = (
            round(sum(1 for v in values if v >= 4) * 100 / len(values))
            if values
            else None
        )
        rows.append(
            {
                "key": key,
                "statement": statement,
                "average": average,
                "favourable": favourable,
            }
        )
    overall = round(sum(totals) / len(totals), 1) if totals else None
    return {"count": count, "shown": True, "rows": rows, "overall": overall}
