"""One SSA per school per financial year: the rule every SSA write reads.

Owner, 2026-10-14: "Manual SSA entry and SSA upload are simply two ways of
creating the same authoritative SSA record. Both must pass through the same
authorization, FY validation, duplicate detection, business-rule validation
and persistence layer." Until then several dated assessments in one year were
kept as monitoring history and only the same school on the same date was a
duplicate; now a school has one SSA a year.

What holds a year is a record that is pending or confirmed (owner, the same
day: a record waiting for its verifier holds the year, so two people cannot
key it while the first waits). A returned or flagged record, and a deleted
one, leave the year free; a returned record keyed on a visit is corrected in
place by its visit (apps.ssa.services.upload), never by a second record.

The year is the record's own ``fy`` (1 October to 30 September,
apps.core.fy), the same year the assessment date gives every record. The
database holds the rule too (``uniq_live_ssa_school_fy`` on SsaRecord): this
module reads it first, so the person keying learns why before anything is
written, and the index refuses the one write that loses a race.

Who may enter a school's SSA from its profile (owner, the same day): a CCEO,
a Programme Lead or Impact Assessment, each for the schools in their own
scope. The file upload keeps its own permission (SSA upload) and the same
check of every row against this rule, in one read for the whole file.
"""

from __future__ import annotations

from contextlib import contextmanager

from django.db import IntegrityError

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole

#: The verification states in which a record holds its school's year.
HOLDING_STATUSES = ("pending", "confirmed")
#: The database's name for the rule (apps.ssa.models.SsaRecord.Meta).
CONSTRAINT = "uniq_live_ssa_school_fy"

#: Who enters a school's SSA from its profile.
ENTRY_ROLES = (
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
)

#: Why an upload row was not imported, as the result table says it.
EXISTING_REASON = "SSA already exists"
IN_FILE_REASON = "Duplicate of row {row} in this file"


def current_fy() -> str:
    """The financial year today falls in, read on the local calendar day
    (1 October in Kampala is already the new year) from the FY engine."""
    from django.utils import timezone

    from apps.core.fy import get_operational_fy

    return get_operational_fy(timezone.localdate())


def duplicate_message(fy: str) -> str:
    return f"SSA already exists for this school for FY{fy}. The record was not added."


class SsaAlreadyExists(BadRequest):
    """The school's year is already held by a pending or confirmed SSA."""

    def __init__(self, fy: str):
        self.fy = str(fy)
        super().__init__(duplicate_message(self.fy))


def _holding(queryset):
    return queryset.filter(
        deleted_at__isnull=True, verification_status__in=HOLDING_STATUSES
    )


def held_years(pairs) -> set[tuple[str, str]]:
    """Which (school pk, fy) pairs already hold an SSA: one read for any
    number of pairs, so an upload checks every row before it writes any."""
    from apps.ssa.models import SsaRecord

    pairs = {(str(s), str(f)) for s, f in pairs if s and f}
    if not pairs:
        return set()
    found = _holding(
        SsaRecord.objects.filter(
            school_id__in={s for s, _f in pairs}, fy__in={f for _s, f in pairs}
        )
    ).values_list("school_id", "fy")
    return {(str(s), str(f)) for s, f in found} & pairs


def held_years_of_schools(school_pks) -> set[tuple[str, str]]:
    """Every (school pk, fy) these schools hold, whatever the year: one read
    for a whole file whose rows name years of their own."""
    from apps.ssa.models import SsaRecord

    pks = {str(pk) for pk in school_pks if pk}
    if not pks:
        return set()
    return {
        (str(s), str(f))
        for s, f in _holding(SsaRecord.objects.filter(school_id__in=pks))
        .values_list("school_id", "fy")
        .distinct()
    }


def year_record(school, fy: str | None = None):
    """The record holding ``school``'s year (the operational year by
    default), confirmed first; None when the year is free."""
    from apps.ssa.models import SsaRecord

    school_pk = getattr(school, "pk", school)
    fy = str(fy or current_fy())
    records = list(
        _holding(SsaRecord.objects.filter(school_id=school_pk, fy=fy))
        .prefetch_related("scores")
        .order_by("-date_of_ssa")
    )
    records.sort(key=lambda r: r.verification_status != "confirmed")
    return records[0] if records else None


