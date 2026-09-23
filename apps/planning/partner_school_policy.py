"""What staff may plan directly at a Partner-supported school.

Owner rule, 2026-09-23. When a school's support has been handed to a Partner,
the Partner delivers that support; staff keep the school and may still plan the
work that is not the delegated support:

    Partner-supported school + normal (direct) Planning
        = Data Gathering, Content Gathering or Donor Visit only
    Partner-supported school + Cluster Planning
        = Cluster Meeting and Group Training allowed

Everything is keyed on the governed Activity Catalogue's ``stable_code`` and
``workflow_kind`` — never on a display name, which the Country Director may
reword — and the same policy answers the drawer (which purposes to offer) and
the canonical create service (what to refuse), so the page cannot offer a
choice the server then rejects without saying why.

Schools with no live Partner support are untouched: this policy returns
``ALLOWED_DIRECT_STAFF_ACTIVITY`` for them without reading the catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from apps.core.enums import ActivityType

# ── The governed whitelist ───────────────────────────────────────────────────
#: Stable codes staff may schedule directly at a Partner-supported school.
#: Data Gathering has two governed items: the standard school visit that
#: collects the SSA (what the Planning drawer's "SSA Support" purpose costs)
#: and the ASA/SSA project data-gathering item.
DIRECT_STAFF_ACTIVITY_CODES: dict[str, str] = {
    "STANDARD_SCHOOL_VISIT_SSA_COLLECTION": "Data Gathering",
    "ASA_SSA_DATA_GATHERING": "Data Gathering",
    "STANDARD_STORY_GATHERING_VISIT": "Content Gathering",
    "STANDARD_DONOR_VISIT": "Donor Visit",
}

#: The standard cluster items. Group Training also covers the governed
#: curriculum courses delivered to a cluster, which share the
#: ``cluster_training`` workflow kind; the kind is the stable test for those.
CLUSTER_ACTIVITY_CODES = ("STANDARD_CLUSTER_MEETING", "STANDARD_CLUSTER_TRAINING")
CLUSTER_WORKFLOW_KINDS = (
    ActivityType.CLUSTER_MEETING,
    ActivityType.CLUSTER_TRAINING,
    ActivityType.CLUSTER_MEETING_SSA_REVIEW,
    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
)

ORIGIN_SCHOOL = "school_planning"
ORIGIN_CLUSTER = "cluster_planning"
ORIGIN_PROJECT = "project_planning"
ORIGIN_CORE = "core_planning"


class PlanningDecision(str, Enum):
    ALLOWED_DIRECT_STAFF_ACTIVITY = "ALLOWED_DIRECT_STAFF_ACTIVITY"
    PARTNER_WORKFLOW_REQUIRED = "PARTNER_WORKFLOW_REQUIRED"
    ALLOWED_FROM_CLUSTER_PLANNING = "ALLOWED_FROM_CLUSTER_PLANNING"
    NOT_ALLOWED = "NOT_ALLOWED"


@dataclass(frozen=True)
class PolicyResult:
    decision: PlanningDecision
    reason: str = ""
    partner_name: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision in (
            PlanningDecision.ALLOWED_DIRECT_STAFF_ACTIVITY,
            PlanningDecision.ALLOWED_FROM_CLUSTER_PLANNING,
        )


def restriction_message(partner_name: str) -> str:
    """The sentence the drawer shows and the service refuses with — one text."""
    return (
        f"This school is currently supported by {partner_name or 'a Partner'}. "
        "Staff may directly plan Data Gathering, Content Gathering, or Donor "
        "Visits. Use Cluster Planning for approved group activities."
    )


class PartnerSupportedSchoolPlanningPolicy:
    """The one answer to "may staff plan this here", for page and service."""

    @staticmethod
    def evaluate(
        school,
        catalogue_item=None,
        *,
        activity_type: str | None = None,
        planning_origin: str = ORIGIN_SCHOOL,
        delivery_channel: str = "staff",
        fy: str | None = None,
        project_id: str | None = None,
        principal=None,
        responsibility=None,
    ) -> PolicyResult:
        from apps.partners.support_responsibility import (
            SchoolSupportResponsibilityService,
            visibility_enabled,
        )

        allowed = PolicyResult(PlanningDecision.ALLOWED_DIRECT_STAFF_ACTIVITY)
        if school is None or not visibility_enabled(principal):
            return allowed
        kind = getattr(catalogue_item, "workflow_kind", None) or activity_type or ""

        # Cluster Planning: the school is one explicitly invited member of a
        # group session. Partner support never blocks it.
        if planning_origin == ORIGIN_CLUSTER:
            if kind in CLUSTER_WORKFLOW_KINDS or (
                getattr(catalogue_item, "stable_code", "") in CLUSTER_ACTIVITY_CODES
            ):
                return PolicyResult(PlanningDecision.ALLOWED_FROM_CLUSTER_PLANNING)
            return PolicyResult(
                PlanningDecision.NOT_ALLOWED,
                "Cluster Planning schedules Cluster Meetings and Group Training.",
            )
        # Partner delivery IS the Partner workflow; the Partner's own
        # scheduling and certified-agency bookings are not staff planning.
        if delivery_channel != "staff":
            return PolicyResult(PlanningDecision.PARTNER_WORKFLOW_REQUIRED)
        # Special Project work is governed by the project's own approved
        # activity list and funding line, and Core package slots by the
        # package's staff/Partner split (two visits each). Neither is the
        # delegated general support this rule protects.
        if project_id or planning_origin in (ORIGIN_PROJECT, ORIGIN_CORE):
            return allowed

        responsibility = (
            responsibility
            or SchoolSupportResponsibilityService.for_school(school, fy=fy)
        )
        if not responsibility.is_partner:
            return allowed

        partner = responsibility.responsible_name
        code = getattr(catalogue_item, "stable_code", "") or ""
        whitelisted = code in DIRECT_STAFF_ACTIVITY_CODES or (
            catalogue_item is None and kind in allowed_workflow_kinds()
        )
        if whitelisted:
            if principal is not None and not _may(
                principal, "PARTNER_SCHOOL_DIRECT_PLAN"
            ):
                return PolicyResult(
                    PlanningDecision.NOT_ALLOWED,
                    f"This school is currently supported by {partner}, and your "
                    "role does not plan directly at Partner-supported schools.",
                    partner,
                )
            return allowed
        # Anything else — including a group activity attempted against the one
        # school rather than planned for its cluster — is the Partner's.
        return PolicyResult(
            PlanningDecision.PARTNER_WORKFLOW_REQUIRED,
            restriction_message(partner),
            partner,
        )

    @staticmethod
    def assert_direct_staff_activity_allowed(school, catalogue_item, **kwargs) -> None:
        """Refuse, in the drawer's own words, what the policy does not allow.

        Called by ``apps.activities.services.create`` for every staff-delivered
        school activity, so a crafted POST or an API client meets the same rule
        the drawer shows.
        """
        from apps.core.exceptions import BadRequest

        if kwargs.get("delivery_channel", "staff") != "staff":
            return  # Partner delivery runs the Partner workflow, not this rule.
        result = PartnerSupportedSchoolPlanningPolicy.evaluate(
            school, catalogue_item, **kwargs
        )
        if not result.allowed:
            raise BadRequest(result.reason or "This activity cannot be planned here.")


def _may(principal, permission_name: str) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return has_permission(principal, getattr(Permission, permission_name).value)


def assert_cluster_invitations_allowed(school_ids, principal) -> None:
    """Inviting a Partner-supported school to a group session needs the grant.

    Free for everyone who holds it — the usual case, and no query is spent —
    and a single query otherwise, to learn whether any invited school is
    Partner-supported at all.
    """
    from apps.core.exceptions import Forbidden
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import (
        active_assignment_q,
        visibility_enabled,
    )

    if not school_ids or principal is None or not visibility_enabled(principal):
        return
    if _may(principal, "PARTNER_SCHOOL_CLUSTER_PLAN"):
        return
    if (
        PartnerAssignment.objects.filter(school_id__in=list(school_ids))
        .filter(active_assignment_q())
        .exists()
    ):
        raise Forbidden(
            "Your role does not invite Partner-supported schools to cluster "
            "sessions."
        )


def partner_supported_members(school_ids, principal=None) -> dict[str, str]:
    """Which of these cluster members a Partner supports, and by whom.

    One query. The cluster drawers use it to leave those schools unticked on
    first open: a Partner-supported school joins a Cluster Meeting or Group
    Training because a planner ticked it by name, never because it is in the
    cluster (owner, 2026-09-23).
    """
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import (
        active_assignment_q,
        visibility_enabled,
    )

    ids = [i for i in school_ids if i]
    if not ids or not visibility_enabled(principal):
        return {}
    out: dict[str, str] = {}
    for school_id, name in (
        PartnerAssignment.objects.filter(school_id__in=ids)
        .filter(active_assignment_q())
        .order_by("created_at")
        .values_list("school_id", "partner__name")
    ):
        if school_id in out and out[school_id] != name:
            out[school_id] = "Multiple Partners"
        else:
            out.setdefault(school_id, name)
    return out


def allowed_workflow_kinds() -> set[str]:
    """The workflow kinds the whitelisted catalogue items carry, one query.

    Read from the live catalogue rather than restated, so a governed item's
    kind is the one place it is written down.
    """
    from apps.activity_catalogue.models import ActivityCatalogueItem

    return set(
        ActivityCatalogueItem.objects.filter(
            stable_code__in=DIRECT_STAFF_ACTIVITY_CODES
        ).values_list("workflow_kind", flat=True)
    )


def allowed_direct_purposes() -> list[str]:
    """Planning-drawer purposes that resolve to a whitelisted catalogue item."""
    from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES

    kinds = allowed_workflow_kinds()
    return [
        purpose for purpose, kind in PURPOSE_ACTIVITY_TYPES.items() if kind in kinds
    ]


__all__ = [
    "CLUSTER_ACTIVITY_CODES",
    "CLUSTER_WORKFLOW_KINDS",
    "DIRECT_STAFF_ACTIVITY_CODES",
    "ORIGIN_CLUSTER",
    "ORIGIN_CORE",
    "ORIGIN_PROJECT",
    "ORIGIN_SCHOOL",
    "PartnerSupportedSchoolPlanningPolicy",
    "PlanningDecision",
    "PolicyResult",
    "allowed_direct_purposes",
    "assert_cluster_invitations_allowed",
    "partner_supported_members",
    "allowed_workflow_kinds",
    "restriction_message",
]
