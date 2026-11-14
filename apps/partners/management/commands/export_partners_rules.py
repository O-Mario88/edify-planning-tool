"""Write the Partner Activities workspace rules for Go.

Go builds Partner Activities (/partners: apps.frontend.views.partner_views
.partners_list_view, _partner_workspace and pages/partners/index.html) from
what this command writes to platform/backend/internal/partnerworkspace/
rules.json: who may open the page and who is sent on to Partner Oversight;
the roles that see only their own organisation; who may open a school's or a
partner's profile from it; the labels the rows and cards print (activity
types, visit purposes, SSA interventions, partner roles, the KPI tiles); the
statuses that leave the list, that count as complete and that a hand-over is
released by; and the table's page size. A change to any of them must be
exported again; apps/partners/test_partners_rules_export.py fails until it
is.

    python manage.py export_partners_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/partnerworkspace/rules.json")

#: _partner_workspace's complete_statuses: a row reads Completed.
COMPLETE_STATUSES = ["closed", "completed", "ia_verified", "payment_approved"]

#: The six tiles, in the page's order.
KPI_KEYS = [
    "partner_total_partners",
    "partner_assigned_schools",
    "partner_scheduled_activities",
    "partner_activities_yet_to_schedule",
    "partner_scheduled_activity_cost",
    "partner_high_risk_delays",
]


def rules() -> dict:
    from django.conf import settings

    from apps.activities.models import ActivityType
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NON_FUNDABLE_ACTIVITY_STATUSES,
    )
    from apps.core.enums import SsaIntervention
    from apps.core.metrics.registry import get_metric
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.partner_views import PARTNER_ROLES
    from apps.partners import capabilities
    from apps.partners.models import PartnerAssignment, PartnerRole
    from apps.partners.purposes import _LABELS

    def roles_where(test) -> list[str]:
        return sorted(role.value for role in EdifyRole if test(_role_user(role.value)))

    return {
        "page_roles": roles_where(
            lambda user: RolePermissionService.can_view_page(user, "partners")
            and can_open_url(user, "/partners")
        ),
        "oversight_roles": roles_where(
            lambda user: RolePermissionService.can_view_page(user, "partner_oversight")
        ),
        "own_organisation_roles": sorted(PARTNER_ROLES),
        "profile_link_roles": {
            "schools": roles_where(lambda user: can_open_url(user, "/schools/0")),
            "partners": roles_where(lambda user: can_open_url(user, "/partners/0")),
        },
        "activity_types": {k: str(v) for k, v in ActivityType.choices},
        "purpose_labels": {str(k): str(v) for k, v in _LABELS.items()},
        "interventions": {k: str(v) for k, v in SsaIntervention.choices},
        "capability_groups": {
            capabilities.ANY_INTERVENTION_KEY: "Any SSA intervention",
            capabilities.UNMAPPED_KEY: "Not mapped to an intervention",
            capabilities.LOAN_KEY: capabilities.LOAN_LABEL,
        },
        "partner_roles": {k: str(v) for k, v in PartnerRole.choices},
        "kpi_labels": {key: str(get_metric(key).label) for key in KPI_KEYS},
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "complete_statuses": COMPLETE_STATUSES,
        "released_statuses": list(PartnerAssignment.RELEASED_STATUSES),
        "partner_role_bridge": bool(getattr(settings, "PARTNER_ROLE_BRIDGE", False)),
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Partner Activities workspace rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
