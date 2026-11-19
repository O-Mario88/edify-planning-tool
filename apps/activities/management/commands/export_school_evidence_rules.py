"""Export the School Evidence page's rules for the Go gateway.

Go builds /ia/school-evidence/ (internal/schoolevidence) from these: which
roles open it, who records evidence, each role's section strip, the tabs,
the verification states with their tones, the assessment types, the fewest
learners a comparison side may have, the learning rule's words and the label
each figure is drawn with. apps/activities/test_school_evidence_rules_export.py
fails when the file and this application differ.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/schoolevidence/rules.json")
PAGE = "/ia/school-evidence/"
METRIC_SOURCE = "apps.frontend.views.ia_school_evidence_views:_metric"
#: The page's figures, as the view writes them.
METRICS = (
    "School Evidence Awaiting Verification",
    "Schools With Confirmed Learning Results",
    "Schools With Confirmed Discipleship Records",
    "Schools With Confirmed EdTech Deployments",
    "School Evidence Returned for Correction",
)


def rules() -> dict:
    from apps.core.metrics.reconciled_registry import (
        key_for_source_label,
        source_label_for_key,
    )
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.ia_school_evidence_views import TABS
    from apps.impact import evidence_services as ev
    from apps.impact.models import LearningAssessmentType

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, "ia_school_evidence") and bool(
            can_open_url(user, PAGE)
        )
        roles[role.value] = {
            "page": page,
            "record": ev.may_record(user),
            "strip": strip(user, PAGE, "partials/_section_nav.html") if page else None,
        }
    return {
        "roles": roles,
        "tabs": [[key, str(label)] for key, label in TABS],
        "statuses": [[k, str(v)] for k, v in ev.STATUS_LABELS.items()],
        "status_tones": dict(ev.STATUS_TONES),
        "assessment_types": [[k, str(v)] for k, v in LearningAssessmentType.choices],
        "min_learners": ev.MIN_LEARNERS,
        "learning_rule_label": ev.LEARNING_RULE_LABEL,
        "metric_labels": {
            label: source_label_for_key(key_for_source_label(METRIC_SOURCE, label))
            for label in METRICS
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the School Evidence page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
