"""Write the Measurement Framework page's rules for the Go gateway.

Go builds the Measurement Framework (/ia/framework/,
apps.frontend.views.ia_framework_views.framework_page over
apps.impact.framework) from what this command writes to
platform/backend/internal/iaframework/rules.json: who may open the page, the
IA workspace strip each draws, who may author framework definitions; the
tabs; the definition, rule, direction, level and source labels; the
machine authors whose unpublished rules are reference defaults; the rule
status filters; the loan-purpose indicator key prefix; the proposed outcome
areas' codes; the intervention labels and abbreviations; and the register's
page size. A change to any of them must be exported again;
apps/impact/test_ia_framework_rules_export.py fails until it is.

    python manage.py export_ia_framework_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/iaframework/rules.json")

PAGE_PATH = "/ia/framework/"
PAGE_PERMISSION = "ia_framework"


def rules() -> dict:
    from apps.activity_catalogue.intervention_mapping import (
        PENDING_STATUSES,
        REFERENCE_DEFAULT_LABEL,
    )
    from apps.activity_catalogue.models import (
        MACHINE_AUTHORS,
        ExpectedDirection,
        MappingStatus,
    )
    from apps.core.enums import SsaIntervention
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.ia_framework_views import TABS
    from apps.impact import framework as fw
    from apps.impact.models import DefinitionStatus, IndicatorLevel, IndicatorSource

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PAGE_PATH)
        )
        roles[role.value] = {
            "page": page,
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html")
            if page
            else None,
            "author": fw.may_author(user),
        }
    return {
        "roles": roles,
        "tabs": [[key, str(label)] for key, label in TABS],
        "definition_statuses": [
            [v, str(label)] for v, label in DefinitionStatus.choices
        ],
        "pending_definition_statuses": [str(s) for s in fw.PENDING],
        "mapping_statuses": {k: str(v) for k, v in MappingStatus.choices},
        "pending_mapping_statuses": [str(s) for s in PENDING_STATUSES],
        "directions": {k: str(v) for k, v in ExpectedDirection.choices},
        "levels": {k: str(v) for k, v in IndicatorLevel.choices},
        "sources": {k: str(v) for k, v in IndicatorSource.choices},
        "machine_authors": [str(a) for a in MACHINE_AUTHORS],
        "reference_default_label": REFERENCE_DEFAULT_LABEL,
        "rule_status_filters": [[k, str(v)] for k, v in fw.RULE_STATUS_FILTERS],
        "loan_purpose_key_prefix": fw.LOAN_PURPOSE_KEY_PREFIX,
        "proposed_area_codes": [p["code"] for p in fw.PROPOSED_OUTCOME_AREAS],
        "intervention_labels": {k: str(v) for k, v in SsaIntervention.choices},
        "intervention_abbreviations": {
            str(k): v for k, v in INTERVENTION_ABBREVIATIONS.items()
        },
        "ia_role": fw.IA,
        "cd_role": fw.CD,
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Measurement Framework page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
