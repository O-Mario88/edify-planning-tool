"""Priorities is one page with tabs, not three sidebar links.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"I dont see it in the priority page… I was also thinking they should be one
page separated by tabs just like the way you did the map and operation. The
idea is to reduce to many menu links."

Three surfaces answered the same question from three sidebar entries:

  Priority Setting          /strategic-priorities   the priority groups and
                                                    their milestones, as
                                                    sourced — the level the
                                                    owner went looking for
  Priorities                /target-distribution    the Uganda master and its
                            /priorities             distribution to Program
                                                    Leads and CCEOs
  Team Target Distribution  /target-distribution/team  a Program Lead's own
                                                    distribution among their
                                                    supervised CCEOs

A Country Director had the first two, filed in two different sidebar groups —
and the second one under MY PERFORMANCE, which is not what it is. An Impact
Assessment officer had only Priorities, so on a country with no master yet it
opened empty and showed none of the 68 milestones that did exist. The
priorities were in the product the whole time, one menu entry away from the
menu entry named after them.

HOW THIS JOINS THEM

The same rail the dashboards use for Map | Operations. Each tab is a real URL
— the two pages keep their own routes, their own permissions and their own
tests — so a deep link, the back button and a press all land in the same
place, and a press only ever builds the context of the view it is opening.
Nothing here merges the two views into one query.

WHO SEES THE RAIL

Only a reader who may open more than one view: the rail is built from the
views that role actually has, and a role left with one gets the page it always
had, with no chrome around it. A CCEO reads the master and nothing else, so a
CCEO sees no tabs.
"""

from __future__ import annotations

from urllib.parse import urlencode

from apps.core.rbac import EdifyRole

# The strategy authors, plus the roles the owner added on 2026-09-07: Impact
# Assessment runs the distribution and needs the source beside it, and a
# Program Lead reads the priorities their own allocation comes from. Both are
# READ access — every action on the setting page is gated on its own
# permission (define, approve, allocate), which neither role gains here.
PRIORITY_SETTING_VIEWERS = (
    EdifyRole.REGIONAL_VICE_PRESIDENT.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.HUMAN_RESOURCES.value,
    EdifyRole.ADMIN.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
)

# Where "the master" lives for a role. IA, CD and Admin run the distribution,
# so their Priorities entry has always gone straight to the workspace; every
# other role reads the canonical table.
_MASTER_URL = {
    EdifyRole.IMPACT_ASSESSMENT.value: "/target-distribution",
    EdifyRole.COUNTRY_DIRECTOR.value: "/target-distribution",
    EdifyRole.ADMIN.value: "/target-distribution",
}

# §13's workspace — a Program Lead's own distribution among the CCEOs they
# supervise — was a third sidebar entry pointing at a third priority surface.
# It is the same page's third tab, for the two roles that can open it.
TEAM_DISTRIBUTION_ROLES = (
    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
    EdifyRole.ADMIN.value,
)

PANEL_ID = "priority-workspace-view"
SHELL_ID = f"{PANEL_ID}-shell"


def may_see_priority_setting(user) -> bool:
    return getattr(user, "active_role", "") in PRIORITY_SETTING_VIEWERS


def may_see_team_distribution(user) -> bool:
    return getattr(user, "active_role", "") in TEAM_DISTRIBUTION_ROLES


def master_url_for(user) -> str:
    return _MASTER_URL.get(getattr(user, "active_role", ""), "/priorities/master")


def priority_workspace_tabs(request, *, active: str, view_template: str) -> dict | None:
    """The rail for the Priorities page, or None when the reader has one view.

    `active` names the view being rendered: "setting", "distribution" or
    "team". The financial year travels with the press — every view here is
    read a year at a time, and a tab that dropped it would send a reader
    looking at FY2027 back to the operational year.
    """

    fy = (request.GET.get("fy") or "").strip()
    carried = [("fy", fy)] if fy else []

    def url(path: str) -> str:
        query = urlencode(carried)
        return f"{path}?{query}" if query else path

    tabs = []
    if may_see_priority_setting(request.user):
        tabs.append(
            {
                "key": "setting",
                "label": "Priority Setting",
                "description": "The priority groups and their milestones, as sourced",
                "url": url("/strategic-priorities"),
                "active": active == "setting",
            }
        )
    tabs.append(
        {
            "key": "distribution",
            "label": "Target Distribution",
            "description": "The Uganda master and its distribution to Program Leads and CCEOs",
            "url": url(master_url_for(request.user)),
            "active": active == "distribution",
        }
    )
    if may_see_team_distribution(request.user):
        tabs.append(
            {
                "key": "team",
                "label": "My Team",
                "description": "This Program Lead's own distribution among the CCEOs they supervise",
                "url": url("/target-distribution/team"),
                "active": active == "team",
            }
        )
    # One tab is not a tab bar.
    if len(tabs) < 2:
        return None
    return {
        "panel_id": PANEL_ID,
        "view_template": view_template,
        "active": active,
        "tabs": tabs,
    }


def wants_panel_only(request) -> bool:
    """True when this request is a tab press: htmx asking for the rail and the
    panel, to swap into the shell already on the page."""

    return request.headers.get("HX-Target") == SHELL_ID
