"""Write the Staff Activity Log's rules for the Go gateway.

Go builds the Staff Activity Log (/staff-activity,
apps.frontend.views.staff_activity_views.staff_activity_view and
apps.staff_activity.services.activity_log) from the vocabularies this command
writes to platform/backend/internal/staffactivity/rules.json: who may open the
page, which readers it sends to their dashboard, the roles it lists, the
meaningful actions it counts, its statuses, thresholds and labels, the parts
of the platform a page belongs to, and two renderings of its summary strip.
A change to any of them must be exported again;
apps/staff_activity/test_staff_activity_rules_export.py fails until it is, so
the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks.

    python manage.py export_staff_activity_rules
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/staffactivity/rules.json")
#: A person's detail address as the feed's gate is asked it.
PERSON_PATH_SAMPLE = "/staff-activity/people/sample"

#: Two summary strips the page can show: everything zero and nobody expected,
#: and large figures with every helper on (``_kpi_items``). The feed's reading
#: of each is exported beside the figures, so Go is held to the words, tones
#: and helper cuts the page writes.
STRIP_SAMPLES = (
    {
        "active_share": None,
        "staff_expected": 0,
        "staff_total": 0,
        "staff_active": 0,
        "no_login": 0,
        "total_active_label": "0m",
        "median_active_label": "0m",
        "meaningful_actions": 0,
        "schools": 0,
        "open_follow_ups": 0,
        "suggested": 0,
    },
    {
        "active_share": 7,
        "staff_expected": 1234,
        "staff_total": 12345,
        "staff_active": 1000,
        "no_login": 3,
        "total_active_label": "21h 05m",
        "median_active_label": "<1m",
        "meaningful_actions": 10500,
        "schools": 1,
        "open_follow_ups": 2,
        "suggested": 2,
    },
    {
        "active_share": 100,
        "staff_expected": 1,
        "staff_total": 1,
        "staff_active": 1,
        "no_login": 0,
        "total_active_label": "1h 00m",
        "median_active_label": "1h 00m",
        "meaningful_actions": 1,
        "schools": 2,
        "open_follow_ups": 0,
        "suggested": 1,
    },
)


def doors() -> dict:
    """Who may open the page, by its own gates: require_page_permission
    ("staff_activity") and the feed's can_open_url."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, "staff_activity")
            and bool(can_open_url(user, "/staff-activity")),
            # A person's detail (staff_activity_person_view), one id standing
            # for every person.
            "person": RolePermissionService.can_view_page(user, "staff_activity")
            and bool(can_open_url(user, PERSON_PATH_SAMPLE)),
        }
    return out


def strip_samples() -> list[dict]:
    """Each sample strip as the page draws it and the feed reads it."""
    from django.template.loader import render_to_string

    from apps.core.metrics.payload import render_precomputed_metric_for_source
    from apps.frontend.views.staff_activity_views import _kpi_items
    from apps.mobile_feed.views import page_body

    out = []
    for kpis in STRIP_SAMPLES:
        html = render_to_string(
            "components/context_metrics.html",
            {
                "items": _kpi_items(
                    {"kpis": kpis}, render_precomputed_metric_for_source
                ),
                "variant": "executive",
                "density": "compact",
                "title": "Staff activity at a glance",
            },
        )
        blocks = page_body(f"<main>{html}</main>", "/staff-activity")["blocks"]
        out.append({"kpis": kpis, "strip": blocks[0]["strip"]})
    return out


