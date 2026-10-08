"""Whether a school has completed its SSA for a financial year.

Owner, 2026-10-08: SSA Support "can only be assigned to schools that do NOT
have an SSA score for the current FY", and, asked what having one means, "the
school has completed SSA this year (FY2027)". The year is the record's own
``fy`` (1 October to 30 September, `apps.core.fy`), never "the last 365 days"
and never "has it ever been assessed": an SSA of FY2026 is not FY2027's.

Completed is confirmed, which is also when a school's SSA status reads Done
and when an SSA starts to count anywhere else (`apps.ssa.models`). A record
still waiting for its verifier is not a completed SSA yet, and one a verifier
returned or flagged is not one either: the school stays open to SSA Support
until an SSA of the year is confirmed.
"""

from __future__ import annotations

#: The verification states in which a record is the year's completed SSA.
CURRENT_SSA_STATUSES = ("confirmed",)


def schools_with_ssa(school_ids, fy: str | None = None) -> set[str]:
    """Which of these schools have completed an SSA for ``fy`` (the
    operational year by default). One query whatever the count."""
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord

    ids = [i for i in school_ids if i]
    if not ids:
        return set()
    return set(
        SsaRecord.objects.filter(
            school_id__in=ids,
            fy=str(fy or get_operational_fy()),
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
        .values_list("school_id", flat=True)
        .distinct()
    )


def has_ssa(school, fy: str | None = None) -> bool:
    return bool(schools_with_ssa([getattr(school, "id", school)], fy))


__all__ = ["CURRENT_SSA_STATUSES", "has_ssa", "schools_with_ssa"]
