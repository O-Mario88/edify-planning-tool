"""Write Core School Oversight's rules for the Go gateway.

Go is to be the application's only backend (owner, 2026-11-11). It builds
Core School Oversight (/core-schools-oversight/, apps.frontend.views.
core_oversight_views) from the vocabularies this command writes to
platform/backend/internal/coreoversight/rules.json: who may open the page and
each of its doors, its tabs, filters and sorts, the readings of
apps.core_schools.intelligence (trajectories, Champion readiness, what a
school needs), the statuses and activity types each figure counts, and the
official Champion rule's statuses. A change to any of them must be exported
again; apps/core_schools/test_core_oversight_rules_export.py fails until it
is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks (require_page_permission, can_open_url and the
template's school links).

    python manage.py export_core_oversight_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/coreoversight/rules.json")

#: The page as the app's feed opens it.
PAGE_PATH = "/core-schools-oversight/"
URL_NAME = "core_schools_oversight"
#: The scale an SSA band is read on, in hundredths.
SCORE_STEPS = 1001


def doors() -> dict:
    """What each role may do on Core School Oversight, by the page's gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("core_schools_oversight") and the
            # feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, URL_NAME)
            and bool(can_open_url(user, PAGE_PATH)),
            # {% school_link %}: a name is a link for a reader the school
            # profile lets in.
            "school": bool(can_open_url(user, "/schools/0")),
            # may_review_champions: the Champion review is the Core Schools
            # page's.
            "review": RolePermissionService.can_view_page(user, "core_schools"),
            # The header's Download CSV and Download Excel (can_export).
            "export": RolePermissionService.can_export(user, PAGE_PATH),
        }
    return out


def critical_below() -> float:
    """The score below which ssa_score_band names a score Critical, read off
    the band itself in hundredths."""
    from apps.core.enums import ssa_score_band

    critical = [ssa_score_band(n / 100)[0] == "Critical" for n in range(SCORE_STEPS)]
    floor = critical.index(False)
    if any(critical[floor:]):
        raise ValueError("a Critical score above a score that is not Critical")
    return floor / 100


def rules() -> dict:
    from apps.core.activity_types import TRAINING_TYPES
    from apps.core.enums import SchoolType, SsaIntervention
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.rbac import EdifyRole
    from apps.core_schools import champion_services as champion
    from apps.core_schools import intelligence
    from apps.core_schools.lifecycle import CORE_LIFECYCLE_TYPES
    from apps.core_schools.services import (
        CORE_PLAN_CLOSED_STATUSES,
        CORE_SLOT_DONE_STATUSES,
        PACKAGE_WORK_KINDS,
        PACKAGE_WORK_SLOTS,
    )
    from apps.frontend.views import core_oversight_views as view
    from apps.mobile_feed.views import NATIVE_PAGES, NOT_PASSED
    from apps.partners.models import PartnerAssignment
    from apps.planning import school_planning_badges as badges
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.ssa import change_rules
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.recommendation_models import LIVE_STATES, RecommendationState

    return {
        "doors": doors(),
        "feed_opens_page": URL_NAME in NATIVE_PAGES,
        "not_passed_query_keys": sorted(NOT_PASSED),
        "table_page_size": TABLE_PAGE_SIZE,
        "tabs": [list(tab) for tab in view.TABS],
        "plan_tabs": list(view.PLAN_TABS),
        "trajectory_filters": [list(kv) for kv in view.TRAJECTORY_FILTERS.items()],
        "sorts": [[key, label] for key, (label, _key) in view.SORTS.items()],
        "groupings": [list(kv) for kv in intelligence.GROUPINGS.items()],
        "trajectory_labels": dict(intelligence.TRAJECTORY_LABELS),
        "trajectory_tones": dict(intelligence.TRAJECTORY_TONES),
        "change": {
            "improved": change_rules.IMPROVED,
            "declined": change_rules.DECLINED,
            "no_change": change_rules.NO_CHANGE,
            "maintained_strong": change_rules.MAINTAINED_STRONG,
            "not_comparable": change_rules.NOT_COMPARABLE,
        },
        "champion": {
            "order": list(intelligence.CHAMPION_ORDER),
            "champion": intelligence.CHAMPION,
            "potential": intelligence.POTENTIAL,
            "progressing": intelligence.PROGRESSING,
            "not_yet": intelligence.NOT_YET,
            "insufficient": intelligence.INSUFFICIENT,
            "latest_avg": intelligence.CHAMPION_LATEST_AVG,
            "stored_champion": list(intelligence.STORED_CHAMPION_STATUSES),
            "champion_type": SchoolType.CHAMPION.value,
            "confirmed_ssa": champion.CONFIRMED_SSA,
            "closed_status": champion.CLOSED_STATUS,
            "clean_evidence": champion.CLEAN_EVIDENCE,
            "plan_closed_statuses": sorted(CORE_PLAN_CLOSED_STATUSES),
            "package_work_kinds": list(PACKAGE_WORK_KINDS),
            "slot_done_statuses": sorted(CORE_SLOT_DONE_STATUSES),
            "package_work_slots": PACKAGE_WORK_SLOTS,
        },
        "attention": {
            "order": list(intelligence.ATTENTION_ORDER),
            "declined": intelligence.DECLINED_REASON,
            "critical": intelligence.CRITICAL_REASON,
            "no_ssa": intelligence.NO_SSA_REASON,
            "package": intelligence.PACKAGE_REASON,
            "handover": intelligence.HANDOVER_REASON,
            "candidate": intelligence.CANDIDATE_REASON,
            "critical_below": critical_below(),
        },
        "program_lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "core_types": list(CORE_LIFECYCLE_TYPES),
        "school_types": dict(SchoolType.choices),
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "current_ssa_statuses": list(CURRENT_SSA_STATUSES),
        "confirmed_status": champion.CONFIRMED_SSA,
        "ssa_interventions": [[key.value, key.label] for key in SsaIntervention],
        "handover_unscheduled": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "handover_scheduled": [
            PartnerAssignment.STATUS_SCHEDULED,
            PartnerAssignment.STATUS_PARTNER_SCHEDULED,
        ],
        "handover_completed": PartnerAssignment.STATUS_COMPLETED,
        "delivered_statuses": sorted(
            badges.AWAITING_VERIFICATION_STATUSES | badges.VERIFIED_STATUSES
        ),
        "cluster_session_types": [str(t) for t in badges.CLUSTER_SESSION_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
        "recommendation_states": dict(RecommendationState.choices),
        "recommendation_shown_states": [
            *(str(s) for s in LIVE_STATES),
            str(RecommendationState.PLANNED),
        ],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Core School Oversight's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
