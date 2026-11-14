"""Write the Business Transformation pages' rules for the Go gateway.

Go builds the Business Transformation pages (apps.business_transformation
.frontend_views over apps.business_transformation.services and its lending
ledger) from what this command writes to
platform/backend/internal/btportfolio/rules.json: who may open each page and
which BT permissions each role holds; which roles read the whole Uganda
portfolio, only summaries, or one lending partner's books; the role the
workspace tabs are drawn for and who reads districts as links; the words for each case, recommendation, loan,
Salesforce, IA and impact status; and the registry labels of the portfolio
figures. A change to any of them must be exported again;
apps/business_transformation/test_bt_rules_export.py fails until it is.

    python manage.py export_bt_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/btportfolio/rules.json")

#: Each page Go answers, with the page permission its view requires.
PAGES = {
    "/business-transformation/overview": "business_transformation",
    "/business-transformation/business-accounting-finance": (
        "business_transformation_finance"
    ),
    "/business-transformation/government-requirements": (
        "business_transformation_government"
    ),
    "/business-transformation/impact-reports": "business_transformation_reports",
    "/loans": "loans",
    "/mfi-portal": "mfi_portal",
}

#: The portfolio figures the pages draw, by registry key.
METRIC_KEYS = [
    "bt_value_disbursed",
    "bt_schools_financed",
    "bt_active_portfolio",
    "bt_par30",
    "bt_collection_rate",
    "bt_use_verified",
]

#: The role workspace_nav.html draws the BT-only tabs for.
NAV_ROLE = "BusinessTransformationOfficer"


def rules() -> dict:
    from apps.business_transformation import models as m
    from apps.business_transformation import services
    from apps.core.metrics.registry import get_metric
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission

    bt_permissions = sorted(
        p.value for p in Permission if p.value.startswith("businessTransformation.")
    )
    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "pages": sorted(
                path
                for path, permission in PAGES.items()
                if RolePermissionService.can_view_page(user, permission)
                and can_open_url(user, path)
            ),
            "permissions": [p for p in bt_permissions if has_permission(user, p)],
        }

    def choices(enum) -> list[list[str]]:
        return [[str(k), str(v)] for k, v in enum.choices]

    return {
        "roles": roles,
        "uganda_wide_roles": sorted(services.UGANDA_WIDE_ROLES),
        "summary_only_roles": sorted(services.SUMMARY_ONLY_ROLES),
        "mfi_roles": sorted(services.MFI_ROLES),
        "nav_role": NAV_ROLE,
        # Who reads a district's name as a link to its profile (district_link).
        "district_profile_roles": sorted(
            r.value
            for r in EdifyRole
            if can_open_url(_role_user(r.value), "/districts/0")
        ),
        "case_statuses": choices(m.CaseStatus),
        "open_case_statuses": [str(s) for s in m.OPEN_CASE_STATUSES],
        "recommendation_kinds": choices(m.RecommendationKind),
        "loan_statuses": choices(m.LoanStatus),
        "salesforce_statuses": choices(m.SalesforceStatus),
        "ia_statuses": choices(m.IAValidationStatus),
        "impact_statuses": choices(m.LoanImpactStatus),
        "metric_labels": {key: get_metric(key).label for key in METRIC_KEYS},
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Business Transformation pages' rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
