"""What a school's record is missing, said one way.

Owner, 2026-10-10: "can we make sure that all the school hidden because it
lacks certain data all unhidden so that the staff can update their data.
other dont have owners, other dont have ssa, others don't have district".

Read on production that day: Planning counted 15,167 schools as "Data Cleanup
Required" and its filter of that name listed none of them, because the count
read the school's fields and the filter read a stored label that nothing had
written; and the School Directory said "No SSA: 16,152" for FY 2025/26 while
14,818 of those schools held a confirmed SSA of that year, because it read a
flag that is reset when the year turns.

So a gap is a condition on the school's own record (`GAPS`), never a stored
label: every page that counts a gap and every page that lists it read the
same `Q`, and a school leaves the list the moment the field is filled.

A school nobody holds is `unheld` — no responsible staff member on the
record and no staff portfolio that carries it. Those are shown to every
field officer and Programme Lead of the country (owner's answer, 2026-10-10:
"All field staff, whole country"), who can complete the record and take the
school (`take`), since a school only its own holder could see had nobody to
see it.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

__all__ = [
    "ANY",
    "open_to",
    "GAPS",
    "LABELS",
    "counts",
    "gap_q",
    "missing",
    "no_ssa_q",
    "take",
    "unheld",
    "unheld_q",
]

#: Blank is as missing as null: an upload writes either.
_NO_OWNER = Q(account_owner_id__isnull=True) | Q(account_owner_id="")
_NO_SCHOOL_ID = Q(school_id__isnull=True) | Q(school_id="")
_NO_CLUSTER = Q(cluster_id__isnull=True) | Q(cluster_id="")
_NO_TYPE = Q(school_type__isnull=True) | Q(school_type="")

#: Each gap of a school's own record: key → (label, condition).
GAPS = {
    "no_owner": ("No Responsible Staff", _NO_OWNER),
    "no_district": ("No District", Q(district_id__isnull=True)),
    "no_sub_county": ("No Sub-county", Q(sub_county_id__isnull=True)),
    "no_cluster": ("No Cluster", _NO_CLUSTER),
    "no_type": ("No School Type", _NO_TYPE),
    "no_enrolment": (
        "No Enrolment",
        Q(enrollment__isnull=True) | Q(enrollment=0),
    ),
    "no_school_id": ("No School ID", _NO_SCHOOL_ID),
}
#: Any of them.
ANY = "any"
#: No confirmed SSA in the year asked about: a condition on the SSA records,
#: not on the school's own fields, so it takes the year.
NO_SSA = "no_ssa"
LABELS = {
    ANY: "Any Missing Detail",
    **{key: label for key, (label, _q) in GAPS.items()},
    NO_SSA: "No Confirmed SSA",
}

#: What Planning calls "Data Cleanup Required": the details a visit or a
#: training cannot be planned without (`planning_service.get_school_readiness`).
PLANNING_BLOCKERS = ("no_district", "no_sub_county", "no_owner", "no_school_id")


def no_ssa_q(fy) -> Q:
    """Schools with no confirmed SSA record of ``fy``."""
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord

    return ~Exists(
        SsaRecord.objects.filter(
            school_id=OuterRef("pk"),
            fy=str(fy),
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
    )


def gap_q(gap: str, fy=None) -> Q | None:
    """The condition for ``gap``; None for a key that names none."""
    if gap == ANY:
        any_of = Q()
        for _label, condition in GAPS.values():
            any_of |= condition
        return any_of
    if gap == NO_SSA:
        return no_ssa_q(fy) if fy else None
    if gap in GAPS:
        return GAPS[gap][1]
    return None


def planning_blockers_q() -> Q:
    blockers = Q()
    for key in PLANNING_BLOCKERS:
        blockers |= GAPS[key][1]
    return blockers


def counts(schools, fy=None) -> dict[str, int]:
    """How many of ``schools`` have each gap, any gap, and — for ``fy`` — no
    confirmed SSA. One query."""
    from django.db.models import Count

    figures = {
        key: Count("id", filter=condition) for key, (_label, condition) in GAPS.items()
    }
    figures[ANY] = Count("id", filter=gap_q(ANY))
    if fy:
        figures[NO_SSA] = Count("id", filter=no_ssa_q(fy))
    return schools.aggregate(**figures)


def missing(school) -> list[str]:
    """What this school's record lacks, as the labels a reader is shown."""
    found = []
    checks = (
        ("no_owner", not school.account_owner_id),
        ("no_district", not school.district_id),
        ("no_sub_county", not school.sub_county_id),
        ("no_cluster", not school.cluster_id),
        ("no_type", not school.school_type),
        ("no_enrolment", not school.enrollment),
        ("no_school_id", not school.school_id),
    )
    for key, lacking in checks:
        if lacking:
            found.append(GAPS[key][0])
    return found


