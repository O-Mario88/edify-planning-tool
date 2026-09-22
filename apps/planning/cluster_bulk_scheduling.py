"""One day, one purpose, five or more of a cluster's schools.

Owner, 2026-09-21:

  "Allow the users to bulk schedule school visits in cluster by using the
  checkbox but they can only mark a minimum of 5 schools per day and that
  should only happen from cluster. They should be able to do so ONLY IF they
  are doing training follow up, SSA Support, Donor Visit, Content/Story
  Collection. In-School Training CANNOT be scheduled from bulk scheduling."

Three rules, and all three live here rather than in the drawer:

* **A cluster, and only a cluster.** The schools are resolved from live
  cluster membership, not from whatever ids the browser posted. The Planning
  page's own bulk Schedule is retired to this surface
  (:mod:`apps.frontend.views.planning_views`), so there is one place a day of
  visits is planned and one set of rules it obeys.
* **Five schools or none.** Fewer than five is an ordinary day and belongs in
  the per-school drawer, where the purpose and the focus are chosen for that
  school deliberately. The floor is ``CLUSTER_BULK_MINIMUM_SCHOOLS``.
* **Four purposes.** Training Follow Up, SSA Support, Donor Visit and
  Content/Story Collection — the support that is the same errand at every
  school on the route. In-school Training is refused by name, because it
  pairs a governed course with a companion visit and the course is a
  per-school choice.

Nothing here writes an Activity itself: every school goes through
``schedule_school_visit`` — the same canonical service the per-school drawer
calls — so costing, the calendar gate, the visit entitlement, the duplicate
guard and the daily visit batch all behave exactly as they do for one visit.
The whole selection is one transaction: a day that cannot be planned for one
of its schools is not half-planned for the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.partners.purposes import (
    CLUSTER_BULK_MINIMUM_SCHOOLS,
    CLUSTER_BULK_VISIT_PURPOSES,
    normalise_cluster_bulk_purpose,
    purpose_activity_type,
    visit_purpose_label,
)

__all__ = [
    "CLUSTER_BULK_MINIMUM_SCHOOLS",
    "CLUSTER_BULK_VISIT_PURPOSES",
    "BulkMember",
    "BulkSelection",
    "bulk_schedule_cluster_visits",
    "schedulable_members",
]


@dataclass
class BulkMember:
    """One member school, and whether this day may name it."""

    id: str
    school_id: str
    name: str
    school_type_label: str
    selectable: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "schoolId": self.school_id,
            "name": self.name,
            "schoolTypeLabel": self.school_type_label,
            "selectable": self.selectable,
            "reason": self.reason,
        }


@dataclass
class BulkSelection:
    """What the drawer shows before anything is written."""

    cluster_id: str
    cluster_name: str
    members: list[BulkMember] = field(default_factory=list)
    minimum: int = CLUSTER_BULK_MINIMUM_SCHOOLS

    @property
    def selectable(self) -> list[BulkMember]:
        return [member for member in self.members if member.selectable]

    @property
    def enough_schools(self) -> bool:
        return len(self.selectable) >= self.minimum

    @property
    def shortfall_reason(self) -> str:
        """Why the drawer cannot be used yet, said before a press."""
        if self.enough_schools:
            return ""
        available = len(self.selectable)
        return (
            f"{self.cluster_name} has {available} school"
            f"{'' if available == 1 else 's'} open for a visit today, and a "
            f"bulk day needs {self.minimum}. Schedule these from each "
            f"school's own row instead."
        )


def _cluster_for(cluster_id: str, principal):
    """The cluster this planner may plan FROM — the direct lens, not oversight.

    `get_operational_cluster_or_404` is the write-side question every
    scheduling drawer already asks, so a supervisor who can watch a cluster
    cannot bulk-plan its schools from it.
    """
    from apps.core.permissions import get_operational_cluster_or_404

    return get_operational_cluster_or_404(
        principal, id=cluster_id, deleted_at__isnull=True
    )


def schedulable_members(cluster, principal) -> BulkSelection:
    """The cluster's live members, each with the reason it may not be ticked.

    Membership is read from the School rows themselves — one definition,
    shared with ``apps.clusters.services.active_school_count`` — and every row
    is answered by the same visit gate the per-school Schedule button reads,
    so a school greyed out on one surface is greyed out here with the same
    sentence.
    """
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.core.scoping import direct_portfolio_schools, resolve_user_scope
    from apps.planning.visit_gate import visit_gates
    from apps.schools.models import School

    members = list(
        School.objects.filter(
            cluster_id=cluster.id,
            cluster_status="clustered",
            deleted_at__isnull=True,
            operational_status__in=OPERATING_STATUSES,
        )
        .select_related("district")
        .order_by("name")
    )
    if not members:
        return BulkSelection(cluster_id=cluster.id, cluster_name=cluster.name)

    scope = resolve_user_scope(principal)
    # Scheduling is the portfolio owner's, not a supervisor's — the same rule
    # activities.services.create applies, asked here so the drawer greys the
    # row rather than refusing it on submit.
    if scope.country_scope:
        writable_ids = {school.id for school in members}
    else:
        writable = direct_portfolio_schools(scope)
        writable_ids = (
            set(
                writable.filter(id__in=[school.id for school in members]).values_list(
                    "id", flat=True
                )
            )
            if writable is not None
            else set()
        )

    gates = visit_gates(members)
    rows = []
    for school in members:
        gate = gates[school.id]
        if school.id not in writable_ids:
            selectable, reason = (
                False,
                f"{school.name} is not in your own portfolio. Its owner plans "
                "its visits.",
            )
        elif gate.staff_locked:
            selectable, reason = False, gate.staff_locked_reason
        else:
            selectable, reason = True, ""
        rows.append(
            BulkMember(
                id=school.id,
                school_id=school.school_id,
                name=school.name,
                school_type_label=school.get_school_type_display(),
                selectable=selectable,
                reason=reason,
            )
        )
    return BulkSelection(cluster_id=cluster.id, cluster_name=cluster.name, members=rows)


def _parse_date(raw) -> date:
    if not raw:
        raise BadRequest("Pick the day these visits are planned for.")
    try:
        return date.fromisoformat(str(raw).strip()[:10])
    except ValueError as exc:
        raise BadRequest("That visit date is not a valid calendar date.") from exc


def _assert_follow_up_is_plannable_in_bulk(purpose: str, fy: str) -> None:
    """A country that requires a prior training cannot bulk-plan follow-ups.

    The source session is a per-school fact, so where the policy demands one
    there is nothing a single day-wide choice could name. Say that, rather
    than letting the first school's refusal stand for the whole selection.
    """
    if purpose != "training_follow_up":
        return
    from apps.planning.fy_policy import follow_up_requires_prior_training

    if follow_up_requires_prior_training(fy):
        raise BadRequest(
            "This fiscal year requires each follow-up visit to name the "
            "training it follows up, which is a per-school choice. Schedule "
            "these from each school's own Schedule drawer."
        )


@transaction.atomic
def bulk_schedule_cluster_visits(cluster_id: str, data: dict, principal) -> dict:
    """Plan one purpose, on one day, at every school the planner ticked.

    Returns ``{"created": [activity ids], "schools": n, "purpose": ...}``.
    Raises ``BadRequest`` with the sentence to show the planner; nothing is
    written when it does.
    """
    from apps.core.fy import get_operational_fy
    from apps.planning.services import schedule_school_visit

    cluster = _cluster_for(cluster_id, principal)
    purpose = normalise_cluster_bulk_purpose(data.get("purposeOfVisit"))
    when = _parse_date(data.get("scheduledDate"))
    fy = get_operational_fy(when)
    _assert_follow_up_is_plannable_in_bulk(purpose, fy)

    requested = [
        str(value).strip()
        for value in (data.get("schoolIds") or [])
        if str(value).strip()
    ]
    requested = list(dict.fromkeys(requested))
    if len(requested) < CLUSTER_BULK_MINIMUM_SCHOOLS:
        raise BadRequest(
            f"Tick at least {CLUSTER_BULK_MINIMUM_SCHOOLS} schools for one "
            f"day. You ticked {len(requested)}; fewer than "
            f"{CLUSTER_BULK_MINIMUM_SCHOOLS} is an ordinary day and is "
            "scheduled from each school's own row."
        )

    selection = schedulable_members(cluster, principal)
    by_id = {member.id: member for member in selection.members}
    by_school_id = {member.school_id: member for member in selection.members}
    chosen: list[BulkMember] = []
    for value in requested:
        member = by_id.get(value) or by_school_id.get(value)
        if member is None:
            raise BadRequest(
                "One of the schools ticked is no longer a member of "
                f"{cluster.name}. Reopen the drawer and tick the day again."
            )
        if not member.selectable:
            raise BadRequest(member.reason)
        chosen.append(member)

    # Ticked twice under two ids is still one school; count what will be
    # written, because that is what the floor is about.
    chosen = list({member.id: member for member in chosen}.values())
    if len(chosen) < CLUSTER_BULK_MINIMUM_SCHOOLS:
        raise BadRequest(
            f"Tick at least {CLUSTER_BULK_MINIMUM_SCHOOLS} different schools "
            "for one day."
        )

    label = visit_purpose_label(purpose, purpose)
    activity_type = purpose_activity_type(purpose)
    # One purpose for the whole day means one costing for the whole day, so
    # it is resolved once rather than per school.
    catalogue_item_id = _catalogue_item_id(activity_type, label)
    created: list[str] = []
    for member in chosen:
        payload = {
            "schoolId": member.school_id,
            "activityType": activity_type,
            "purposeType": purpose,
            "scheduledDate": when.isoformat(),
            "plannedMonth": when.month,
            "plannedWeek": min(5, (when.day - 1) // 7 + 1),
            "deliveryType": "staff",
            "requireCatalogue": True,
            "catalogueItemId": catalogue_item_id,
            "activityPurposeText": (
                data.get("activityPurposeText")
                or f"{label} for {cluster.name} cluster schools"
            ),
            "expectedOutcome": (
                data.get("expectedOutcome")
                or f"Complete the {label.lower()} and record its evidence."
            ),
            "recommendationReason": (
                f"Planned with {len(chosen)} {cluster.name} cluster schools "
                f"for {when.isoformat()}."
            ),
        }
        result = schedule_school_visit(payload, principal)
        created.append(result["id"])

    return {
        "created": created,
        "schools": len(created),
        "purpose": purpose,
        "purposeLabel": label,
        "scheduledDate": when.isoformat(),
        "clusterId": cluster.id,
        "clusterName": cluster.name,
    }


def _catalogue_item_id(activity_type: str, label: str) -> str:
    """The one approved Catalogue item that costs this purpose.

    Derived here rather than asked of the planner, exactly as the per-school
    drawer derives it: a bulk day names a purpose, and the purpose owns the
    costing. Where the catalogue offers no single answer, say which purpose
    could not be costed — that is a governance job for the Country Director,
    not something a field officer can fix in the drawer.
    """
    from apps.activity_catalogue.services import resolve_item_for_workflow_kind

    resolved = resolve_item_for_workflow_kind(activity_type)
    if resolved is None:
        raise BadRequest(
            f"No single approved Catalogue Activity costs “{label}”. "
            "Ask the Country Director to define one costing for it before "
            "scheduling this purpose."
        )
    return resolved.id
