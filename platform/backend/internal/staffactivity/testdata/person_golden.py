"""Golden readings of a person's detail for rows the development data lacks.

Renders partials/staff_activity/_person_detail.html with two made-up people
and reads each through the app's feed (apps.mobile_feed.views.page_body),
writing person_golden.json beside this file; person_test.go builds the same
two people in Go and compares. Run from the repository root:

    python manage.py shell < platform/backend/internal/staffactivity/testdata/person_golden.py
"""

import json
from datetime import date
from pathlib import Path

from django.template.loader import render_to_string

from apps.mobile_feed.views import page_body
from apps.staff_activity.models import StaffUsageFollowUp

HERE = Path("platform/backend/internal/staffactivity/testdata")
PERIOD = {"key": "week", "on": date(2026, 11, 11), "label": "Week of 9 Nov 2026"}


def busy():
    person = {
        "id": "gpsa-p1",
        "name": "Grace  A. Okello",
        "initials": "GO",
        "status_key": "online",
        "status_label": "Online",
        "title": "CCEO",
        "region": "Central",
        "supervisor": "Ruth Lead",
        "logins": 12,
        "active_label": "2h 05m",
        "actions": 0,
        "failed": 4,
        "schools": 0,
        "suggestions": [
            {"reason": "Signed in, but no meaningful action in the period"},
            {"reason": "4 failed actions in the period"},
        ],
    }
    follow_ups = [
        StaffUsageFollowUp(
            id="gpsa-f1",
            trigger="repeated_errors",
            status="sent",
            due_date=date(2026, 11, 3),
        ),
        StaffUsageFollowUp(
            id="gpsa-f2",
            trigger="excessive_time",
            status="returned",
            due_date=date(2026, 12, 25),
        ),
    ]
    detail = {
        "person": person,
        "period": PERIOD,
        "session_total": 12,
        "sessions": [
            {
                "at_label": "Wed 11 Nov 2026, 08:05",
                "device": "Phone",
                "active_label": "1h 00m",
                "idle_label": "<1m",
                "span_label": "1h 00m",
                "ended": "Current session",
                "current": True,
            },
            {
                "at_label": "Tue 10 Nov 2026, 17:30",
                "device": "Unknown",
                "active_label": "0m",
                "idle_label": "5m",
                "span_label": "5m",
                "ended": "Signed out 10/11 17:35",
                "current": False,
            },
        ],
        "tasks": 1,
        "modules": [
            {"label": "Planning", "time": "1h 05m", "share": 52, "actions": 1},
            {"label": "Clusters", "time": "0m", "share": 0, "actions": 2},
        ],
        "timeline_total": 3,
        "timeline": [
            {
                "at_label": "08:10",
                "label": "Scheduled a visit",
                "module": "Planning",
                "ok": True,
                "link": "/activities/gpsa-a1",
            },
            {
                "at_label": "10/11 17:31",
                "label": "Set a cluster's partner facilitator",
                "module": "Clusters",
                "ok": True,
                "link": "",
            },
        ],
        "trend": [
            {"label": day, "time": "0m", "actions": 0, "height": 0}
            for day in ("Mon", "Tue", "Wed")
        ],
        "login_days": 1,
        "follow_ups": follow_ups,
    }
    return detail, True


def quiet():
    person = {
        "id": "gpsa-p2",
        "name": "Ann",
        "initials": "A",
        "status_key": "on_leave",
        "status_label": "On approved leave",
        "title": "Programme Lead",
        "region": "",
        "supervisor": "",
        "logins": 0,
        "active_label": "0m",
        "actions": 0,
        "failed": 0,
        "schools": 0,
        "suggestions": [],
    }
    detail = {
        "person": person,
        "period": PERIOD,
        "session_total": 1,
        "sessions": [],
        "tasks": 0,
        "modules": [],
        "timeline_total": 0,
        "timeline": [],
        "trend": [],
        "login_days": 0,
        "follow_ups": [],
    }
    return detail, False


out = {}
for name, make in (("busy", busy), ("quiet", quiet)):
    detail, can_follow_up = make()
    html = render_to_string(
        "partials/staff_activity/_person_detail.html",
        {
            "detail": detail,
            "person": detail["person"],
            "can_follow_up": can_follow_up,
            "query": "",
        },
    )
    path = "/staff-activity/people/" + detail["person"]["id"]
    out[name] = page_body(html, path, None)
(HERE / "person_golden.json").write_text(
    json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("wrote", HERE / "person_golden.json")
