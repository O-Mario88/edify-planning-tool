"""Where signing in lands, by role.

Home, the task-first page, for everyone (owner, 2026-10-24: "on logging in,
the new home page is loaded by default"), except the country readers, whose
start is Country Oversight (owner, 2026-10-25: "IA and Country Director, RVP
and Regional Program Lead homepage dashboard should be Country Oversight by
default"). A listed role that may not open Country Oversight lands on Home
rather than on an access-denied page.
"""

from __future__ import annotations

from apps.core.rbac import EdifyRole

HOME_URL = "/home"
COUNTRY_OVERSIGHT_URL = "/country-planning-oversight/"
COUNTRY_OVERSIGHT_PAGE = "country_planning_oversight"

#: The roles the owner named, as the role a person is signed in as.
COUNTRY_OVERSIGHT_ROLES = frozenset(
    role.value
    for role in (
        EdifyRole.IMPACT_ASSESSMENT,
        EdifyRole.COUNTRY_DIRECTOR,
        EdifyRole.REGIONAL_VICE_PRESIDENT,
        EdifyRole.REGIONAL_PROGRAM_LEAD,
    )
)


def landing_url(user) -> str:
    """The page this person opens on signing in."""
    from apps.core.permissions import RolePermissionService

    if getattr(
        user, "active_role", None
    ) in COUNTRY_OVERSIGHT_ROLES and RolePermissionService.can_view_page(
        user, COUNTRY_OVERSIGHT_PAGE
    ):
        return COUNTRY_OVERSIGHT_URL
    return HOME_URL
