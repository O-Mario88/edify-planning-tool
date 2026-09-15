"""Turn a request path into the two words the Who's Online table shows.

Owner, 2026-09-15: "what they were working on" and "part of the system
accessed (could be planning, my plan, cluster, core school…)".

The section comes from the sidebar registry first (its labels are what people
see in the navigation), then from a prefix table for routes the sidebar does
not list. The activity comes from the last write or drawer request on the
page, read off the path's verbs; a plain page load reads as viewing the page.
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

# Routes the sidebar does not name, longest prefix wins.
SECTION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/planning", "Planning"),
    ("/my-plan", "My Plan"),
    ("/clusters", "Clusters"),
    ("/core-schools", "Core Schools"),
    ("/core-school-health", "Core School Health"),
    ("/schools", "Schools"),
    ("/partner-oversight", "Partner Oversight"),
    ("/partners", "Partners"),
    ("/partner", "Partner Workspace"),
    ("/dashboard", "Dashboard"),
    ("/todos", "To-Do"),
    ("/calendar", "Calendar"),
    ("/work-plan", "Work Plan"),
    ("/fund-requests", "Fund Requests"),
    ("/fund-approvals", "Fund Approvals"),
    ("/my-budget", "My Budget"),
    ("/budget", "Budget"),
    ("/analytics", "Analytics"),
    ("/ssa", "SSA"),
    ("/impact", "Impact"),
    ("/reports", "Reports"),
    ("/completed-activities", "Completed Work"),
    ("/activities", "Activities"),
    ("/evidence", "Evidence"),
    ("/ia", "Impact Assessment"),
    ("/team-planning-oversight", "Team Oversight"),
    ("/priorities", "Priorities"),
    ("/targets", "Targets"),
    ("/messages", "Messages"),
    ("/notifications", "Notifications"),
    ("/hr", "HR"),
    ("/leave", "Leave"),
    ("/users", "Users"),
    ("/admin-ops", "Platform Operations"),
    ("/system-health", "System Health"),
    ("/projects", "Projects"),
    ("/search", "Search"),
    ("/debriefs", "Field Debrief"),
    ("/help", "Help Center"),
    ("/profile", "Profile"),
    ("/settings", "Settings"),
    ("/professional-development", "Professional Development"),
    ("/business-transformation", "Business Transformation"),
    ("/mfi-portal", "MFI Portal"),
    ("/login", "Sign-in"),
    ("/", "Dashboard"),
)

# Verbs in an action path, first match wins. The path is the write or drawer
# request the person last made on the page.
ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"reschedul", "Rescheduling an activity"),
    (r"schedul", "Scheduling an activity"),
    (r"assign-partner|assign_partner|partner-modal", "Assigning a school to a partner"),
    (r"add-to-cluster|bulk-assign|assign-cluster", "Adding schools to a cluster"),
    (r"return", "Returning an assignment"),
    (r"cancel", "Cancelling an activity"),
    (r"complet", "Completing an activity"),
    (r"evidence", "Working on evidence"),
    (r"verif", "Verifying work"),
    (r"approv|decline|reject", "Reviewing an approval"),
    (r"onboard", "Onboarding a school"),
    (r"upload|import", "Uploading data"),
    (r"export|download", "Exporting data"),
    (r"fund|budget|request", "Working on a fund request"),
    (r"debrief", "Writing a field debrief"),
    (r"message", "Messaging"),
    (r"search", "Searching"),
    (r"password|profile|settings|mfa", "Updating their account"),
    (r"login|logout", "Signing in"),
    (r"delete|remove|close", "Removing a record"),
    (r"create|new|add", "Creating a record"),
    (r"edit|update|save|drawer|form", "Editing a record"),
)

_ID_SEGMENT = re.compile(r"^(?:[a-z0-9]{20,}|\d+|[A-Za-z]{1,4}-\d+)$")


def page_path(value: str) -> str:
    """The path part of a URL or path, with no query string."""
    if not value:
        return ""
    return urlsplit(value).path or "/"


@lru_cache(maxsize=1)
def _registry_labels() -> list[tuple[str, str]]:
    """Exact url → label from the navigation registry, longest first."""
    try:
        from apps.core import navigation
    except Exception:  # pragma: no cover - the registry is always importable
        return []
    found: dict[str, str] = {}

    def take(item):
        label = item.get("label")
        if not label:
            return
        for url in [item.get("url"), *(item.get("role_urls") or {}).values()]:
            if url and url.startswith("/"):
                found.setdefault(url.rstrip("/") or "/", label)
        for section in item.get("sections") or []:
            take(section)

    for group in getattr(navigation, "SIDEBAR_ITEMS", []):
        for item in group.get("items", []):
            take(item)
    for name in dir(navigation):
        if name.endswith("_SECTIONS") and isinstance(getattr(navigation, name), list):
            for item in getattr(navigation, name):
                if isinstance(item, dict):
                    take(item)
    return sorted(found.items(), key=lambda kv: -len(kv[0]))


def section_for(path: str) -> str:
    """The part of the system a path belongs to."""
    path = page_path(path).rstrip("/") or "/"
    for url, label in _registry_labels():
        if path == url or path.startswith(url + "/"):
            return label
    for prefix, label in SECTION_PREFIXES:
        if prefix == "/":
            continue
        if path == prefix or path.startswith(prefix + "/"):
            return label
    if path == "/":
        return "Dashboard"
    head = path.split("/")[1]
    return head.replace("-", " ").replace("_", " ").title() or "Dashboard"


def _singular(section: str) -> str:
    if section.endswith("ies"):
        return section[:-3] + "y"
    if section.endswith("s") and not section.endswith("ss"):
        return section[:-1]
    return section


def activity_for(path: str, action: str = "") -> str:
    """What the person was doing: the verb of their last action on the page,
    or a reading of the page itself."""
    action_path = page_path(action.split(" ", 1)[-1]) if action else ""
    if action_path:
        lowered = action_path.lower()
        for pattern, label in ACTION_PATTERNS:
            if re.search(pattern, lowered):
                return label
    section = section_for(path)
    segments = [seg for seg in page_path(path).split("/") if seg]
    if any(_ID_SEGMENT.match(seg) for seg in segments[1:]):
        return f"Viewing a {_singular(section).lower()} record"
    if len(segments) > 1:
        tail = segments[-1].replace("-", " ").replace("_", " ")
        return f"Viewing {section} · {tail}"
    return f"Viewing {section}"


def describe(path: str, action: str = "") -> dict:
    return {"section": section_for(path), "working_on": activity_for(path, action)}
