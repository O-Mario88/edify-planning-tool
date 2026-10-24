"""A Core school's cohort: the year it joined and its cohort number.

Owner, 2026-10-24: "categorize core schools into cohort. Using the Year and
the cohort number ... it can only be set once ... it should be on the core
school profile in the edit school drawer". Answered the same day: users set
it directly in the Edit school drawer; choosing Core asks for the cohort
number and year; once saved it is locked for everyone ("Locked once saved"),
and only an Admin corrects a mistake, every change logged.

The cohort stays on the school when it later becomes Core Graduate or Core
Trained: it says which cohort the school came through.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest

#: The earliest year a cohort can be from, and how many cohorts a year can
#: have. The latest is next year: a school recruited now for the coming year.
FIRST_YEAR = 2000
MAX_NUMBER = 99
CORE = "core"


def label(school) -> str:
    """ "Cohort 3 · 2025", or "" for a school with no cohort."""
    if school.core_cohort_year is None or school.core_cohort_number is None:
        return ""
    return f"Cohort {school.core_cohort_number} · {school.core_cohort_year}"


def is_locked(school) -> bool:
    """Set once: a school with a cohort keeps it."""
    return bool(label(school))


def may_correct(principal) -> bool:
    """Only an Admin corrects a cohort once it is set."""
    return getattr(principal, "active_role", "") == "Admin"


def latest_year() -> int:
    return timezone.localdate().year + 1


def _whole(raw: str, what: str, low: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"{what} must be a whole number.") from exc
    if not low <= value <= high:
        raise BadRequest(f"{what} must be between {low} and {high}.")
    return value


def read(post, school, principal, school_type: str) -> tuple[int, int] | None:
    """The cohort this edit leaves the school with, or None for none.

    A locked cohort is kept: anyone but an Admin who asks for another is
    refused, so the edit is not saved behind their back with the old one. A
    Core school must have one. Any other type takes none, and keeps the one
    it came through Core with."""
    year_raw = (post.get("core_cohort_year") or "").strip()
    number_raw = (post.get("core_cohort_number") or "").strip()
    current = (
        (school.core_cohort_year, school.core_cohort_number)
        if is_locked(school)
        else None
    )
    asked = bool(year_raw or number_raw)
    if current is not None and not (asked and may_correct(principal)):
        if asked and (year_raw, number_raw) != tuple(str(v) for v in current):
            raise BadRequest(
                f"This school's cohort is set ({label(school)}) and locked. "
                "Ask an Admin to correct it."
            )
        return current
    if school_type != CORE and current is None:
        return None
    if not year_raw or not number_raw:
        raise BadRequest(
            "A Core school needs its cohort: enter the cohort year and the "
            "cohort number."
        )
    return (
        _whole(year_raw, "Cohort year", FIRST_YEAR, latest_year()),
        _whole(number_raw, "Cohort number", 1, MAX_NUMBER),
    )


def apply(school, chosen: tuple[int, int] | None, principal) -> dict | None:
    """Put ``chosen`` on the school (unsaved) and say what changed, for the
    audit log; None when nothing did."""
    before = (school.core_cohort_year, school.core_cohort_number)
    if chosen is None or chosen == before:
        return None
    school.core_cohort_year, school.core_cohort_number = chosen
    school.core_cohort_set_at = timezone.now()
    school.core_cohort_set_by_id = getattr(principal, "user_id", None) or getattr(
        principal, "id", None
    )
    previous = None if None in before else {"year": before[0], "number": before[1]}
    return {
        "action": "school.cohort_corrected" if previous else "school.cohort_set",
        "previous": previous,
        "cohort": {"year": chosen[0], "number": chosen[1]},
    }


def log(school, change: dict, principal) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=change["action"],
        subject_kind="school",
        subject_id=school.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "school_id": school.school_id,
            "previous": change["previous"],
            "cohort": change["cohort"],
        },
    )


__all__ = [
    "FIRST_YEAR",
    "MAX_NUMBER",
    "apply",
    "is_locked",
    "label",
    "latest_year",
    "log",
    "may_correct",
    "read",
]
