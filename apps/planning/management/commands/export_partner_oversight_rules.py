"""Write Partner Monitoring's rules for the Go gateway.

Go builds Partner Monitoring (/partner-oversight/, apps.frontend.views.
oversight_views.partner_oversight_view, apps.planning.partner_oversight_service
and pages/oversight/partner_oversight.html with partials/oversight/
partner_workspace.html) from what this command writes to
platform/backend/internal/partneroversight/rules.json: who may open the page,
the lens each role reads it through, who is offered Add Partner Organisation,
who sees the partnership register and its Regional Lead observations tile, the
Status filter's phases, the work tabs, the planning roles the monitor's roster
is read by, the vocabularies the page's sources are read with, and the
headline tiles as the page draws them for a reader with no partner work. A
change to any of them must be exported again;
apps/planning/test_partner_oversight_rules_export.py fails until it is.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks.

    python manage.py export_partner_oversight_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/partneroversight/rules.json")

PAGE_PATH = "/partner-oversight/"


def _lens(user) -> str:
    """partner_oversight_service._resolve_scope's kind, without its reads."""
    from apps.core.permissions import has_permission
    from apps.core.rbac import EdifyRole, Permission

    if user.active_role == EdifyRole.REGIONAL_PROGRAM_LEAD.value:
        return "region"
    if has_permission(user, Permission.PARTNER_MONITORING_COUNTRY.value):
        return "country"
    return "team"


def roles() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import can_open_url, has_permission
    from apps.core.rbac import EdifyRole, Permission, holds_operational_admin
    from apps.partners import engagement_services
    from apps.partners.services import may_create_partner_organisation

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        records = engagement_services.can_record(user)
        out[role.value] = {
            # partner_oversight_view's PARTNER_MONITORING_VIEW, and the feed's
            # can_open_url.
            "page": has_permission(user, Permission.PARTNER_MONITORING_VIEW.value)
            and bool(can_open_url(user, PAGE_PATH)),
            "lens": _lens(user),
            # _resolve_scope: a CCEO's team is their own work alone.
            "own_work_only": role.value == EdifyRole.CCEO.value,
            "create_partner": may_create_partner_organisation(user),
            # The partnership register: the roles that record engagements, and
            # the operational admins who read them.
            "engagement_register": records or holds_operational_admin(user),
            "records_engagements": records,
            # engagements_visible_to: a Programme Lead reads their own.
            "reads_own_engagements": engagement_services._role(user)
            == engagement_services.PROGRAM_LEAD,
            # The Regional Lead observations tile and its follow-ups.
            "observations_tile": engagement_services._role(user)
            == engagement_services.PROGRAM_LEAD,
        }
    return out


def zero_tiles(target) -> list[dict]:
    """The headline tiles for a reader with no partner work, as the strip
    (components/context_metrics.html) draws them and the feed reads them."""
    from apps.core.templatetags.kpi_metrics import kpi_value, professional_kpis
    from apps.frontend.views.oversight_views import _partner_kpis
    from apps.planning import partner_oversight_service as service

    out = []
    for item in professional_kpis(_partner_kpis(service.summarize([]), target)):
        helper = item.get("helper") or ""
        out.append(
            {
                "label": item.get("label") or "",
                "value": kpi_value(item)["display"],
                "helper": helper,
                "note": item.get("helper_note") or "",
                "tone": (item.get("tone") or "") if helper else "",
            }
        )
    return out


def rules() -> dict:
    from apps.core.enums import DeliveryType
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import partner_engagement_views as engagement_views
    from apps.frontend.views.oversight_views import PARTNER_STATUS_FILTER_KEYS
    from apps.mobile_feed.views import NOT_PASSED
    from apps.partners import engagement_services
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import LEFT_PARTNER_STATUSES
    from apps.partners.withdrawal_models import WithdrawalState
    from apps.planning import partner_oversight_service as service
    from apps.planning.country_oversight import rules as planning_rules

    zero_target = {"target": 0, "core": 0, "beyond_staff": 0, "held": 0}
    return {
        "roles": roles(),
        "status_filter_keys": list(PARTNER_STATUS_FILTER_KEYS),
        "work_tabs": [key for key, _label in service.WORK_TABS],
        "core_work_tab": service.TAB_CORE,
        "planning_lead_role": planning_rules.PROGRAM_LEAD_ROLE,
        "planning_cceo_role": planning_rules.CCEO_ROLE,
        # program_lead_rosters: a roster's Lead holds this role.
        "roster_lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "partner_delivery": DeliveryType.PARTNER.value,
        "withdrawal_requested": WithdrawalState.REQUESTED.value,
        # left_partner_q: work the Partner no longer holds.
        "left_partner_statuses": list(LEFT_PARTNER_STATUSES),
        "returned_to_staff": PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        "partner_action_recommendations": list(
            engagement_services.PARTNER_ACTION_RECOMMENDATIONS
        ),
        "engagement_metric_words": {
            key: list(words)
            for key, words in engagement_views.ENGAGEMENT_METRIC_WORDS.items()
        },
        "engagement_autoload_params": list(engagement_views.AUTOLOAD_PARAMS),
        "engagement_page_param": engagement_views.PAGE_PARAM,
        # The tiles with no monitor behind the reader, and with one whose
        # every total is zero.
        "zero_tiles": zero_tiles(None),
        "zero_tiles_with_target": zero_tiles(zero_target),
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Partner Monitoring's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