def assert_year_free(school, fy: str, *, exclude_pk=None) -> None:
    """Refuse a write that would give ``school`` a second SSA for ``fy``.
    `exclude_pk` is the record being corrected in place, which already holds
    the year and may go on holding it."""
    from apps.ssa.models import SsaRecord

    held = _holding(
        SsaRecord.objects.filter(school_id=getattr(school, "pk", school), fy=str(fy))
    )
    if exclude_pk:
        held = held.exclude(pk=exclude_pk)
    if held.exists():
        raise SsaAlreadyExists(fy)


@contextmanager
def year_guard(fy: str):
    """The database's answer to a race, in the reader's words: the write that
    lost it raises SsaAlreadyExists instead of an integrity error. Wrap the
    write in its own savepoint (transaction.atomic) so the caller's
    transaction survives the refusal."""
    try:
        yield
    except IntegrityError as exc:
        if CONSTRAINT in str(exc):
            raise SsaAlreadyExists(fy) from exc
        raise


def source_label(record) -> str:
    """Where a record's scores came from, in the words the SSA pages use
    (the record's own verification_source; no new categories)."""
    from apps.ssa import services as svc

    return {
        svc.SOURCE_STAFF_KEYED: "Keyed on a visit"
        if record.source_activity_id
        else "Keyed by staff",
        svc.SOURCE_IA_KEYED: "Keyed by Impact Assessment",
        svc.SOURCE_FILE_IMPORT: "File import",
        svc.SOURCE_PARTNER: "Partner submission",
    }.get(record.verification_source or "", "Recorded")


# ── Who may enter from a school's profile ───────────────────────────────────


def may_enter_role(user) -> bool:
    return getattr(user, "active_role", "") in ENTRY_ROLES


def school_in_scope(user, school) -> bool:
    """Whether ``school`` is one of the schools the user works with: the
    same scoped school list the user's directory and planning read."""
    from apps.core.scoping import resolve_user_scope, school_queryset

    schools = school_queryset(resolve_user_scope(user))
    if schools is None:
        return False
    return schools.filter(pk=getattr(school, "pk", school)).exists()


def assert_may_enter(user, school) -> None:
    """The backend's answer, whatever the page showed: the role, then the
    school's place in the user's scope."""
    if not may_enter_role(user):
        raise Forbidden(
            "Only a CCEO, a Programme Lead or Impact Assessment enters SSA scores."
        )
    if getattr(school, "is_closed", False) or not school_in_scope(user, school):
        raise Forbidden("This school is not in your scope.")


def entry_state(user, school) -> dict:
    """The profile's Enter SSA Score: shown to the roles that enter scores
    on an open school in their scope, enabled while the school's current
    year has no SSA, and greyed with the reason once it has one.

    The year's record is read from the database on every profile load; a
    record a file upload added an hour ago greys the button as one keyed
    here does."""
    fy = current_fy()
    record = year_record(school, fy)
    show = (
        may_enter_role(user)
        and not getattr(school, "is_closed", False)
        and school_in_scope(user, school)
    )
    return {
        "ssa_year_source": source_label(record) if record else "",
        "ssa_entry_shown": show,
        "ssa_entry_fy": fy,
        "ssa_year_record": record,
        "ssa_entry_block": f"SSA already entered for FY{fy}" if record else "",
    }


__all__ = [
    "CONSTRAINT",
    "ENTRY_ROLES",
    "EXISTING_REASON",
    "HOLDING_STATUSES",
    "IN_FILE_REASON",
    "SsaAlreadyExists",
    "assert_may_enter",
    "assert_year_free",
    "current_fy",
    "duplicate_message",
    "entry_state",
    "held_years",
    "held_years_of_schools",
    "may_enter_role",
    "school_in_scope",
    "source_label",
    "year_guard",
    "year_record",
]
