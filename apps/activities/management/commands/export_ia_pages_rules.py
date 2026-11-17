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
    "/ia/compare/": "ia_compare",
    "/ia/impact-reports/": "impact_reports",
    "/ia/lending-evidence/": "ia_lending_evidence",
    "/ia/verification/": "ia_verification_queue",
    "/ia/dashboard/": "ia_dashboard",
}

#: The pages that draw the IA workspace strip (partials/_section_nav.html).
STRIP_PAGES = (
    "/ia/samples/",
    "/ia/stories/",
    "/ia/impact-reports/",
    "/ia/lending-evidence/",
    "/ia/verification/",
    "/ia/dashboard/",
)

#: The roles ia_samples_view offers "Draw this week now" (can_draw).
SAMPLE_DRAW_ROLES = ["ImpactAssessment", "CountryDirector", "Admin"]


def _lending() -> dict:
    """Lending Evidence (apps.frontend.views.ia_lending_views over
    apps.business_transformation.lending_impact): who sees the money, whose
    loans each role reaches (scoped_impact_loans), the states and labels the
    queues and conclusions carry, and the cohorts' evidence grade."""
    from apps.analytics import evidence_strength as es
    from apps.business_transformation import lending_impact as li
    from apps.business_transformation.models import (
        EnrolmentSnapshotKind,
        IAValidationStatus,
        ImpactEvidenceStatus,
        LoanImpactStatus,
        PurposeAllocationStatus,
    )
    from apps.core.permissions import Permission, has_permission
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import ia_lending_views as views

    def scope(role: str) -> str:
        if role in li.MFI_ROLES:
            return "mfi"
        if role in li.COUNTRY_BOUND_ROLES:
            return "country_bound"
        if role in li.COUNTRY_ROLES:
            return "country"
        if role in {EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value}:
            return "portfolio"
        return "none"

    return {
        "money_roles": sorted(
            role.value
            for role in EdifyRole
            if has_permission(
                _role_user(role.value),
                Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW.value,
            )
        ),
        "scope": {role.value: scope(role.value) for role in EdifyRole},
        "legacy_preparer": li.LEGACY_PREPARER,
        "tabs": [list(t) for t in views.TABS],
        "state_labels": dict(views.STATE_LABELS),
        "classification_labels": {k: str(v) for k, v in LoanImpactStatus.choices},
        "positive": [str(s) for s in views.POSITIVE],
        "neutral": [str(s) for s in views.NEUTRAL],
        "negative": str(LoanImpactStatus.NEGATIVE),
        "snapshot_kinds": {k: str(v) for k, v in EnrolmentSnapshotKind.choices},
        "baseline_kind": str(EnrolmentSnapshotKind.BASELINE),
        "use_reported": str(PurposeAllocationStatus.REPORTED),
        "evidence_reported": str(ImpactEvidenceStatus.REPORTED),
        "evidence_verified": str(ImpactEvidenceStatus.VERIFIED),
        "ia_pending": str(IAValidationStatus.PENDING),
        "ia_returned": str(IAValidationStatus.RETURNED),
        "ia_verified": str(IAValidationStatus.VERIFIED),
        "min_n": es.MIN_N,
        "grade_labels": {
            "insufficient": es.LABELS[es.INSUFFICIENT],
            "descriptive": es.LABELS[es.DESCRIPTIVE],
        },
        "page_size": views.PAGE_SIZE,
        "cohort_caveat": views.COHORT_CAVEAT,
    }


def _collection() -> dict:
    """The dashboard's Collection view (apps.analytics.ia_collection): each
    state's label, next step and order, the statuses it is read from, the
    projects whose enrolments make the segment, and the page."""
    from apps.analytics import ia_collection as c
    from apps.core.enums import VerificationStatus
    from apps.projects.models import LIVE_PROJECT_STATUSES

    return {
        "states": [[key, meta[0], meta[1]] for key, meta in c.STATES.items()],
        "work_states": list(c.WORK_STATES),
        "operating_statuses": list(c.COLLECTION_OPERATING_STATUSES),
        "open_statuses": list(c.OPEN_COLLECTION_STATUSES),
        "delivered_statuses": list(c.DELIVERED_STATUSES),
        "live_project_statuses": sorted(str(s) for s in LIVE_PROJECT_STATUSES),
        "verification_labels": dict(VerificationStatus.choices),
        "page_size": c.PAGE_SIZE,
        "page_param": c.PAGE_PARAM,
    }


