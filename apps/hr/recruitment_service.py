"""Recruitment, and the handoff into provisioning that never existed.

The audit found no code path at all between an accepted candidate and an
account: nothing wrote `Application.stage = "Hired"`, no signal or service
connected the two, and `admin_users.services.create` took no candidate
reference of any kind. In practice HR re-keyed the person's name, email and
phone into an empty modal, so nothing reconciled the created account against
a candidate and nothing recorded who authorised the hire.

Policy note: HR retains the provisioning permission (confirmed 2026-07-21),
so the handoff is built HR-side — `hire()` provisions directly through the
canonical `admin_users.services.create`, which carries the guard rails, the
invitation path and the audit row.

Every transition here records who decided and why, and lands on the
tamper-evident chain.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.hr.models import (
    Application,
    ApplicationStage,
    Candidate,
    OnboardingPlan,
    OnboardingStatus,
    Vacancy,
    VacancyStatus,
)

#: Roles that may run recruitment. HR owns it; Admin can act anywhere.
_RECRUITER_ROLES = {"HumanResources", "Admin"}
#: Who may approve a vacancy — never the person who requested it.
_VACANCY_APPROVER_ROLES = {"CountryDirector", "RegionalVicePresident", "Admin"}


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _country(principal) -> str | None:
    return getattr(getattr(principal, "staff_profile", None), "country", None)


def _assert_recruiter(principal) -> None:
    if _role(principal) not in _RECRUITER_ROLES:
        raise Forbidden("Only HR may manage recruitment.")


def _assert_in_country(principal, country: str) -> None:
    """HR is a country function. Admin is not bound."""
    if _role(principal) == "Admin":
        return
    actor = _country(principal)
    if not actor:
        raise Forbidden("Your staff profile has no country.")
    if country and country != actor:
        raise Forbidden(f"You may only manage recruitment for {actor}.")


def _audit(action: str, subject_kind: str, subject_id: str, principal, payload=None):
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind=subject_kind,
        subject_id=subject_id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload=payload or {},
    )


# ── Vacancies ────────────────────────────────────────────────────────────────


def scoped_vacancies(principal):
    qs = Vacancy.objects.all()
    if _role(principal) == "Admin":
        return qs
    country = _country(principal)
    return qs.filter(country=country) if country else qs.none()


@transaction.atomic
def request_vacancy(data: dict, principal) -> Vacancy:
    """Raise a workforce need. Starts as a request, not an open post."""
    _assert_recruiter(principal)
    country = (data.get("country") or _country(principal) or "").strip()
    if not country:
        raise BadRequest("A country is required.")
    _assert_in_country(principal, country)
    role = (data.get("role") or "").strip()
    if not role:
        raise BadRequest("A role is required.")

    vacancy = Vacancy.objects.create(
        country=country,
        department=(data.get("department") or "").strip(),
        role=role,
        employment_type=data.get("employment_type") or "Full-time",
        reason_for_vacancy=data.get("reason") or "",
        replacement_or_new_role=data.get("replacement_or_new_role") or "new_role",
        required_skills=data.get("required_skills") or "",
        target_start_date=data.get("target_start_date") or None,
        approved_salary_band=data.get("salary_band") or None,
        budget_source=data.get("budget_source") or None,
        status=VacancyStatus.PENDING_APPROVAL,
        requested_by_id=getattr(principal, "user_id", None),
    )
    _audit("hr.vacancy_requested", "vacancy", vacancy.id, principal, {"role": role})
    return vacancy


@transaction.atomic
def approve_vacancy(vacancy_id: str, principal, *, reason: str = "") -> Vacancy:
    """Approve a requested post. Never the requester."""
    vacancy = Vacancy.objects.select_for_update().filter(id=vacancy_id).first()
    if not vacancy:
        raise BadRequest("Vacancy not found.")
    if _role(principal) not in _VACANCY_APPROVER_ROLES:
        raise Forbidden("Only country leadership may approve a vacancy.")
    _assert_in_country(principal, vacancy.country)
    if vacancy.requested_by_id and vacancy.requested_by_id == getattr(
        principal, "user_id", None
    ):
        raise Forbidden("You cannot approve a vacancy you requested.")
    if vacancy.status != VacancyStatus.PENDING_APPROVAL:
        raise BadRequest("This vacancy is not awaiting approval.")

    vacancy.status = VacancyStatus.OPEN
    vacancy.approved_by_id = getattr(principal, "user_id", None)
    vacancy.approved_at = timezone.now()
    vacancy.decision_reason = reason or ""
    vacancy.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "decision_reason",
            "updated_at",
        ]
    )
    _audit("hr.vacancy_approved", "vacancy", vacancy.id, principal, {"reason": reason})
    return vacancy


@transaction.atomic
def close_vacancy(vacancy_id: str, principal, *, reason: str = "") -> Vacancy:
    _assert_recruiter(principal)
    vacancy = Vacancy.objects.select_for_update().filter(id=vacancy_id).first()
    if not vacancy:
        raise BadRequest("Vacancy not found.")
    _assert_in_country(principal, vacancy.country)
    vacancy.status = VacancyStatus.CLOSED
    vacancy.closed_at = timezone.now()
    vacancy.decision_reason = reason or vacancy.decision_reason
    vacancy.save(
        update_fields=["status", "closed_at", "decision_reason", "updated_at"]
    )
    _audit("hr.vacancy_closed", "vacancy", vacancy.id, principal, {"reason": reason})
    return vacancy


# ── Candidates and applications ──────────────────────────────────────────────


@transaction.atomic
def record_application(data: dict, principal) -> Application:
    """Register a candidate against an open vacancy.

    Deduplicates on the canonical name normaliser rather than a second
    implementation — `Candidate.email` is unique at the DB level, which
    produces an IntegrityError rather than a usable message.
    """
    _assert_recruiter(principal)
    vacancy = Vacancy.objects.filter(id=data.get("vacancy_id")).first()
    if not vacancy:
        raise BadRequest("Vacancy not found.")
    _assert_in_country(principal, vacancy.country)
    if vacancy.status != VacancyStatus.OPEN:
        raise BadRequest("This vacancy is not open for applications.")

    email = (data.get("email") or "").strip().lower()
    name = (data.get("name") or "").strip()
    if not email or not name:
        raise BadRequest("A candidate name and email are required.")

    candidate = Candidate.objects.filter(email=email).first()
    if candidate is None:
        candidate = Candidate.objects.create(
            name=name,
            email=email,
            phone=(data.get("phone") or "").strip() or None,
            skills=data.get("skills") or "",
            # Applicant data is personal data about someone who does not work
            # here; record consent and a retention horizon at intake.
            consent_given_at=timezone.now() if data.get("consent") else None,
            retention_until=data.get("retention_until") or None,
        )

    if Application.objects.filter(vacancy=vacancy, candidate=candidate).exists():
        raise BadRequest("This candidate has already applied for this vacancy.")

    application = Application.objects.create(
        vacancy=vacancy, candidate=candidate, stage=ApplicationStage.APPLIED
    )
    _audit(
        "hr.application_recorded",
        "application",
        application.id,
        principal,
        {"vacancyId": vacancy.id, "candidateId": candidate.id},
    )
    return application


#: Legal forward moves. A stage change that is not here is refused, so the
#: pipeline cannot skip an assessment or jump straight to an offer.
_STAGE_FLOW = {
    ApplicationStage.APPLIED: {ApplicationStage.SCREENING, ApplicationStage.REJECTED},
    ApplicationStage.SCREENING: {
        ApplicationStage.INTERVIEW,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.INTERVIEW: {
        ApplicationStage.ASSESSMENT,
        ApplicationStage.REFERENCE_CHECK,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.ASSESSMENT: {
        ApplicationStage.REFERENCE_CHECK,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.REFERENCE_CHECK: {
        ApplicationStage.OFFER,
        ApplicationStage.REJECTED,
    },
    ApplicationStage.OFFER: {
        ApplicationStage.ACCEPTED,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    },
    ApplicationStage.ACCEPTED: {ApplicationStage.HIRED, ApplicationStage.WITHDRAWN},
}


@transaction.atomic
def advance_application(
    application_id: str, principal, *, to_stage: str, reason: str = "", **extra
) -> Application:
    """Move an application one legal step, recording who and why."""
    _assert_recruiter(principal)
    app = (
        Application.objects.select_for_update()
        .select_related("vacancy", "candidate")
        .filter(id=application_id)
        .first()
    )
    if not app:
        raise BadRequest("Application not found.")
    _assert_in_country(principal, app.vacancy.country)

    allowed = _STAGE_FLOW.get(app.stage, set())
    if to_stage not in allowed:
        raise BadRequest(
            f"An application at '{app.get_stage_display()}' cannot move to "
            f"'{dict(ApplicationStage.choices).get(to_stage, to_stage)}'."
        )
    if to_stage in (ApplicationStage.REJECTED, ApplicationStage.OFFER) and not (
        reason or ""
    ).strip():
        raise BadRequest("A reason is required for this decision.")

    app.stage = to_stage
    app.decision_reason = reason or app.decision_reason
    for field in ("interview_panel", "assessment_result", "reference_check_note"):
        if extra.get(field):
            setattr(app, field, extra[field])
    if to_stage == ApplicationStage.OFFER:
        app.offer_approved_by_id = getattr(principal, "user_id", None)
    if to_stage == ApplicationStage.ACCEPTED:
        app.offer_accepted_at = timezone.now()
    app.save()
    _audit(
        f"hr.application_{to_stage}",
        "application",
        app.id,
        principal,
        {"reason": reason, "candidateId": app.candidate_id},
    )
    return app


# ── The handoff ──────────────────────────────────────────────────────────────


@transaction.atomic
def hire(application_id: str, principal, *, provisioning: dict) -> dict:
    """Turn an accepted candidate into a provisioned employee.

    THE missing link. Carries the candidate's identity through so nobody
    re-keys it, provisions through the canonical service (guard rails,
    invitation path, audit row), records the resulting user back on the
    application so an account can always be reconciled to a hire, and opens
    the onboarding plan.
    """
    _assert_recruiter(principal)
    app = (
        Application.objects.select_for_update()
        .select_related("vacancy", "candidate")
        .filter(id=application_id)
        .first()
    )
    if not app:
        raise BadRequest("Application not found.")
    _assert_in_country(principal, app.vacancy.country)
    if app.stage != ApplicationStage.ACCEPTED:
        raise BadRequest("Only an accepted offer can be provisioned.")
    if app.provisioned_user_id:
        raise BadRequest("This candidate has already been provisioned.")

    from apps.admin_users.services import create as create_user

    payload = {
        # Identity comes from the candidate record, not from re-typing.
        "email": app.candidate.email,
        "name": app.candidate.name,
        "phone": app.candidate.phone,
        "role": provisioning.get("role") or app.vacancy.role,
        "additionalRoles": provisioning.get("additionalRoles") or [],
        "primaryDistrictId": provisioning.get("primaryDistrictId"),
        "additionalDistrictIds": provisioning.get("additionalDistrictIds") or [],
        "supervisorStaffId": provisioning.get("supervisorStaffId") or "",
        "country": app.vacancy.country,
        "department": app.vacancy.department or None,
    }
    # No password: the new employee sets their own from a one-time invitation.
    result = create_user(payload, principal)

    from apps.accounts.models import StaffProfile, User

    user = User.objects.filter(email=app.candidate.email.lower()).first()
    app.provisioned_user = user
    app.provisioned_at = timezone.now()
    app.stage = ApplicationStage.HIRED
    app.save(
        update_fields=["provisioned_user", "provisioned_at", "stage", "updated_at"]
    )

    plan = None
    profile = StaffProfile.objects.filter(user=user).first()
    if profile:
        from apps.hr.onboarding_service import open_onboarding

        plan = open_onboarding(profile, principal, application=app)

    _audit(
        "hr.candidate_hired",
        "application",
        app.id,
        principal,
        {
            "candidateId": app.candidate_id,
            "vacancyId": app.vacancy_id,
            "userId": getattr(user, "id", None),
            "onboardingPlanId": getattr(plan, "id", None),
        },
    )
    return {
        "applicationId": app.id,
        "userId": getattr(user, "id", None),
        "onboardingPlanId": getattr(plan, "id", None),
        "inviteToken": result.get("inviteToken"),
    }
