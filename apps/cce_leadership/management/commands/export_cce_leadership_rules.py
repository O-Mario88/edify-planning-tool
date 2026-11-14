"""Write the CCE leadership registers' rules for the Go gateway.

Go builds the CCE leadership registers (apps.frontend.views.
cce_leadership_views, drawn by pages/cce_leadership/workspace.html) from what
this command writes to platform/backend/internal/ccelead/rules.json: for each
register Go answers, who may open it, the workspace strip each role is shown
and which of its drawer buttons each role may open; the label each figure is
drawn with; a monthly report's status labels and tones; the month reporting
started; an observation's rating fields and recommendation labels and an
activity type's labels; an engagement's kinds and which are shared with a
Programme Lead; the meeting rhythm's rules; how long the line under a figure may stay; the register's page
size; and the query keys the feed never passes. A change to any of them must
be exported again; apps/cce_leadership/test_cce_leadership_rules_export.py
fails until it is.

    python manage.py export_cce_leadership_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/ccelead/rules.json")

METRIC_SOURCE = "apps.frontend.views.cce_leadership_views:_metric"

PAGES = {
    "/cce-leadership/reports": {
        "permission": "cce_reports",
        "drawers": ["/cce-leadership/reports/new"],
        "metrics": [
            "Report Drafts",
            "Reports Awaiting Review",
            "Reports Returned",
            "Reports Acknowledged",
        ],
    },
    "/cce-leadership/engagements": {
        "permission": "cce_engagements",
        "drawers": [
            "/cce-leadership/engagements/new",
            "/cce-leadership/engagements/new?kind=training_observation",
        ],
        "metrics": [
            "Coaching Conversations (30 Days)",
            "Trainings Observed This Quarter",
            "Country Reviews This Quarter",
            "Engagements Overdue",
        ],
    },
    "/my-coaching": {
        "permission": "my_coaching",
        "drawers": [],
        "source": "apps.frontend.views.coaching_views:_metric",
        "metrics": [
            "Coaching Awaiting My Acknowledgement",
            "Coaching I Have Acknowledged",
            "Agreed Coaching Actions Open",
        ],
    },
    "/cce-leadership/feedback": {
        "permission": "cce_training_feedback",
        "drawers": [],
        "metrics": [
            "Feedback Awaiting Acknowledgement",
            "Feedback Acknowledged",
            "Average Observation Rating",
        ],
    },
}


def pages() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for path, page in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            roles[role.value] = {
                "page": RolePermissionService.can_view_page(user, page["permission"])
                and bool(can_open_url(user, path)),
                "strip": strip(user, path, "partials/_section_nav.html"),
                "drawers": [d for d in page["drawers"] if can_open_url(user, d)],
            }
        out[path] = {"roles": roles}
    return out


def rules() -> dict:
    from apps.cce_leadership import cadence, services
    from apps.activities.models import ActivityType
    from apps.cce_leadership.models import (
        OBSERVATION_CRITERIA,
        CoachingKind,
        EngagementKind,
        ObservationRecommendation,
        ReportStatus,
    )
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS
    from apps.core.metrics.reconciled_registry import (
        key_for_source_label,
        source_label_for_key,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.frontend.views.cce_leadership_views import STATUS_TONES
    from apps.mobile_feed.views import NOT_PASSED

    return {
        "pages": pages(),
        "metric_labels": {
            label: source_label_for_key(
                key_for_source_label(page.get("source", METRIC_SOURCE), label)
            )
            for page in PAGES.values()
            for label in page["metrics"]
        },
        "report_statuses": dict(ReportStatus.choices),
        "report_tones": {str(k): v for k, v in STATUS_TONES.items()},
        "reporting_starts": services.REPORTING_STARTS.isoformat(),
        # An observation's rating fields (averaged, the empty ones left out)
        # and its recommendation's labels; an activity type's labels.
        "rating_fields": [field for field, _label, _help in OBSERVATION_CRITERIA],
        "recommendations": dict(ObservationRecommendation.choices),
        "activity_types": dict(ActivityType.choices),
        "engagement_kinds": [[str(k), str(v)] for k, v in EngagementKind.choices],
        "shareable_kinds": [str(k) for k in services.SHAREABLE_KINDS],
        # A coaching record's kinds, as the My Coaching filter offers them.
        "coaching_kinds": [[str(k), str(v)] for k, v in CoachingKind.choices],
        # The meeting rhythm the role description sets (cadence.py).
        "cadence": {
            "rules": [
                {
                    "kind": str(r.kind),
                    "label": r.label,
                    "expectation": r.expectation,
                    "per": r.per,
                    "window": r.window,
                    "every_days": r.every_days,
                }
                for r in cadence.CADENCE_RULES
            ],
            "state_labels": cadence.STATE_LABELS,
            "state_tones": cadence.STATE_TONES,
            "state_order": cadence.STATE_ORDER,
            "due_soon_days": cadence.DUE_SOON_DAYS,
            "quarter_due_soon_days": cadence.QUARTER_DUE_SOON_DAYS,
            "annual_window_opens_month": cadence.ANNUAL_WINDOW_OPENS_MONTH,
        },
        "helper_figure_chars": HELPER_FIGURE_CHARS,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the CCE leadership registers' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
