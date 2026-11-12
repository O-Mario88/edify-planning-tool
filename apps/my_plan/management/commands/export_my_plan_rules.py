"""Write My Plan's rules for the Go gateway.

Go owns Activity planning and scheduling (owner brief, 2026-11-11). It
builds My Plan (/my-plan, my_plan_views.my_plan_view,
apps.my_plan.services.get_frontend_context and the page's templates) from
the vocabularies this command writes to
platform/backend/internal/myplan/rules.json: who may open the page, the
period filters' choices, the strip's labels, the keys that turn the page
into an export, and the planning roles whose page carries their own Planned
and remaining. A change to any of them must be exported again;
apps/my_plan/test_my_plan_rules_export.py fails until it is, so the two can
never drift.

    python manage.py export_my_plan_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/myplan/rules.json")


def doors() -> dict:
    """Whether each role may open the page, by the page's own gates:
    require_page_permission("my_plan") and the feed's can_open_url."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, "my_plan")
            and bool(can_open_url(user, "/my-plan")),
        }
    return out


def strip() -> dict:
    """The Plan progress strip as the metric registry labels it, and the
    words its completed share shows when nothing was planned."""
    from apps.core.metrics import MetricValue, render_metric, render_strip
    from apps.my_plan.services import MY_PLAN_TILES

    keys = [key for key, _icon, _variant in MY_PLAN_TILES]
    # As the page renders them with nothing planned: counts of 0 and the
    # completed share of nothing (get_frontend_context).
    values = [MetricValue.measured(0) for _key in keys[:-1]]
    values.append(MetricValue.ratio(0, 0))
    items = render_strip(
        [
            render_metric(key, value, drilldown_url="/my-plan")
            for key, value in zip(keys, values)
        ]
    )
    return {
        "keys": keys,
        "labels": [item["label"] for item in items],
        "drilldown": "/my-plan",
        "no_data": items[-1]["display_value"],
    }


def rules() -> dict:
    from django.conf import settings

    from apps.frontend.views.my_plan_views import EXPORT_PERIOD_KEYS
    from apps.mobile_feed.views import NOT_PASSED
    from apps.my_plan import services
    from apps.planning.country_oversight import rules as planning_rules

    return {
        "doors": doors(),
        "strip": strip(),
        "month_options": [[m["val"], m["label"]] for m in services.MONTH_OPTIONS],
        "quarter_options": list(services.QUARTER_OPTIONS),
        "quarter_first_month": dict(services.QUARTER_FIRST_MONTH),
        "unset_filter_values": sorted(services._UNSET_FILTER_VALUES),
        "export_period_keys": list(EXPORT_PERIOD_KEYS),
        "not_passed_query_keys": sorted(NOT_PASSED),
        # panel_views.plans_visits: a Programme Lead or a CCEO by the role
        # held has a Planned and remaining of their own, and a visit target.
        "program_lead_role": planning_rules.PROGRAM_LEAD_ROLE,
        "cceo_role": planning_rules.CCEO_ROLE,
        "visit_targets": dict(planning_rules.VISIT_TARGETS),
        # scoping.resolve_partner_ids: with the demo bridge on, every reader
        # is the first active partner.
        "partner_role_bridge": bool(getattr(settings, "PARTNER_ROLE_BRIDGE", False)),
        # The feed is a REST framework view: a ?format= no renderer answers
        # is "not found" before the page is asked.
        "api_formats": api_formats(),
    }


def api_formats() -> list[str]:
    from rest_framework.settings import api_settings

    return sorted(renderer.format for renderer in api_settings.DEFAULT_RENDERER_CLASSES)


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write My Plan's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
