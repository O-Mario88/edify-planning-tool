"""Compliance with country employment law: requirements and the evidence
each employee holds against them (2026-09-13).

The Regional HR Director "monitors and ensures the organisation's compliance
with country/regional employment laws". `ComplianceRequirement` and
`EmployeeComplianceRecord` existed, and the HR dashboard and HR Today read
them, but nothing wrote either, so every compliance figure was an em dash.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

#: A document inside this many days of expiring is "Due Soon".
DUE_SOON_DAYS = 30
ALL_COUNTRIES = "All"


def _assert_hr(principal) -> None:
    if (getattr(principal, "active_role", "") or "") not in ("HumanResources", "Admin"):
        raise Forbidden("Only HR may manage employment compliance.")


def _audit(action, subject_kind, subject_id, principal, payload=None):
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload=payload or {},
    )


def derived_status(*, expiry_date, has_evidence: bool, today=None) -> str:
    """The status a record's evidence and expiry date support."""
    from apps.hr.models import ComplianceStatus

    today = today or date.today()
    if not has_evidence:
        return ComplianceStatus.MISSING
    if expiry_date and expiry_date < today:
        return ComplianceStatus.EXPIRED
    if expiry_date and expiry_date <= today + timedelta(days=DUE_SOON_DAYS):
        return ComplianceStatus.DUE_SOON
    return ComplianceStatus.COMPLIANT


def visible_requirements(principal):
    """Requirements for the director's countries, plus those for every country."""
    from django.db.models import Q

    from apps.hr.models import ComplianceRequirement
    from apps.hr.reach import people_reach

    reach = people_reach(principal)
    requirements = ComplianceRequirement.objects.all()
    if reach.is_everything:
        return requirements
    return requirements.filter(
        Q(country=ALL_COUNTRIES) | Q(country__in=list(reach.countries))
    )


def compliance_gaps(principal) -> list:
    """(profile, requirement) pairs with no record at all.

    A mandatory requirement binds every active employee in its country from
    the day it is added, so an employee nobody has recorded yet is missing
    evidence, not absent from the register.
    """
    from apps.accounts.models import StaffProfile
    from apps.hr.models import EmployeeComplianceRecord
    from apps.hr.reach import people_reach, scope_profiles

    requirements = list(
        visible_requirements(principal).filter(is_mandatory=True).order_by("name")
    )
    if not requirements:
        return []
    profiles = (
        scope_profiles(
            StaffProfile.objects.select_related("user").filter(
                user__deleted_at__isnull=True, user__is_active=True
            ),
            people_reach(principal),
        )
        .exclude(onboarding_state="exited")
        .order_by("user__name")
    )
    recorded = set(
        EmployeeComplianceRecord.objects.filter(
            staff_id__in=profiles.values("id"),
            requirement_id__in=[requirement.id for requirement in requirements],
        ).values_list("staff_id", "requirement_id")
    )
    return [
        (profile, requirement)
        for profile in profiles
        for requirement in requirements
        if requirement.country in (ALL_COUNTRIES, profile.country)
        and (profile.id, requirement.id) not in recorded
    ]


@transaction.atomic
def add_requirement(data: dict, principal):
    from apps.hr.models import ComplianceRequirement
    from apps.hr.reach import people_reach

    _assert_hr(principal)
    name = (data.get("name") or "").strip()
    if not name:
        raise BadRequest("Name the requirement.")
    country = (data.get("country") or "").strip()
    if not country:
        raise BadRequest("Choose the country the requirement applies in.")
    reach = people_reach(principal)
    if country == ALL_COUNTRIES:
        if not reach.is_everything:
            raise Forbidden("Only an Admin sets a requirement for every country.")
    elif not reach.allows_country(country):
        raise Forbidden("You may only set requirements for the countries you oversee.")
    if ComplianceRequirement.objects.filter(
        country=country, name__iexact=name
    ).exists():
        raise BadRequest("That requirement already exists for this country.")
    requirement = ComplianceRequirement.objects.create(
        country=country,
        name=name,
        description=(data.get("description") or "").strip() or None,
        is_mandatory=bool(data.get("is_mandatory")),
    )
    _audit(
        "hr.compliance_requirement_added",
        "compliance_requirement",
        requirement.id,
        principal,
        {"country": country, "mandatory": requirement.is_mandatory},
    )
    return requirement


@transaction.atomic
def record_evidence(staff_profile, requirement, data: dict, principal):
    """Create or update one employee's record against one requirement.

    The status is derived from the evidence and its expiry date rather than
    typed, so a lapsed document cannot keep reading "Compliant".
    """
    from apps.hr.models import EmployeeComplianceRecord
    from apps.hr.reach import people_reach

    _assert_hr(principal)
    if staff_profile is None or requirement is None:
        raise BadRequest("Choose the employee and the requirement.")
    if not people_reach(principal).allows_country(staff_profile.country):
        raise Forbidden("You may only record compliance for staff you oversee.")
    if requirement.country not in (ALL_COUNTRIES, staff_profile.country):
        raise BadRequest(
            f"That requirement applies in {requirement.country}, not "
            f"{staff_profile.country}."
        )
    document_url = (data.get("document_url") or "").strip()
    expiry_date = data.get("expiry_date") or None
    verified = bool(data.get("verified"))

    record = (
        EmployeeComplianceRecord.objects.select_for_update()
        .filter(staff=staff_profile, requirement=requirement)
        .first()
    )
    if record is None:
        record = EmployeeComplianceRecord(staff=staff_profile, requirement=requirement)
    record.document_url = document_url or record.document_url
    record.expiry_date = expiry_date
    has_evidence = bool(record.document_url) or verified
    record.status = derived_status(expiry_date=expiry_date, has_evidence=has_evidence)
    if verified:
        record.verified_by_id = getattr(principal, "user_id", None)
        record.verified_at = timezone.now()
    record.save()
    _audit(
        "hr.compliance_evidence_recorded",
        "employee_compliance_record",
        record.id,
        principal,
        {
            "staffId": staff_profile.id,
            "requirementId": requirement.id,
            "status": record.status,
            "verified": verified,
        },
    )
    return record