def _outcomes() -> dict:
    """The dashboard's Outcomes view (apps.analytics.ia_workflow): the SSA
    domains in order, the enrolment states' words, the measured
    classifications, the evidence floor, the change rule's words and the
    statuses an outcome area and a measurement rule are read in."""
    from apps.activity_catalogue.models import MappingStatus
    from apps.analytics import evidence_strength
    from apps.analytics import ia_workflow as workflow
    from apps.core.enums import SsaIntervention
    from apps.impact.models import DefinitionStatus
    from apps.projects.ssa_impact import MEASURED
    from apps.ssa import change_rules

    return {
        "interventions": [[code, label] for code, label in SsaIntervention.choices],
        "state_labels": workflow.STATE_LABELS,
        "measured": [str(m) for m in MEASURED],
        "limitation": workflow.LIMITATION,
        "portfolio_limitation": workflow.PORTFOLIO_LIMITATION,
        "cohort_period": workflow.COHORT_PERIOD,
        "rule_sentence": change_rules.RULE_SENTENCE,
        "fallback_label": change_rules.FALLBACK_LABEL,
        "min_interval_days": change_rules.MIN_INTERVAL_DAYS,
        "min_n": evidence_strength.MIN_N,
        "insufficient_label": evidence_strength.LABELS[evidence_strength.INSUFFICIENT],
        "area_approved_status": str(DefinitionStatus.APPROVED),
        "rule_published_status": str(MappingStatus.PUBLISHED),
    }


def _dashboard() -> dict:
    """The IA dashboard (ia_dashboard_view) as Go draws its Today and
    Operations views: the view rail's labels, the header tiles' labels and
    drill-downs, who may open a record's review (the primary action), and the
    thresholds and states its exceptions count."""
    from apps.activities.ia_todos import DUPLICATE_OPEN_STATUS, UNMATCHED_OPEN_STATUSES
    from apps.core.metrics import MetricValue, render_metric
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import ia_views as views
    from apps.frontend.templatetags.frontend_filters import can_open
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.targets.performance import ACHIEVED_STATUSES

    return {
        "tabs": [[key, label] for key, label, _ in views.IA_DASHBOARD_TABS],
        "default_view": views.IA_DASHBOARD_DEFAULT_VIEW,
        "metrics": [
            [render_metric(key, MetricValue.measured(0)).label, url]
            for key, url in views.IA_HEADER_METRICS
        ],
        "review_open_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open(_role_user(role.value), "/ia/verification/x/")
        ),
        "queue_open_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open(_role_user(role.value), "/ia/verification/")
        ),
        "district_ssa_target": views.IA_DISTRICT_SSA_TARGET,
        "return_overdue_days": views.IA_RETURN_OVERDUE_DAYS,
        "failed_upload_statuses": list(views.IA_FAILED_UPLOAD_STATUSES),
        "school_duplicate_statuses": list(views.IA_SCHOOL_DUPLICATE_STATUSES),
        "unmatched_open_statuses": list(UNMATCHED_OPEN_STATUSES),
        "duplicate_open_status": DUPLICATE_OPEN_STATUS,
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "outcomes": _outcomes(),
        "collection": _collection(),
        # The Map view's roll-ups: the plans left out, and the done-states.
        "performance_excluded_statuses": list(views.IA_PERFORMANCE_EXCLUDED_STATUSES),
        "achieved_statuses": list(ACHIEVED_STATUSES),
    }


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
    from apps.frontend.views.impact_report_views import (
        PAGE_SIZE as IMPACT_REPORT_PAGE_SIZE,
    )
    from apps.impact import reports as impact_reports
    from apps.impact.models import Programme, ReportStatus
    from apps.pl_review.services import LEAD_VERIFIED_ROLES
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
        "lending": _lending(),
        "dashboard": _dashboard(),
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
        # Evidence Compare (ia_compare_view): the roles whose staff work a
        # Programme Lead verifies, so IA's picker leaves it out
        # (apps.pl_review.services.lead_verified_q), and the lead role.
        "lead_verified_roles": list(LEAD_VERIFIED_ROLES),
        "lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        # Impact Reports (apps.impact.reports): each status's label in order,
        # the programmes, what an RVP reads, the open recommendation states,
        # and the register's page size.
        "report_statuses": [[k, str(v)] for k, v in ReportStatus.choices],
        "report_programmes": {k: str(v) for k, v in Programme.choices},
        "report_rvp_statuses": list(impact_reports.RVP_STATUSES),
        "report_open_recommendations": list(impact_reports.OPEN_RECOMMENDATIONS),
        "report_page_size": IMPACT_REPORT_PAGE_SIZE,
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
