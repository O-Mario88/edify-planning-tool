"""Write the field pages' rules for the Go gateway.

Go builds the School Map (/map: apps.frontend.views.extended_views.map_view,
pages/map/index.html), the empty Search page (/search: search_view with no
query) and the Schedule School Visit form with nothing chosen yet
(/planning/schedule: planning_views.schedule_activity_form_view) as the
existing feed reads them, from what this command writes to
platform/backend/internal/fieldpages/rules.json: for each role, whether it
may open each page and whether its search lists staff; the roles whose staff
search crosses countries; the names of each activity state; and the
interventions the form offers. A change
must be exported again;
apps/frontend/test_field_pages_rules_export.py fails until it is.

    python manage.py export_field_pages_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/fieldpages/rules.json")

#: Each page, its permission and its path.
PAGES = {
    "map": ("schools", "/map"),
    "search": ("search", "/search"),
    "schedule": ("planning", "/planning/schedule"),
}


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            name: bool(
                RolePermissionService.can_view_page(user, permission)
                and can_open_url(user, path)
            )
            for name, (permission, path) in PAGES.items()
        }
        # search_view lists staff only for the staff directory's roles.
        roles[role.value]["search_staff"] = RolePermissionService.can_view_page(
            user, "staff_directory"
        )
    from apps.activities.models import ActivityStatus
    from apps.partners.models import PartnerAssignment
    from apps.core.enums import SsaIntervention

    from apps.frontend.views.extended_views import EVERY_COUNTRY_SEARCH_ROLES

    return {
        "roles": roles,
        # _searches_every_country: their staff search is not held to a country.
        "every_country_search_roles": sorted(EVERY_COUNTRY_SEARCH_ROLES),
        # A partner's search reaches the schools its organisation holds:
        # PartnerAssignment rows not in these states (resolve_user_scope).
        "partner_released_statuses": sorted(PartnerAssignment.RELEASED_STATUSES),
        # The names of each activity state, as search results print them.
        "activity_statuses": {str(v): str(lb) for v, lb in ActivityStatus.choices},
        # The form's Primary Focus Intervention choices, in their order.
        "interventions": [[str(v), str(label)] for v, label in SsaIntervention.choices],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the field pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