def rules() -> dict:
    from django.conf import settings

    from apps.accounts import presence, presence_labels
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.frontend.views import dashboard_embed
    from apps.hr.leave_services import PublicHolidayService
    from apps.mobile_feed import views as feed
    from apps.staff_activity import registry, services
    from apps.staff_activity.models import (
        OPEN_STATUSES,
        FollowUpStatus,
        FollowUpTrigger,
    )

    holidays = inspect.signature(PublicHolidayService.get_holidays_in_range)
    return {
        "doors": doors(),
        "roles": {
            "program_lead": services.PROGRAM_LEAD,
            "country_director": services.COUNTRY_DIRECTOR,
            "admin": services.ADMIN,
            "cceo": services.CCEO,
        },
        "internal_roles": list(services.INTERNAL_ROLES),
        "supervisor_roles": list(services.SUPERVISOR_ROLES),
        "leave_approved": services.LEAVE_APPROVED,
        "holiday_country": holidays.parameters["country"].default,
        "dashboard": {
            "role": dashboard_embed.PROGRAM_LEAD,
            "path": dashboard_embed.STAFF_ACTIVITY.path,
            "param": dashboard_embed.STAFF_ACTIVITY.param,
            "anchor": dashboard_embed.STAFF_ACTIVITY.anchor,
        },
        "role_filter_labels": [
            [key, label] for key, label in services.ROLE_FILTER_LABELS.items()
        ],
        "role_titles": presence.ROLE_TITLES,
        "status_options": [list(option) for option in services.STATUS_OPTIONS],
        "periods": [list(option) for option in presence.PRESENCE_PERIODS],
        "thresholds": {
            "failed_actions_suggestion": services.FAILED_ACTIONS_SUGGESTION,
            "excessive_time_factor": services.EXCESSIVE_TIME_FACTOR,
            "excessive_time_floor_seconds": services.EXCESSIVE_TIME_FLOOR_SECONDS,
            "low_engagement_min_expected_days": services.LOW_ENGAGEMENT_MIN_EXPECTED_DAYS,
            "idle_seconds": presence.activity_setting("IDLE_SECONDS"),
            "online_seconds": presence.activity_setting("ONLINE_SECONDS"),
            "final_beat_seconds": presence.FINAL_BEAT_SECONDS,
            "session_cookie_age": settings.SESSION_COOKIE_AGE,
        },
        "person": {
            "sessions_shown": services.SESSIONS_SHOWN,
            "actions_shown": services.ACTIONS_SHOWN,
            "follow_ups_shown": services.FOLLOW_UPS_SHOWN,
            "suggestion_reasons": {
                "no_login": services.NO_LOGIN_REASON,
                "low_engagement": services.LOW_ENGAGEMENT_REASON,
                "repeated_errors": services.REPEATED_ERRORS_REASON,
            },
            "follow_up_triggers": [
                [str(key), str(label)] for key, label in FollowUpTrigger.choices
            ],
            "follow_up_statuses": [
                [str(key), str(label)] for key, label in FollowUpStatus.choices
            ],
        },
        "time_zone": settings.TIME_ZONE,
        "page_size": TABLE_PAGE_SIZE,
        "meaningful_actions": {
            action: {
                "label": d.label,
                "module": d.module,
                "school": d.school,
                "secondary": d.secondary,
            }
            for action, d in registry.MEANINGFUL_ACTIONS.items()
        },
        "failed_request_actions": list(registry.FAILED_REQUEST_ACTIONS),
        "school_subjects": sorted(registry.SCHOOL_SUBJECTS),
        "activity_subjects": sorted(registry.ACTIVITY_SUBJECTS),
        "payload_school_keys": list(registry.PAYLOAD_SCHOOL_KEYS),
        "follow_up_open_statuses": [str(status) for status in OPEN_STATUSES],
        "untracked_prefixes": list(presence._UNTRACKED_PREFIXES),
        "section_registry": [list(pair) for pair in presence_labels._registry_labels()],
        "section_prefixes": [list(pair) for pair in presence_labels.SECTION_PREFIXES],
        "query": {
            "key_pattern": feed.QUERY_KEY.pattern,
            "not_passed": sorted(feed.NOT_PASSED),
            "max_value": feed.MAX_QUERY_VALUE,
        },
        "strip_samples": strip_samples(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Staff Activity Log's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
