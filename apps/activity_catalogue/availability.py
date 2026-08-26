"""§6 — the ONE service that answers "what may this user schedule here?".

Before this existed, every surface worked it out for itself: the school
drawer derived a purpose list from a hardcoded set of ActivityTypes, the
cluster drawer had its own, and the costing link was resolved separately
again at POST time. Three answers to one question, and the one that mattered
— can this be scheduled at all? — was only discovered on submit.

The rule it enforces is the corrected scheduling rule:

    Operational need
      → target SSA intervention or approved rationale
      → standard activity type
      → OPTIONAL project context
      → schedule

A Project is required only where the selected Activity's Workflow Profile
says ``requires_project``. Whether an intervention happens to be used by some
Project is not a scheduling question and is never consulted here.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.enums import (
    DeliveryType,
    ExecutorType,
    PARTNER_EXECUTOR_TYPES,
    SsaIntervention,
)

from .models import (
    ActivityCatalogueItem,
)
from .services import effective_items


#: The planning contexts a scheduling drawer can be opened in.
SCHOOL = "school"
CLUSTER = "cluster"
PROJECT = "project"
NON_SCHOOL = "non_school"

PLANNING_CONTEXTS = (SCHOOL, CLUSTER, PROJECT, NON_SCHOOL)


def _executor_filtered(qs, executor_type: str):
    if executor_type == ExecutorType.CERTIFIED_PARTNER_AGENCY:
        return qs.filter(
            partner_delivery_allowed=True,
            certified_agency_delivery_allowed=True,
        )
    if executor_type in PARTNER_EXECUTOR_TYPES:
        return qs.filter(partner_delivery_allowed=True)
    return qs.filter(staff_delivery_allowed=True)


def _context_filtered(qs, planning_context: str, *, cluster=None):
    if planning_context == CLUSTER or cluster is not None:
        return qs.filter(cluster_delivery_allowed=True)
    if planning_context == NON_SCHOOL:
        return qs.filter(non_school_allowed=True)
    return qs.filter(individual_school_allowed=True)


def available_catalogue_items(
    *,
    planning_context: str = SCHOOL,
    school=None,
    cluster=None,
    project=None,
    executor_type: str = DeliveryType.STAFF,
    intervention: str | None = None,
    on_date=None,
    standard_only: bool = False,
):
    """The effective Catalogue items schedulable in this exact context.

    ``project`` NARROWS the result to that Project's approved activities when
    supplied, because deliberately planning Project work means planning from
    the Project's approved list. Omitting it does not narrow anything and is
    the ordinary case — standard support has no Project and needs none.
    """
    on_date = on_date or timezone.localdate()
    qs = effective_items(on_date).prefetch_related(
        "intervention_mappings", "eligibility_rule"
    )
    qs = _executor_filtered(qs, executor_type)
    qs = _context_filtered(qs, planning_context, cluster=cluster)
    if standard_only:
        qs = qs.filter(standard_support=True)
    if project is not None:
        qs = qs.filter(
            project_mappings__project=project,
            project_mappings__active=True,
        )
    if intervention:
        # Standard support answers ANY intervention, so it is never filtered
        # out by one. Only the programme's named curriculum titles are keyed
        # to a specific intervention.
        from django.db.models import Q

        qs = qs.filter(
            Q(standard_support=True)
            | Q(
                intervention_mappings__intervention=intervention,
                intervention_mappings__active=True,
            )
        )
    return qs.distinct()


def available_activity_types(
    *,
    user=None,
    planning_context: str = SCHOOL,
    school=None,
    cluster=None,
    project=None,
    executor_type: str = DeliveryType.STAFF,
    intervention: str | None = None,
    on_date=None,
) -> list[dict]:
    """The activity types the user may schedule, each with its field profile.

    One row per (workflow kind), because that is the unit a planner chooses
    and the unit the CD Cost Catalogue prices. Standard support sorts first:
    it is the ordinary answer, and burying "School Visit" under twelve
    curriculum titles is what made planners believe a Project was required.
    """
    from .services import validate_context

    items = available_catalogue_items(
        planning_context=planning_context,
        school=school,
        cluster=cluster,
        project=project,
        executor_type=executor_type,
        intervention=intervention,
        on_date=on_date,
    )
    rows: dict[str, dict] = {}
    for item in items:
        try:
            validate_context(
                item,
                school=school,
                cluster=cluster,
                project=project,
                executor_type=executor_type,
                non_school=planning_context == NON_SCHOOL,
            )
        except Exception:  # noqa: BLE001 — ineligible here is not an error
            continue
        existing = rows.get(item.workflow_kind)
        # One row per kind, and the standard item owns the kind when present:
        # it is the one whose profile the drawer must be generated from.
        if existing is not None and not item.standard_support:
            continue
        rows[item.workflow_kind] = {
            **item.workflow_profile(),
            "label": item.display_name,
            "description": item.description,
        }
    return sorted(
        rows.values(),
        key=lambda row: (not row["standardSupport"], row["label"].casefold()),
    )


def workflow_profile_for(
    workflow_kind: str, *, on_date=None
) -> ActivityCatalogueItem | None:
    """The Catalogue item whose Workflow Profile governs this activity type."""
    from .services import resolve_item_for_workflow_kind

    return resolve_item_for_workflow_kind(workflow_kind, on_date=on_date)


def training_activity_options(
    *,
    planning_context: str,
    school=None,
    cluster=None,
    executor_type: str = DeliveryType.STAFF,
    on_date=None,
) -> list[dict]:
    """Return the governed 21-course Training Catalogue for this context.

    The training is the user's decision; category and SSA association are
    governed metadata fetched from that decision.  Priority rules remain in
    the payload for traceability and reporting, but they do not hide an
    approved course from the Training dropdown.

    The option payload still carries delivery permissions.  Alpine uses them
    to keep the list honest when the planner switches between Staff and a
    Certified Partner Agency, and :func:`apps.activities.services.create`
    repeats every check server-side before anything is saved.
    """
    if planning_context not in {SCHOOL, CLUSTER}:
        raise ValueError("Training activity options require School or Cluster context.")

    from django.db.models import Prefetch

    from apps.hr.models import MilestoneActivityRule

    priority_rules = MilestoneActivityRule.objects.filter(active=True).select_related(
        "milestone__priority"
    )
    items = effective_items(on_date).filter(
        is_training_course=True,
        **(
            {"cluster_delivery_allowed": True}
            if planning_context == CLUSTER
            else {"individual_school_allowed": True}
        ),
    )
    items = _executor_filtered(items, executor_type)
    items = (
        items
        .prefetch_related(
            "intervention_mappings",
            Prefetch(
                "milestone_rules",
                queryset=priority_rules,
                to_attr="active_priority_rules",
            ),
        )
        .distinct()
        .order_by("display_name", "stable_code")
    )

    options = []
    for item in items:
        if school is not None or cluster is not None:
            from .services import validate_context

            try:
                validate_context(
                    item,
                    school=school,
                    cluster=cluster,
                    project=None,
                    executor_type=executor_type,
                )
            except Exception:  # noqa: BLE001 — unavailable here is not an error
                continue
        mappings = [
            mapping for mapping in item.intervention_mappings.all() if mapping.active
        ]
        primary_mapping = next(
            (mapping for mapping in mappings if mapping.is_primary),
            mappings[0] if mappings else None,
        )
        ssa_intervention = (
            primary_mapping.intervention if primary_mapping else None
        )
        interventions = [ssa_intervention] if ssa_intervention else []
        options.append(
            {
                "id": str(item.id),
                "label": item.display_name,
                "stableCode": item.stable_code,
                "interventions": interventions,
                "ssaIntervention": ssa_intervention or "",
                "ssaInterventionLabel": (
                    SsaIntervention(ssa_intervention).label
                    if ssa_intervention
                    else "Not SSA-scored"
                ),
                "category": item.training_category,
                "ssaIndicator": item.ssa_indicator_label,
                "standardSupport": item.standard_support,
                "staffDeliveryAllowed": item.staff_delivery_allowed,
                "partnerDeliveryAllowed": item.partner_delivery_allowed,
                "certifiedAgencyDeliveryAllowed": (
                    item.partner_delivery_allowed
                    and item.certified_agency_delivery_allowed
                ),
                "priorityTitles": sorted(
                    {rule.milestone.title for rule in item.active_priority_rules}
                ),
            }
        )
    return sorted(
        options,
        key=lambda option: (
            not option["standardSupport"],
            option["label"].casefold(),
            option["stableCode"],
        ),
    )


def validate_priority_training_selection(
    item_id: str,
    *,
    planning_context: str,
    intervention: str | None = None,
    on_date=None,
) -> dict:
    """Return one governed course or reject a forged/stale selection.

    ``intervention`` remains accepted for legacy API callers, but it can only
    confirm the catalogue mapping.  New forms do not ask for it: the selected
    course supplies it automatically.
    """
    from apps.core.exceptions import BadRequest

    selected = next(
        (
            option
            for option in training_activity_options(
                planning_context=planning_context,
                on_date=on_date,
            )
            if option["id"] == str(item_id)
        ),
        None,
    )
    if selected is None:
        raise BadRequest(
            "Select a training from the governed Training Catalogue."
        )
    if intervention and intervention != selected["ssaIntervention"]:
        raise BadRequest(
            "The submitted SSA intervention does not match the selected "
            "Training Catalogue course."
        )
    return selected


__all__ = [
    "CLUSTER",
    "NON_SCHOOL",
    "PLANNING_CONTEXTS",
    "PROJECT",
    "SCHOOL",
    "available_activity_types",
    "available_catalogue_items",
    "training_activity_options",
    "validate_priority_training_selection",
    "workflow_profile_for",
]
