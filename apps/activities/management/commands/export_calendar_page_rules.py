"""Write the Calendar page's rules for the Go gateway.

Go builds the Calendar (/calendar, apps.frontend.views.extended_views.
calendar_view, apps.activities.calendar_people, calendar_scope, day_off,
group_actions, apps.core.public_holidays and pages/calendar/index.html with
its partials) from the vocabularies this command writes to
platform/backend/internal/calendarpage/rules.json: who may open the page and
what each role is offered on it (Apply for Leave, tick boxes, Add other
event, the workspace strip), the activity types and status filters, the
statuses the page hides, the work a day-off mark is put on, the tab names of
the people strip, the national holiday calendar and the rule a recorded Eid
replaces the expected one by, the time zone the page's day is read in and
the query keys the app's feed never passes. A change to any of them must be
exported again; apps/activities/test_calendar_page_rules_export.py fails
until it is, so the two can never drift.

The doors and the strip are not restated: each role's answer is computed
here by the gates the page itself asks, and the strip is the workspace
template rendered for that role and read by the feed's own reader. The
national calendar is not restated either: it is the existing calendar's own
answer for every year the page can reach.

    python manage.py export_calendar_page_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/calendarpage/rules.json")

PAGE_PATH = "/calendar"
LEAVE_PATH = "/personal-time-off"
#: The national calendar is exported for these years: a month the page opens
#: (2000-2100) and the days around it a multi-day activity may run on.
HOLIDAY_YEARS = range(1998, 2103)


def strip(user):
    """The workspace strip the page shows ``user``, as the feed reads it (a
    linkTabs block), or None when there is none."""
    from django.template.loader import render_to_string

    from apps.core.navigation import build_workspace
    from apps.mobile_feed import page_blocks

    html = render_to_string(
        "partials/_section_nav.html", {"workspace": build_workspace(user, PAGE_PATH)}
    )
    blocks = page_blocks.read(html)["blocks"]
    return blocks[0]["linkTabs"] if blocks else None


def roles() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.extended_views import _CALENDAR_EVENT_ROLES

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("calendar") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "calendar")
            and bool(can_open_url(user, PAGE_PATH)),
            # The header's Apply for Leave (request.user|can_open).
            "leave": bool(can_open_url(user, LEAVE_PATH)),
            # group_actions.tickable_ids asks can_view_page("my_plan") first.
            "my_plan": RolePermissionService.can_view_page(user, "my_plan"),
            "add_event": role.value in _CALENDAR_EVENT_ROLES,
            "strip": strip(user),
        }
    return out


def holidays() -> dict:
    """The national calendar for each year, and what a recorded day changes."""
    from apps.core import public_holidays as ph

    national = {
        str(year): [
            [day.date.isoformat(), day.name, day.kind, day.expected]
            for day in ph.national_holidays(year)
        ]
        for year in HOLIDAY_YEARS
    }
    return {
        "national_country": ph.NATIONAL_COUNTRY,
        "public": ph.PUBLIC,
        "national": national,
        "eid_al_fitr": ph.EID_AL_FITR,
        "eid_al_adha": ph.EID_AL_ADHA,
        "fitr_spellings": list(ph._FITR_SPELLINGS),
        "adha_spellings": list(ph._ADHA_SPELLINGS),
        "eid_reach_days": ph._EID_REACH,
        "recorded_block_type": "PUBLIC_HOLIDAY",
    }


def rules() -> dict:
    from django.conf import settings

    from apps.activities import calendar_people, day_off, group_actions
    from apps.activities.completion_columns import OFFICER_COMPLETED_STATUSES
    from apps.core.enums import ActivityType
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import extended_views as ev
    from apps.mobile_feed.views import NOT_PASSED
    from apps.my_plan.management.commands.export_my_plan_rules import api_formats
    from apps.planning import monitor_roster
    from apps.planning.country_oversight import rules as planning_rules

    return {
        "roles": roles(),
        "time_zone": settings.TIME_ZONE,
        "years": list(ev._CALENDAR_YEARS),
        "activity_types": [
            [value, str(label)] for value, label in ActivityType.choices
        ],
        "status_families": {
            k: list(v) for k, v in ev._CALENDAR_STATUS_FAMILIES.items()
        },
        "status_options": [list(option) for option in ev._CALENDAR_STATUS_OPTIONS],
        "hidden_statuses": list(ev._CALENDAR_HIDDEN_STATUSES),
        "officer_completed_statuses": sorted(OFFICER_COMPLETED_STATUSES),
        "event_kinds": sorted(ev._CALENDAR_EVENT_KINDS),
        "weekday_labels": list(ev._CALENDAR_WEEKDAY_LABELS),
        "awaiting_delivery": list(day_off.AWAITING_DELIVERY),
        "untickable": sorted(
            group_actions._FINISHED_STATUSES | group_actions._CALLED_OFF_STATUSES
        ),
        "programme_event_type": ActivityType.PROGRAMME_EVENT.value,
        "admin_role": EdifyRole.ADMIN.value,
        "lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "director_role": EdifyRole.COUNTRY_DIRECTOR.value,
        "coordinator_role": EdifyRole.PROJECT_COORDINATOR.value,
        "partner_roles": [
            EdifyRole.PARTNER_ADMIN.value,
            EdifyRole.PARTNER_FIELD_OFFICER.value,
        ],
        "own_label": calendar_people.OWN_LABEL,
        "no_lead_key": monitor_roster.NO_LEAD_KEY,
        "no_lead_label": monitor_roster.NO_LEAD_LABEL,
        "planning_lead_role": planning_rules.PROGRAM_LEAD_ROLE,
        "planning_cceo_role": planning_rules.CCEO_ROLE,
        "allow_cd_operational_planning": bool(
            getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False)
        ),
        "partner_role_bridge": bool(getattr(settings, "PARTNER_ROLE_BRIDGE", False)),
        "holidays": holidays(),
        "not_passed_query_keys": sorted(NOT_PASSED),
        "api_formats": api_formats(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Calendar page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