# ── Schools nobody holds ────────────────────────────────────────────────────
def unheld_q() -> Q:
    """No responsible staff member on the record, and in nobody's portfolio."""
    from apps.accounts.models import StaffSchoolAssignment

    return _NO_OWNER & ~Exists(
        StaffSchoolAssignment.objects.filter(school_id=OuterRef("pk"))
    )


def unheld(country: str = ""):
    """The operating schools of ``country`` that nobody holds."""
    from apps.core.scoping import school_in_country_q
    from apps.schools.lifecycle_service import active_schools

    schools = active_schools().filter(unheld_q())
    if country:
        schools = schools.filter(school_in_country_q(country))
    return schools


#: Who may see and take an unheld school: the people who hold schools.
FIELD_ROLES = ("CCEO", "Program Lead")


def may_take(principal) -> bool:
    return getattr(principal, "active_role", "") in FIELD_ROLES and bool(
        getattr(principal, "staff_profile_id", None)
        or getattr(getattr(principal, "staff_profile", None), "id", None)
    )


def country_of(principal) -> str:
    """The country a field officer works in: their staff profile's. (A
    scope names a country only for a country-wide role.)"""
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=principal.id)
        .values_list("country", flat=True)
        .first()
        or ""
    )


def open_to(principal, school_id) -> bool:
    """May ``principal`` open and complete this school although it is not
    theirs? Yes when nobody holds it and they are field staff of its country
    (owner, 2026-10-10: "All field staff, whole country")."""
    if not may_take(principal):
        return False
    return unheld(country_of(principal)).filter(id=school_id).exists()


def take(school, principal):
    """``principal`` becomes the school's responsible staff member: the
    record names them and their portfolio carries it, as an upload that
    matched their name would have done. Only a school nobody holds can be
    taken — a held school changes hands by an ownership transfer."""
    from django.db import transaction

    from apps.accounts.models import StaffProfile, StaffSchoolAssignment
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.schools.models import School

    if not may_take(principal):
        raise Forbidden("Only a field officer or a Programme Lead takes a school.")
    staff = StaffProfile.objects.filter(user_id=principal.id).first()
    if staff is None:
        raise Forbidden("Your account has no staff profile to hold a school.")
    with transaction.atomic():
        locked = School.objects.select_for_update().filter(id=school.id).first()
        if locked is None or not unheld().filter(id=locked.id).exists():
            raise BadRequest(
                "This school already has a responsible staff member. Ask Impact "
                "Assessment to transfer it."
            )
        locked.account_owner_id = staff.id
        locked.account_owner_name_raw = principal.name or locked.account_owner_name_raw
        locked.account_owner_status = "matched"
        locked.save(
            update_fields=[
                "account_owner_id",
                "account_owner_name_raw",
                "account_owner_status",
                "updated_at",
            ]
        )
        StaffSchoolAssignment.objects.get_or_create(staff=staff, school_id=locked.id)
        from apps.audit.services import log as audit_log

        audit_log(
            action="school.taken",
            subject_kind="School",
            subject_id=locked.id,
            payload={"staff_id": staff.id, "school_id": locked.school_id},
        )
    return locked
