"""Who reviews whom — the one answer, used by every performance surface.

The rule, as the organisation states it:

    Program Leads review the CCEOs they supervise.
    The Country Director reviews Program Leads, Impact Assessment and the
        Accountant — and the other country-level staff reporting to them.
    HR oversees the whole thing. HR does not conduct reviews.

Three separate defects came from not having this in one place:

  * `PerformanceReview.manager` was written once, when the cycle opened, and
    never again. Reassigning someone's supervisor updated the supervisor link
    and left the review pointing at the person they had left — who kept the
    authority to rate them for the rest of the year.
  * The supervisor lookups filtered on nothing but the link's existence, so an
    Impact Assessment or RVP *oversight* row — which the model documents as
    explicitly NOT the reporting line — satisfied "is this their manager?".
  * None of the lookups filtered on employment state, so a suspended or exited
    manager kept approving and rating.

So authority is resolved LIVE, from the current link, and only when that
link's holder is the role the rule says should hold it.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

CCEO = "CCEO"
PROGRAM_LEAD = "Program Lead"
COUNTRY_DIRECTOR = "CountryDirector"
RVP = "RegionalVicePresident"
IMPACT_ASSESSMENT = "ImpactAssessment"
ACCOUNTANT = "Accountant"
HUMAN_RESOURCES = "HumanResources"
PROJECT_COORDINATOR = "ProjectCoordinator"
ADMIN = "Admin"

# Reviewee role → the role that conducts their performance review.
REVIEWER_ROLE_FOR = {
    CCEO: (PROGRAM_LEAD,),
    PROGRAM_LEAD: (COUNTRY_DIRECTOR,),
    IMPACT_ASSESSMENT: (COUNTRY_DIRECTOR,),
    ACCOUNTANT: (COUNTRY_DIRECTOR,),
    PROJECT_COORDINATOR: (COUNTRY_DIRECTOR,),
    HUMAN_RESOURCES: (COUNTRY_DIRECTOR,),
    COUNTRY_DIRECTOR: (RVP,),
    RVP: (ADMIN,),
}

# HR and Admin govern the cycle: they may return an incomplete review, hold it
# open, refer it to calibration and validate it. They may never write the
# manager's assessment or rating — that is the manager's judgment, and a
# governance role writing it would erase the thing it exists to assure.
OVERSIGHT_ROLES = (HUMAN_RESOURCES, "Human Resources", ADMIN)

# Employment states in which a person still holds authority.
LIVE_STATES = ("active", "pending")


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def is_oversight(principal) -> bool:
    """HR/Admin: govern the cycle, never conduct the review."""
    return _role(principal) in OVERSIGHT_ROLES


def reviewer_profiles_for(staff_profile):
    """The StaffProfiles entitled to review this person, as a queryset.

    Normally exactly one. More than one means two people hold the same
    reporting link, which HR Today reports as a people-risk exception rather
    than silently picking whichever the database returns first.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    user = getattr(staff_profile, "user", None)
    expected = REVIEWER_ROLE_FOR.get(getattr(user, "active_role", ""), ())
    if not expected:
        return StaffProfile.objects.none()
    supervisor_ids = StaffSupervisorAssignment.objects.filter(
        supervisee_id=staff_profile.id
    ).values_list("supervisor_id", flat=True)
    return StaffProfile.objects.filter(
        id__in=list(supervisor_ids),
        user__active_role__in=expected,
        user__is_active=True,
        user__deleted_at__isnull=True,
        onboarding_state__in=LIVE_STATES,
    ).select_related("user")


def reviewer_for(staff_profile):
    """The single StaffProfile who conducts this person's review, or None."""
    return reviewer_profiles_for(staff_profile).first()


def _covering_for(profile_ids, now=None):
    """Staff currently standing in for any of these people.

    Authority moves with an approved coverage assignment — that is what the
    coverage mechanism is for — but only for the window it names.
    """
    from apps.accounts.models import TemporaryCoverageAssignment

    now = now or timezone.now()
    return set(
        TemporaryCoverageAssignment.objects.filter(
            original_staff_id__in=list(profile_ids),
            status="active",
            start_datetime__lte=now,
            end_datetime__gte=now,
        ).values_list("covering_staff_id", flat=True)
    )


def is_reviewer_of(staff_profile, principal) -> bool:
    """May this principal write the manager channels for this person?

    True for the resolved reviewer, and for anyone actively covering them.
    Never true for the person themselves, for an oversight role, or for a
    supervisor whose row is an oversight row rather than the reporting line.
    """
    principal_profile_id = getattr(principal, "staff_profile_id", None) or getattr(
        getattr(principal, "staff_profile", None), "id", None
    )
    if not principal_profile_id:
        return False
    if principal_profile_id == getattr(staff_profile, "id", None):
        return False  # nobody reviews themselves
    reviewers = list(reviewer_profiles_for(staff_profile).values_list("id", flat=True))
    if not reviewers:
        return False
    if principal_profile_id in reviewers:
        return True
    return principal_profile_id in _covering_for(reviewers)


def assert_reviewer(staff_profile, principal, action: str = "assess") -> None:
    from apps.core.exceptions import Forbidden

    if is_reviewer_of(staff_profile, principal):
        return
    reviewer = reviewer_for(staff_profile)
    who = getattr(getattr(reviewer, "user", None), "name", None) if reviewer else None
    if is_oversight(principal):
        raise Forbidden(
            f"HR oversees the cycle but does not {action} on a manager's "
            f"behalf. Return the review to "
            f"{who or 'the manager'} instead."
        )
    raise Forbidden(f"Only {who or 'the reporting manager'} may {action} this review.")


def reviewees_of(principal):
    """Everyone this principal is the performance reviewer for."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    profile_id = getattr(principal, "staff_profile_id", None) or getattr(
        getattr(principal, "staff_profile", None), "id", None
    )
    if not profile_id:
        return StaffProfile.objects.none()
    role = _role(principal)
    reviewable = [
        reviewee
        for reviewee, reviewers in REVIEWER_ROLE_FOR.items()
        if role in reviewers
    ]
    if not reviewable:
        return StaffProfile.objects.none()
    supervisee_ids = StaffSupervisorAssignment.objects.filter(
        supervisor_id=profile_id
    ).values_list("supervisee_id", flat=True)
    return StaffProfile.objects.filter(
        Q(id__in=list(supervisee_ids)), user__active_role__in=reviewable
    ).select_related("user")
