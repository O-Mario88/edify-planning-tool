"""Who may review an Impact Assessment judgement (owner, 2026-09-13).

There is one ImpactAssessment role, so seniority cannot decide it. A
measurement rule, an indicator or outcome definition, a finding, an impact
report or a piece of school evidence is reviewed by a SECOND Impact
Assessment officer in the same country — never the person who wrote it. A
country with a single IA officer has nobody to be that second reader, so its
Country Director acknowledges instead: an acknowledgement, not authorship (the
CD still cannot author mappings). This mirrors the no-self-verification rule
for field work (apps.core.permissions.verifies_own_work).
"""

from __future__ import annotations

from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole

PEER_IA = "peer_ia"
CD_FALLBACK = "cd_fallback"


def _profile_country(user) -> str:
    profile = getattr(user, "staff_profile", None)
    return (getattr(profile, "country", "") or "").strip()


def ia_officer_ids(country: str) -> list[str]:
    """User ids of active Impact Assessment officers in `country`."""

    from apps.accounts.models import User

    if not country:
        return []
    return list(
        User.objects.filter(
            roles__contains=[EdifyRole.IMPACT_ASSESSMENT.value],
            is_active=True,
            deleted_at__isnull=True,
            staff_profile__country=country,
            staff_profile__deleted_at__isnull=True,
        ).values_list("id", flat=True)
    )


def reviewer_basis(principal, *, author_id: str, country: str) -> str | None:
    """How `principal` may review a record `author_id` wrote in `country`:
    PEER_IA, CD_FALLBACK, or None when they may not review it at all."""

    user_id = str(getattr(principal, "id", "") or "")
    if not user_id or user_id == str(author_id or ""):
        return None
    role = getattr(principal, "active_role", "")
    country = (country or "").strip()
    if country and _profile_country(principal) != country:
        return None
    if role == EdifyRole.IMPACT_ASSESSMENT.value:
        return PEER_IA
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        others = [i for i in ia_officer_ids(country) if str(i) != str(author_id)]
        return CD_FALLBACK if not others else None
    return None


def assert_can_review(principal, *, author_id: str, country: str) -> str:
    basis = reviewer_basis(principal, author_id=author_id, country=country)
    if basis:
        return basis
    if str(getattr(principal, "id", "")) == str(author_id or ""):
        raise Forbidden("You wrote this, so a second reviewer has to review it.")
    if getattr(principal, "active_role", "") == EdifyRole.COUNTRY_DIRECTOR.value:
        raise Forbidden(
            "Another Impact Assessment officer in this country reviews it; the "
            "Country Director acknowledges only where there is no second officer."
        )
    raise Forbidden(
        "Only a second Impact Assessment officer in this country may review it."
    )
