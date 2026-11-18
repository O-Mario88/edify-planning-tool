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
            # The row links (apps.frontend.templatetags.school_links): a
            # school's and a cluster's name open its profile for a reader
            # who may open one.
            "school_profiles": bool(can_open_url(user, "/schools/0")),
            "cluster_profiles": bool(can_open_url(user, "/clusters/0")),
            "resolves_returns": has_permission(
                user, Permission.PARTNER_RETURN_RESOLVE.value
            ),
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
        "work": work(),
    }


def work() -> dict:
    """The vocabularies the page's rows are read with: each phase's statuses
    (partner_oversight_service), the withdrawal each state permits
    (withdrawal_service.resolve_kind, action_label), the activity families
    and their labels, the purposes, the completion columns' words
    (apps.activities.completion_columns) and the risk rules' grace days
    (partner_risk_service)."""
    from apps.activities import completion_columns as completion
    from apps.core import activity_types
    from apps.core.enums import ActivityType, EvidenceKind, SsaIntervention
    from apps.partners import purposes
    from apps.partners import withdrawal_service as withdrawal
    from apps.partners.models import PartnerAssignment
    from apps.partners.withdrawal_models import WithdrawalKind
    from apps.planning import partner_oversight_service as service
    from apps.planning import partner_risk_service as risk
    from apps.planning.country_oversight.rules import DATED_BY_STAFF
    from apps.planning.school_planning_badges import PLANNED_STATUSES
    from apps.analytics.pl_analytics_service import (
        COMPLETED_STATUSES as ANALYTICS_COMPLETED,
    )
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.planning.partner_follow_up import FOLLOW_UP
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "unscheduled_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "in_progress": list(service._IN_PROGRESS_STATUSES),
        "evidence_review": list(service._EVIDENCE_REVIEW_STATUSES),
        "awaiting_ia": list(service._AWAITING_IA_STATUSES),
        "complete": list(service._COMPLETE_STATUSES),
        "not_started": list(service._NOT_STARTED_STATUSES),
        "returned_to_partner": list(service._RETURNED_TO_PARTNER_STATUSES),
        "paid": list(service._PAID_STATUSES),
        "payment_processing": list(service._PAYMENT_PROCESSING_STATUSES),
        "data_gathering_types": sorted(service._DATA_GATHERING_TYPES),
        "data_gathering_label": service.DATA_GATHERING_LABEL,
        "withdrawal": {
            "not_started": list(withdrawal._NOT_STARTED_STATUSES),
            "in_progress": list(withdrawal._IN_PROGRESS_STATUSES),
            "evidence": list(withdrawal._EVIDENCE_STATUSES),
            "ia_cleared": list(withdrawal._IA_CLEARED_STATUSES),
            "closed": list(withdrawal._CLOSED_STATUSES),
            "paid": list(withdrawal._PAID_STATUSES),
            "labels": {kind.value: kind.label for kind in WithdrawalKind},
            "withdraw_from_partner": withdrawal.WITHDRAW_FROM_PARTNER,
        },
        "dated_by_staff": DATED_BY_STAFF,
        "visit_types": sorted(activity_types.VISIT_TYPES),
        "training_types": sorted(activity_types.TRAINING_TYPES),
        "cluster_meeting_types": sorted(activity_types.CLUSTER_MEETING_TYPES),
        "planned_statuses": sorted(PLANNED_STATUSES),
        "activity_type_labels": {c.value: c.label for c in ActivityType},
        "intervention_labels": {c.value: c.label for c in SsaIntervention},
        "purpose_labels": dict(purposes._LABELS),
        "completion": {
            "officer_completed": sorted(completion.OFFICER_COMPLETED_STATUSES),
            "completed_work": sorted(activity_types.COMPLETED_WORK_STATUSES),
            "attendance_types": sorted(completion._ATTENDANCE_TYPES),
            "evidence_kind_labels": {c.value: c.label for c in EvidenceKind},
            "missing_sf": completion.MISSING_SF,
            "missing_evidence": completion.MISSING_EVIDENCE,
            "missing_both": completion.MISSING_BOTH,
        },
        "follow_up": {
            "recommendations": list(FOLLOW_UP),
            "operating_statuses": [str(s) for s in OPERATING_STATUSES],
            "not_in_plan": list(NOT_IN_PLAN_ACTIVITY_STATUSES),
            "completed": list(ANALYTICS_COMPLETED),
            "released": list(PartnerAssignment.RELEASED_STATUSES),
        },
        "risk": {
            "schedule_grace_days": risk.SCHEDULE_GRACE_DAYS,
            "approaching_days": risk.APPROACHING_DAYS,
            "evidence_grace_days": risk.EVIDENCE_GRACE_DAYS,
            "review_grace_days": risk.REVIEW_GRACE_DAYS,
            "payment_grace_days": risk.PAYMENT_GRACE_DAYS,
            "ia_verification_grace_days": risk.IA_VERIFICATION_GRACE_DAYS,
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Partner Monitoring's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
