"""Write the IA review pages' rules for the Go gateway.

Go builds the Impact Assessment review pages (apps.frontend.views.ia_views)
from what this command writes to
platform/backend/internal/iapages/rules.json: for each page Go answers, who
may open it (the pages draw no workspace strip); which
roles hold the IA verification permission (without it a reader sees only the
work an Impact Assessment officer ran, `_ia_reach_q`); each activity
type's label; the evidence each activity must carry; the partner queue's length; Sample Checks' strip, share, drawers and methods; who is offered a queue's Export; and who may open a school's profile. A change to any of them must be exported again;
apps/activities/test_ia_pages_rules_export.py fails until it is.

    python manage.py export_ia_pages_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/iapages/rules.json")

#: The pages Go answers and their page permission.
PAGES = {
    "/ia/duplicates/": "ia_duplicates",
    "/ia/returned/": "ia_returned",
    "/ia/history/": "ia_history",
    "/ia/partner-evidence/": "ia_partner_evidence",
    "/ia/samples/": "ia_samples",
    "/ia/analytics/": "ia_verification_analytics",
    "/ia/stories/": "ia_stories",
}

#: The pages that draw the IA workspace strip (partials/_section_nav.html).
STRIP_PAGES = ("/ia/samples/", "/ia/stories/")

#: The roles ia_samples_view offers "Draw this week now" (can_draw).
SAMPLE_DRAW_ROLES = ["ImpactAssessment", "CountryDirector", "Admin"]


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.permissions import (
        Permission,
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.evidence.requirements import (
        PROFILE_REQUIRED_EVIDENCE,
        REQUIRED_EVIDENCE,
    )
    from apps.activities.ia_models import VerificationSample
    from apps.activities.verification_sampling import sample_share_pct
    from apps.analytics.ia_collection import PAGE_SIZE as SAMPLE_PAGE_SIZE
    from apps.frontend.views.ia_views import QUEUE_PAGE_SIZE
    from apps.core.enums import SsaIntervention
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.impact.models import DefinitionStatus
    from apps.targets.models import MSCSStatus
    from apps.targets.mscs_review import SPIRITUAL_DOMAINS
    from apps.mobile_feed.views import NOT_PASSED

    pages = {}
    for path, permission in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            page = RolePermissionService.can_view_page(user, permission) and bool(
                can_open_url(user, path)
            )
            roles[role.value] = {
                "page": page,
                # Sample Checks and the stories draw the IA workspace strip;
                # the others none.
                "strip": strip(user, path, "partials/_section_nav.html")
                if page and path in STRIP_PAGES
                else None,
            }
        pages[path] = {"roles": roles}
    return {
        "pages": pages,
        "ia_verify_roles": sorted(
            role.value
            for role in EdifyRole
            if has_permission(_role_user(role.value), Permission.IA_VERIFY.value)
        ),
        # Who is offered a queue's Export (partials/ia/export_button.html:
        # RolePermissionService.can_export, the data-export permission).
        "export_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_export(_role_user(role.value), "")
        ),
        "activity_types": dict(ActivityType.choices),
        # The evidence each activity must carry (apps.evidence.requirements):
        # by its evidence profile, else by its type.
        "required_evidence": {
            k: [str(kind) for kind in v] for k, v in REQUIRED_EVIDENCE.items()
        },
        "profile_required_evidence": {
            k: [str(kind) for kind in v] for k, v in PROFILE_REQUIRED_EVIDENCE.items()
        },
        "queue_page_size": QUEUE_PAGE_SIZE,
        # Sample Checks: the share drawn, who may draw, how a check is made
        # and the samples' page size.
        "sample_share_pct": sample_share_pct(),
        "sample_draw_roles": SAMPLE_DRAW_ROLES,
        "sample_methods": dict(VerificationSample.METHOD_CHOICES),
        "sample_page_size": SAMPLE_PAGE_SIZE,
        # Verification Analytics pages each of its tables (TABLE_PAGE_SIZE).
        "table_page_size": TABLE_PAGE_SIZE,
        # Most Significant Change (apps.frontend.views.ia_stories_views and
        # apps.targets.mscs_review): each story status's label, the
        # intervention labels, the SSA domains that are spiritual formation,
        # and the outcome-area statuses never offered and the one that is
        # approved.
        "story_statuses": [[v, str(label)] for v, label in MSCSStatus.choices],
        "intervention_labels": {k: str(v) for k, v in SsaIntervention.choices},
        "spiritual_domains": list(SPIRITUAL_DOMAINS),
        "outcome_area_hidden_statuses": [
            DefinitionStatus.RETIRED.value,
            DefinitionStatus.SUPERSEDED.value,
        ],
        "outcome_area_approved_status": DefinitionStatus.APPROVED.value,
        "query_keys_not_passed": sorted(NOT_PASSED),
        # Who may open a school's profile, so a school's name is a link
        # (apps.frontend.templatetags.school_links._may_open_profiles).
        "school_profile_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open_url(_role_user(role.value), "/schools/0")
        ),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the IA review pages' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
