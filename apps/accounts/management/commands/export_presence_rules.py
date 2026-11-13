"""Write the presence stamp's rules for the Go gateway.

Every request a signed-in person makes through the existing application is
stamped by ``SlidingSessionMiddleware`` (apps.core.middleware) with
``apps.accounts.presence.touch_presence``: when they were last seen, the page
and the action, the sitting's start, and the time since the beat before it,
credited to that beat's part of the platform and task (presence_time) and to
its sign-in (login_event). A request the Go gateway answers itself never
reaches that middleware, so Go stamps the same beat (docs/migration/65).

Go embeds platform/backend/internal/presence/rules.json, which this command
writes: which requests say nothing about a person working, the read methods,
the verbs an action path is read by, the id segments a record page has, the
online window, the idle and final-beat credits, the column lengths the
values are cut to, and the time zone a credited day is read in. The parts of
the platform a page belongs to are the Staff Activity Log's
(internal/staffactivity/rules.json, the same presence_labels functions).
apps/accounts/test_presence_rules_export.py fails until a change here is
exported again, so the two can never drift.

    python manage.py export_presence_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/presence/rules.json")

#: Requests read by request_footprint: (method, path, htmx, HX-Current-URL).
#: Their readings are exported beside them, so Go is held to the page and
#: action the middleware writes.
FOOTPRINT_SAMPLES = (
    ("GET", "/clusters/", False, ""),
    ("POST", "/today/snooze", True, ""),
    ("POST", "/today/unsnooze", True, "http://localhost/dashboard?today_section=own"),
    ("GET", "/today/panel", True, "https://edify.example/my-plan/#top"),
    ("GET", "/today/panel", True, ""),
    ("HEAD", "/planning/", False, ""),
    ("OPTIONS", "/planning/", True, "/calendar/"),
    ("DELETE", "/messages/abc", False, ""),
    ("GET", "/api/mobile/v1/page", False, ""),
    ("POST", "/api/mobile/v1/drawer", False, ""),
    ("GET", "/static/app.js", False, ""),
    ("GET", "/schools/report.pdf", False, ""),
    ("POST", "/staff-activity/beat", True, "/dashboard"),
    ("GET", "", False, ""),
    ("POST", "/" + "x" * 300, True, ""),
)

#: Beats read by presence_labels.describe: (page, action).
DESCRIBE_SAMPLES = (
    ("/dashboard", ""),
    ("/", ""),
    ("/today/snooze", "POST /today/snooze"),
    ("/today/unsnooze", "POST /today/unsnooze"),
    ("/dashboard", "GET /today/panel"),
    ("/home", "GET /home/queue"),
    ("/my-plan/", ""),
    ("/clusters/cmwf2o25u0029zxghjecr", ""),
    ("/schools/123/profile", ""),
    ("/schools/SV-12", ""),
    ("/planning/schedule-modal", "GET /planning/schedule-modal?school_id=1"),
    ("/calendar/", "POST /calendar/reschedule"),
    ("/staff-activity/people/abc", "GET /staff-activity/people/abc/follow-up"),
    ("/unknown-place/sub_page", ""),
    ("/activities", "POST /activities/x/complete"),
    ("/settings", "POST"),
    ("/partner-oversight/", "POST /partner-oversight/assign-partner"),
    ("/categories/one", ""),
)


def rules() -> dict:
    from apps.accounts import presence, presence_labels
    from apps.accounts.models import PresenceTime, User
    from apps.core.middleware import SlidingSessionMiddleware

    def length(model, field: str) -> int:
        return model._meta.get_field(field).max_length

    return {
        "untracked_prefixes": list(presence._UNTRACKED_PREFIXES),
        "read_methods": list(presence._READ_METHODS),
        "action_patterns": [list(pair) for pair in presence_labels.ACTION_PATTERNS],
        "id_segment": presence_labels._ID_SEGMENT.pattern,
        "online_window_seconds": int(presence.ONLINE_WINDOW.total_seconds()),
        "idle_seconds": presence.activity_setting("IDLE_SECONDS"),
        "final_beat_seconds": presence.FINAL_BEAT_SECONDS,
        "action_interval_seconds": SlidingSessionMiddleware.ACTION_INTERVAL,
        "background_header": "X-Edify-Background",
        "lengths": {
            "page": length(User, "last_seen_path"),
            "action": length(User, "last_seen_action"),
            "login_id": length(User, "last_seen_login_id"),
            "section": length(PresenceTime, "section"),
            "working_on": length(PresenceTime, "working_on"),
        },
        "time_zone": settings.TIME_ZONE,
        "footprint_samples": [
            {
                "method": method,
                "path": path,
                "htmx": htmx,
                "current_url": current,
                "footprint": presence.request_footprint(
                    _Sample(method, path, htmx, current)
                ),
            }
            for method, path, htmx, current in FOOTPRINT_SAMPLES
        ],
        "describe_samples": [
            {"page": page, "action": action, **presence_labels.describe(page, action)}
            for page, action in DESCRIBE_SAMPLES
        ],
    }


class _Sample:
    """A request as request_footprint reads it: its path, method and htmx
    headers."""

    def __init__(self, method: str, path: str, htmx: bool, current: str) -> None:
        self.method = method
        self.path = path
        self.headers = {"HX-Request": "true"} if htmx else {}
        if current:
            self.headers["HX-Current-URL"] = current


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the presence stamp's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
