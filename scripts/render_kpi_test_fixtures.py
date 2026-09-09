"""Render populated samples from platform templates without database writes."""

import json
import os
import sys
import re
from pathlib import Path

import django
from django.template import Context, Template

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

ROOT = Path(__file__).resolve().parents[1]
if "--login-page" in sys.argv:
    from django.template.loader import render_to_string

    print(
        render_to_string(
            "pages/auth/login.html",
            dict(
                stat_schools_reached=2048,
                stat_schools_visited=1536,
                stat_schools_trained=1024,
                stat_ssa_completed=1800,
                stat_portfolio=2400,
            ),
        )
    )
    sys.exit(0)

CASES = [
    (
        "school-import",
        "pages/schools/import_result.html",
        0,
        dict(stats=dict(created=124, updated=36, clean=148, blocked=12)),
    ),
    (
        "hr-today",
        "pages/hr/hr_today.html",
        0,
        dict(
            cards=[
                dict(key=k, label=label, count=n, helper=h)
                for k, label, n, h in [
                    ("approvals", "Approvals", 7, "Awaiting HR review"),
                    ("overdue", "Overdue actions", 12, "Requires follow-up"),
                    ("onboarding", "Onboarding", 4, "Joining this month"),
                    ("leave", "Leave requests", 8, "Pending decisions"),
                ]
            ]
        ),
    ),
    (
        "closure-impact",
        "partials/analytics/closure_impact_workspace.html",
        0,
        dict(
            summary=dict(
                schools_lost=23,
                reopened=2,
                learners_lost=12048,
                schools_counted=20,
                schools_without_enrollment=3,
                districts_affected=6,
                average_school_size=524,
                budget_released=120000000,
            )
        ),
    ),
    (
        "finance-sources",
        "partials/finance/country_budget/root.html",
        -1,
        dict(
            bottom_stats=[
                dict(
                    label=label,
                    value=v,
                    sub="Current financial year",
                    helper="Plan-backed and reviewed by the country team",
                )
                for label, v in [
                    ("Approved", "UGX 1,250,000,000"),
                    ("Committed", "UGX 820,000,000"),
                    ("Disbursed", "UGX 620,000,000"),
                    ("Accounted", "UGX 590,000,000"),
                    ("Returned", "UGX 30,000,000"),
                    ("Remaining", "UGX 430,000,000"),
                ]
            ]
        ),
    ),
    (
        "special-projects",
        "pages/dashboards/special_projects.html",
        0,
        dict(
            active_project_count=14,
            activities_in_plan=128,
            evidence_pending=9,
            action_count=6,
        ),
    ),
    (
        "upload-filters",
        "pages/schools/upload_preview.html",
        0,
        dict(
            tab="review",
            stats=dict(ready=250, update=38, review=17, duplicate=5, blocked=3),
        ),
    ),
    (
        "sign-in",
        "layouts/login.html",
        0,
        dict(
            stat_schools_reached=2048,
            stat_schools_visited=1536,
            stat_schools_trained=1024,
            stat_ssa_completed=1800,
            stat_portfolio=2400,
        ),
    ),
    (
        "partner-today",
        "pages/partner/today.html",
        0,
        dict(
            today_activities=[1, 2, 3],
            upcoming=[1, 2, 3, 4, 5],
            mou_tracker=True,
            mou_awaiting_invoice=2,
        ),
    ),
]
fixtures = {}
for name, template, index, context in CASES:
    source = (ROOT / "templates" / template).read_text()
    blocks = re.findall(r"{% kpi_strip %}.*?{% endkpi_strip %}", source, re.S)
    load = "{% load kpi_metrics frontend_filters %}"
    fixtures[name] = Template(load + blocks[index]).render(Context(context))
print(json.dumps(fixtures))
