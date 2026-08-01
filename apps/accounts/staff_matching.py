"""StaffMatchingService — resolve an uploaded "Staff Name" to a real staff profile.

The ownership bridge between uploaded schools and staff user profiles. A name is
matched only against field-staff users (CCEO / PL) so a same-named Accountant or
HR user is never auto-linked to a school. Ambiguous names (≥2 field-staff users
share the name) return AMBIGUOUS and are sent to Admin review — never guessed.

Matching is case-insensitive + whitespace-normalized (so "Ojok Amos",
"ojok amos", "OJOK  AMOS" all match). Fuzzy matching is deliberately NOT used
for auto-linking; it is unsafe at the ownership level.
"""

from __future__ import annotations

import re

from apps.core.enums import AccountOwnerStatus


# The field-staff roles that may own a school. A name resolves only against
# users holding one of these roles (so an IA/Accountant/HR/CD user with the same
# name is never silently linked to a school).
OWNER_ROLES = ("CCEO", "Program Lead")

#: Statuses that mean "this person is still on the team".
#:
#: `is_active` answers "may this account sign in?", which is NOT the same
#: question as "does this person hold work?". Staff auto-created by a school
#: upload are born `is_active=False`, `pending_invited` — the invite has not
#: been accepted yet — while already owning every school the upload attributed
#: to them. Filtering those lists on `is_active` therefore hid real staff
#: behind real portfolios: one CCEO with 512 schools was absent from the CCEO
#: lists, so no Program Lead could be given her team and none of her schools
#: entered a PL's planning scope.
#:
#: Suspended and disabled are deliberate removals and stay excluded, as does
#: any soft-deleted profile. Use `on_staff()` for "who holds work"; keep
#: `is_active` for "who may sign in".
ON_STAFF_STATUSES = ("active", "pending_invited")


def on_staff(queryset):
    """Narrow a StaffProfile queryset to people still on the team.

    The replacement for `.filter(user__is_active=True)` wherever the question
    is portfolio, supervision, targets or assignment rather than login.
    """
    return queryset.filter(
        deleted_at__isnull=True,
        user__deleted_at__isnull=True,
        user__status__in=ON_STAFF_STATUSES,
    )


def normalize_name(name: str | None) -> str:
    """Normalize a staff name for matching: trim, collapse internal whitespace,
    lowercase. 'Ojok  Amos' / ' OJOK AMOS ' → 'ojok amos'."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def match(name: str | None) -> tuple[str | None, str]:
    """Resolve an uploaded staff name to a StaffProfile id + match status.

    Returns (staff_profile_id | None, status) where status is one of:
      • AccountOwnerStatus.MATCHED   — exactly one field-staff user matches.
      • AccountOwnerStatus.AMBIGUOUS — ≥2 field-staff users share the name.
      • AccountOwnerStatus.UNMATCHED — name present, no field-staff match.
      • AccountOwnerStatus.PENDING   — no name supplied.

    `staff_profile_id` is the CUID PK of the matched StaffProfile (or None for
    ambiguous/unmatched/pending)."""
    from .models import StaffProfile

    if not name or not name.strip():
        return None, AccountOwnerStatus.PENDING.value

    normalized = normalize_name(name)
    # Match field-staff users by normalized name. ArrayField `__contains` would
    # be ideal but cross-DB portability + the multi-role array shape makes an
    # iexact name filter + Python role check the clearer path.
    # on_staff, not is_active: a pending invite created by an earlier upload is
    # the very row this match should find. Excluding it made a re-upload fail to
    # recognise staff it had itself created, and mint a duplicate profile beside
    # the original — splitting one person's portfolio across two records.
    candidates = list(
        on_staff(StaffProfile.objects.select_related("user")).filter(
            user__name__iexact=normalized
        )
    )
    # Keep only users whose roles include a field-staff role (CCEO/PL). A
    # same-named Accountant must never be auto-linked.
    field_staff = [sp for sp in candidates if _is_field_staff(sp)]

    if len(field_staff) == 1:
        return field_staff[0].id, AccountOwnerStatus.MATCHED.value
    if len(field_staff) > 1:
        # Multiple field-staff users share the name → Admin must disambiguate.
        return None, AccountOwnerStatus.AMBIGUOUS.value
    return None, AccountOwnerStatus.UNMATCHED.value


def _is_field_staff(staff_profile) -> bool:
    """True if the linked user holds a CCEO or PL role."""
    user = getattr(staff_profile, "user", None)
    if user is None:
        return False
    roles = getattr(user, "roles", None) or []
    return any(r in OWNER_ROLES for r in roles)


__all__ = ["normalize_name", "match", "OWNER_ROLES"]
