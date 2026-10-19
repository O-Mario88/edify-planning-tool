"""The Analytics entry, retired: each old link opens its closest page.

Owner, 2026-10-19: "Remove the whole Analytics entry now. Send every
section's old link to the closest profile or oversight page, and give only
Reports, Decision Log and Closure Quality their own sidebar entries." The
sections had become copies of what the profiles and the oversight pages read
(the owner's "Since Analytics are integrated inside profiles and oversigths,
do we need analytic page?"), so a bookmark lands where that reading now is,
for whoever follows it:

* a country reader (the Country Profile's readers) on the Country Profile;
* a Programme Lead on their own profile, which is their team's;
* a CCEO on Cluster Oversight, their own clusters analysed;
* the Project Coordinator on Project Analytics; anyone else on the Dashboard.

People and Verification Quality were the HR and Impact Assessment pages shown
as tabs; their addresses open those pages.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.shortcuts import redirect

from apps.core.permissions import RolePermissionService, require_page_permission
from apps.core.rbac import EdifyRole


def _profile(user, **query) -> str | None:
    """The reader's own profile page, with ``query``; None when they have
    none to read (a CCEO, HR, the Accountant)."""
    suffix = f"?{urlencode(query)}" if query else ""
    if RolePermissionService.can_view_page(user, "country_planning_oversight"):
        return f"/country-profile{suffix}"
    if getattr(user, "active_role", "") == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return f"/staff/{user.id}{suffix}"
    return None


def _fallback(user) -> str:
    role = getattr(user, "active_role", "")
    if role == EdifyRole.CCEO.value:
        return "/cluster-oversight/"
    if role == EdifyRole.PROJECT_COORDINATOR.value:
        return "/projects/analytics"
    if role == EdifyRole.PROGRAM_ACCOUNTANT.value:
        return "/budget"
    return "/dashboard"


#: Tabs that showed another module's page inside Analytics open that page.
MODULE_PAGES = {
    "people": "/hr-analytics",
    "verification_quality": "/ia/dashboard/",
}


def destination(user, section: str) -> str:
    """Where ``section``'s old link takes ``user``."""
    if section in MODULE_PAGES:
        return MODULE_PAGES[section]
    if section == "core_school_health":
        return "/core-schools-oversight/"
    if section == "closures":
        return "/schools/closed"
    if section == "impact" and RolePermissionService.can_view_page(
        user, "cluster_oversight"
    ):
        return "/cluster-oversight/impact"
    if section == "ssa":
        return _profile(user, tab="ssa") or (
            "/cluster-oversight/ssa"
            if RolePermissionService.can_view_page(user, "cluster_oversight")
            else _fallback(user)
        )
    if section == "declining":
        return _profile(user, tab="schools", show="declined") or (
            "/cluster-oversight/ssa"
            if RolePermissionService.can_view_page(user, "cluster_oversight")
            else _fallback(user)
        )
    return _profile(user) or _fallback(user)


#: Each home's name, by the start of its address, as its own page reads.
HOME_NAMES = (
    ("/country-profile", "Country Profile"),
    ("/staff/", "My Profile"),
    ("/cluster-oversight/", "Cluster Oversight"),
    ("/core-schools-oversight/", "Core School Oversight"),
    ("/schools/closed", "Closed Schools"),
    ("/projects/analytics", "Project Analytics"),
    ("/budget", "Budget"),
    ("/hr-analytics", "HR Analytics"),
    ("/ia/dashboard/", "Impact Assessment Dashboard"),
)


def home(user, section: str = "overview") -> dict:
    """The page ``section``'s reading lives on for ``user``, and its name.

    A link that once opened an Analytics section opens this page and says
    its name, rather than an old address that redirects."""
    href = destination(user, section)
    label = next(
        (name for start, name in HOME_NAMES if href.startswith(start)), "Dashboard"
    )
    return {"href": href, "label": label}


def retired(section: str, page_key: str):
    """A view for one retired section: the old address opens its home.

    It keeps the permission its page had (``page_key``), so it answers only a
    reader that page admitted."""

    @require_page_permission(page_key)
    def view(request, *args, **kwargs):
        response = redirect(destination(request.user, section))
        if request.headers.get("HX-Request") == "true":
            response["HX-Redirect"] = response["Location"]
        return response

    view.__name__ = f"retired_{section}"
    return view
