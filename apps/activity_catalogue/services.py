from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.core.enums import (
    ActivityStatus,
    DeliveryType,
    ExecutorType,
    PARTNER_EXECUTOR_TYPES,
    SsaIntervention,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy

from .models import (
    ActivityCatalogueItem,
    ActivityCatalogueVersion,
    ActivityProjectMapping,
    CatalogueActivityType,
    CatalogueStatus,
    MappingMode,
)


ACTIVE_SUPPORT_STATUSES = [
    ActivityStatus.PLANNED,
    ActivityStatus.SCHEDULED,
    ActivityStatus.ASSIGNED_TO_PARTNER,
    ActivityStatus.PARTNER_SCHEDULED,
    ActivityStatus.IN_PROGRESS,
    ActivityStatus.COMPLETION_STARTED,
    ActivityStatus.EVIDENCE_UPLOADED,
    ActivityStatus.EVIDENCE_ACCEPTED,
    ActivityStatus.SALESFORCE_ID_REQUIRED,
    ActivityStatus.SUBMITTED_TO_PL,
    ActivityStatus.AWAITING_IA_VERIFICATION,
]
COMPLETED_SUPPORT_STATUSES = [
    ActivityStatus.COMPLETED,
    ActivityStatus.IA_VERIFIED,
    ActivityStatus.ACCOUNTANT_CONFIRMED,
    ActivityStatus.CLOSED,
]


def effective_items(on_date=None):
    on_date = on_date or timezone.localdate()
    return ActivityCatalogueItem.objects.filter(
        status=CatalogueStatus.ACTIVE,
    ).filter(
        Q(effective_from__isnull=True) | Q(effective_from__lte=on_date),
        Q(effective_to__isnull=True) | Q(effective_to__gte=on_date),
    )


def resolve_assignment_item(*, purpose_of_visit=None, expected_activity_type=None):
    """The approved Catalogue Activity is the ASSIGNER's decision, recorded on
    the assignment — the partner never chooses one at scheduling. When an
    assignment flow hands work over without an explicit pick, the
    standard-support item matching the recorded purpose (or activity type) IS
    that decision, because purpose→type→standard item is one-to-one. Returns
    None when nothing matches, which the caller must surface as a repair."""
    from apps.partners.purposes import purpose_activity_type

    kinds = []
    if purpose_of_visit:
        kinds.append(purpose_activity_type(purpose_of_visit, fallback=""))
    if expected_activity_type:
        kinds.append(expected_activity_type)
    for kind in [k for k in kinds if k]:
        item = (
            effective_items()
            .filter(
                partner_delivery_allowed=True,
                standard_support=True,
                workflow_kind=kind,
            )
            .first()
        )
        if item:
            return item
    return None


def get_selectable_item(item_id_or_code: str, *, on_date=None) -> ActivityCatalogueItem:
    item = (
        effective_items(on_date)
        .prefetch_related("intervention_mappings", "versions")
        .filter(Q(id=item_id_or_code) | Q(stable_code=item_id_or_code))
        .first()
    )
    if not item:
        raise BadRequest(
            "The selected Activity Catalogue item is inactive, retired, outside "
            "its effective dates, or does not exist."
        )
    return item


def resolve_item_for_workflow_kind(
    workflow_kind: str, *, on_date=None
) -> ActivityCatalogueItem | None:
    """The effective catalogue item that costs a given activity type.

    The scheduling drawer asks for a PURPOSE OF VISIT, not a catalogue entry.
    A field officer knows they are going to collect SSA or follow up a
    training; asking them which catalogue row funds that is asking them to do
    the finance system's filing. The purpose maps to an activity type
    (PURPOSE_ACTIVITY_TYPES), and the activity type is what the catalogue
    already keys its costing on — so the link is derivable and does not need
    to be a question.

    The STANDARD-SUPPORT item for a kind wins outright when one exists. That
    is what it is for: an in-school training has five governed curriculum
    titles costing it (EdTech Foundations, CC-SEL, …), and "more than one, so
    refuse" meant a planner choosing the purpose "In-school Training" was told
    no approved activity costs it — while five did. The standard item is the
    unnamed, general-purpose response, and the database allows exactly one
    active one per kind, so this is a resolution rather than a guess.

    Returns None rather than guessing when the catalogue offers several
    non-standard items and no standard one: two costings for one purpose is a
    governance question for the Country Director, and silently picking the
    first would put money against an activity nobody chose.
    """
    if not workflow_kind:
        return None
    standard = list(
        effective_items(on_date)
        .filter(workflow_kind=workflow_kind, standard_support=True)
        .order_by("stable_code")[:2]
    )
    if len(standard) == 1:
        return standard[0]
    matches = list(
        effective_items(on_date)
        .filter(workflow_kind=workflow_kind)
        .order_by("stable_code")[:2]
    )
    return matches[0] if len(matches) == 1 else None


def _latest_version(item: ActivityCatalogueItem) -> ActivityCatalogueVersion:
    version = item.versions.order_by("-version").first()
    if version:
        return version
    return ActivityCatalogueVersion.objects.create(
        catalogue_item=item,
        version=1,
        snapshot=item.snapshot(),
        change_reason="Version established when first scheduled.",
        created_by="system",
    )


def _mapping(item: ActivityCatalogueItem):
    return item.intervention_mappings.filter(active=True).order_by(
        "-is_primary", "priority", "id"
    )


def resolve_activity_intervention(
    item: ActivityCatalogueItem,
    *,
    requested_intervention: str | None,
    source_activity=None,
) -> str | None:
    mappings = list(_mapping(item))
    if not mappings:
        raise BadRequest("This Catalogue item has no active intervention mapping.")
    mode = mappings[0].mapping_mode
    if mode == MappingMode.ANY_SSA_INTERVENTION:
        # Standard support belongs to no single intervention. The planner
        # names the one the work is meant to move, and the catalogue does not
        # second-guess it — but it must still be one of the canonical eight,
        # because everything downstream (intervention analytics, the SSA
        # lineage stamped in apply_catalogue_snapshot) is keyed on them.
        if not requested_intervention:
            return None
        if requested_intervention not in SsaIntervention.values:
            raise BadRequest("Choose a valid canonical SSA intervention.")
        return requested_intervention
    if mode in {
        MappingMode.SSA_COMPLETION_PREREQUISITE,
        MappingMode.ADMINISTRATIVE,
    }:
        if requested_intervention:
            raise BadRequest(
                "SSA Completion and administrative Activities cannot be recorded "
                "as intervention support."
            )
        return None
    if mode == MappingMode.INHERIT_FROM_SOURCE_ACTIVITY:
        if source_activity:
            inherited = (
                source_activity.focus_intervention
                or source_activity.purpose_intervention
            )
            if not inherited:
                raise BadRequest(
                    "The selected source Activity has no intervention to inherit. "
                    "Choose a valid source Training or ask IA to repair its mapping."
                )
            return inherited
        if requested_intervention in SsaIntervention.values:
            return requested_intervention
        if not requested_intervention:
            raise BadRequest(
                "Choose the Training or support Activity being followed up, or "
                "select one current unresolved SSA intervention."
            )
        raise BadRequest("Choose a valid canonical SSA intervention.")
    allowed = {m.intervention for m in mappings if m.intervention}
    if requested_intervention and requested_intervention not in allowed:
        raise BadRequest(
            "The selected Activity is not approved for that SSA intervention."
        )
    if requested_intervention:
        return requested_intervention
    primary = next((m.intervention for m in mappings if m.is_primary), None)
    return primary or next(iter(sorted(allowed)), None)


def validate_context(
    item: ActivityCatalogueItem,
    *,
    school=None,
    cluster=None,
    project=None,
    executor_type: str,
    non_school: bool = False,
) -> None:
    """Validate the delivery context of a Catalogue selection.

    ``non_school=True`` is the Work Plan's central-planning context: a
    Group-delivered camp or conference is being planned as one dated
    programme activity at a venue rather than school by school. The item must
    still be approved for it (``non_school_allowed``); the per-school
    requirements below then do not apply, because there is no school to which
    they could refer.

    A Project is required ONLY where ``item.requires_project`` says so (§2).
    There is no rule anywhere in this function that a selected intervention
    must belong to a Project, and there must never be one: an intervention
    may inform a Project, but a Project does not own it.
    """
    executor_type = executor_type or DeliveryType.STAFF
    is_partner_delivery = executor_type in PARTNER_EXECUTOR_TYPES
    if executor_type == ExecutorType.CERTIFIED_PARTNER_AGENCY:
        if not item.certified_agency_delivery_allowed:
            raise Forbidden(
                "This Catalogue Activity is not approved for Certified "
                "Partner Agency delivery."
            )
        if not item.partner_delivery_allowed:
            raise Forbidden(
                "This Catalogue Activity is not approved for Partner delivery."
            )
    if non_school:
        if not item.non_school_allowed:
            raise BadRequest(
                "This Catalogue Activity is delivered through School or "
                "Cluster planning and cannot be planned as a standalone "
                "programme activity."
            )
        if is_partner_delivery and not item.partner_delivery_allowed:
            raise Forbidden(
                "This Catalogue Activity is not approved for Partner delivery."
            )
        if executor_type == DeliveryType.STAFF and not item.staff_delivery_allowed:
            raise Forbidden(
                "This Catalogue Activity is not approved for Staff delivery."
            )
        if item.requires_project and project is None:
            raise BadRequest("This Catalogue Activity requires a Special Project.")
        return
    if item.requires_school and school is None:
        raise BadRequest("This Catalogue Activity requires a School.")
    if item.requires_cluster and cluster is None:
        raise BadRequest("This Catalogue Activity requires a Cluster.")
    if item.requires_project and project is None:
        raise BadRequest("This Catalogue Activity requires a Special Project.")
    if school and cluster is None and not item.individual_school_allowed:
        raise BadRequest(
            "This Catalogue Activity is not approved for individual Schools."
        )
    if cluster and not item.cluster_delivery_allowed:
        raise BadRequest(
            "This Catalogue Activity is not approved for Cluster delivery."
        )
    if is_partner_delivery and not item.partner_delivery_allowed:
        raise Forbidden("This Catalogue Activity is not approved for Partner delivery.")
    if executor_type == DeliveryType.STAFF and not item.staff_delivery_allowed:
        raise Forbidden("This Catalogue Activity is not approved for Staff delivery.")

    rule = getattr(item, "eligibility_rule", None)
    if school and rule:
        school_type = getattr(school, "school_type", None)
        school_level = getattr(school, "school_level", None)
        if rule.eligible_school_categories and school_type not in set(
            rule.eligible_school_categories
        ):
            raise BadRequest(
                "This Catalogue Activity is not eligible for this School type."
            )
        if rule.eligible_school_levels and school_level not in set(
            rule.eligible_school_levels
        ):
            raise BadRequest(
                "This Catalogue Activity is not eligible for this School level."
            )
        if rule.core_school_only and school_type != "core":
            raise BadRequest("This Catalogue Activity is restricted to Core Schools.")
        if rule.client_school_only and school_type != "client":
            raise BadRequest("This Catalogue Activity is restricted to Client Schools.")
        if rule.requires_cluster_membership and not getattr(school, "cluster_id", None):
            raise BadRequest("This Catalogue Activity requires Cluster membership.")
    if item.new_school_only and school:
        fy = get_operational_fy()
        created_fy = (
            get_operational_fy(school.created_at) if school.created_at else None
        )
        if created_fy != fy:
            raise BadRequest("New School Orientation is available only to new Schools.")

    if project:
        mapping = ActivityProjectMapping.objects.filter(
            project=project,
            catalogue_item=item,
            active=True,
        ).first()
        # The approved-activity list governs which of the programme's NAMED
        # curriculum titles a Project funds — EdTech Foundations belongs to
        # the EdTech project and not to Literacy, and that is a real rule.
        #
        # It says nothing useful about ordinary support. A Literacy project
        # running a cluster training is running a cluster training; requiring
        # someone to first map "Cluster Training" into all five projects adds
        # a setup step whose only outcome is that scheduling fails until it
        # is done. Here the Project is attribution, not a menu.
        if not mapping and not item.standard_support:
            raise BadRequest(
                "This Activity is not approved in the selected Special Project."
            )
        if not mapping:
            return
        if is_partner_delivery and not mapping.partner_delivery_allowed:
            raise Forbidden(
                "The Project does not allow Partner delivery for this Activity."
            )
        if executor_type == DeliveryType.STAFF and not mapping.staff_delivery_allowed:
            raise Forbidden(
                "The Project does not allow Staff delivery for this Activity."
            )


def validate_frequency(
    item,
    *,
    school=None,
    cluster=None,
    fy=None,
    on_date=None,
):
    rule = getattr(item, "eligibility_rule", None)
    if not rule or item.core_slot_type:
        return
    from apps.activities.models import Activity

    target = Q(school=school) if school is not None else Q(cluster=cluster)
    live = Activity.objects.filter(
        target,
        catalogue_item=item,
        deleted_at__isnull=True,
    ).exclude(status__in=["cancelled", "rejected", "deferred"])
    if fy:
        live = live.filter(fy=fy)
    if (
        rule.maximum_frequency_per_fy is not None
        and live.count() >= rule.maximum_frequency_per_fy
    ):
        raise BadRequest(
            "This Catalogue Activity has reached its approved frequency for "
            "the target in this financial year."
        )
    if rule.cooldown_days:
        latest = (
            live.filter(status__in=COMPLETED_SUPPORT_STATUSES)
            .exclude(planned_date__isnull=True)
            .order_by("-planned_date")
            .values_list("planned_date", flat=True)
            .first()
        )
        if latest and (on_date or timezone.localdate()) < latest + timedelta(
            days=rule.cooldown_days
        ):
            raise BadRequest(
                "This Catalogue Activity is still inside its approved cooldown period."
            )


@transaction.atomic
def apply_catalogue_snapshot(
    activity,
    *,
    item: ActivityCatalogueItem,
    source_ssa=None,
    recommendation_reason: str = "",
    requested_intervention: str | None = None,
    source_activity=None,
    override_reason: str = "",
    recommendation_source: dict | None = None,
):
    """Stamp governed metadata onto a canonical Activity exactly once."""

    intervention = resolve_activity_intervention(
        item,
        requested_intervention=requested_intervention,
        source_activity=source_activity,
    )
    version = _latest_version(item)
    activity.catalogue_item = item
    activity.catalogue_version = version.version
    activity.activity_name_snapshot = item.display_name
    activity.activity_type_snapshot = item.activity_type
    activity.delivery_method_snapshot = item.delivery_method
    activity.evidence_profile_snapshot = item.evidence_profile
    activity.salesforce_record_type_snapshot = item.salesforce_record_type
    activity.salesforce_activity_type = (
        "training"
        if item.salesforce_record_type == "TRAINING"
        else "visit"
        if item.salesforce_record_type == "VISIT"
        else None
    )
    activity.costing_profile_snapshot = item.costing_profile
    activity.recommendation_reason = recommendation_reason or ""
    activity.recommendation_source = recommendation_source or {}
    activity.follow_up_of_activity = source_activity
    activity.override_reason = override_reason or ""
    activity.focus_intervention = intervention
    activity.purpose_intervention = intervention
    if source_activity:
        activity.secondary_focus_interventions = list(
            source_activity.secondary_focus_interventions or []
        )
        if source_ssa is None and source_activity.source_ssa_id:
            source_ssa = source_activity.source_ssa
        activity.recommendation_source = {
            **(source_activity.recommendation_source or {}),
            **(recommendation_source or {}),
            "inheritedFromActivityId": source_activity.id,
        }
    if source_ssa:
        activity.source_ssa = source_ssa
        activity.source_ssa_verification_state = source_ssa.verification_status
        score = next(
            (
                score.score
                for score in source_ssa.scores.all()
                if score.intervention == intervention
            ),
            None,
        )
        activity.source_score = score
        if score is not None:
            from apps.core.enums import ssa_score_band

            activity.source_classification = ssa_score_band(float(score))[0]
    activity.save(
        update_fields=[
            "catalogue_item",
            "catalogue_version",
            "activity_name_snapshot",
            "activity_type_snapshot",
            "delivery_method_snapshot",
            "evidence_profile_snapshot",
            "salesforce_record_type_snapshot",
            "salesforce_activity_type",
            "costing_profile_snapshot",
            "recommendation_reason",
            "recommendation_source",
            "follow_up_of_activity",
            "override_reason",
            "focus_intervention",
            "purpose_intervention",
            "secondary_focus_interventions",
            "source_ssa",
            "source_ssa_verification_state",
            "source_score",
            "source_classification",
            "updated_at",
        ]
    )
    return activity


def list_catalogue(
    *,
    intervention: str | None = None,
    activity_type: str | None = None,
    delivery_method: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
):
    qs = ActivityCatalogueItem.objects.all()
    if not include_inactive:
        qs = effective_items()
    if intervention:
        qs = qs.filter(
            intervention_mappings__intervention=intervention,
            intervention_mappings__active=True,
        )
    if activity_type:
        qs = qs.filter(activity_type=activity_type)
    if delivery_method:
        qs = qs.filter(delivery_method=delivery_method)
    if status:
        qs = qs.filter(status=status)
    if project_id:
        qs = qs.filter(
            project_mappings__project_id=project_id,
            project_mappings__active=True,
        )
    return qs.prefetch_related("intervention_mappings").distinct()


def serialize_item(item: ActivityCatalogueItem) -> dict:
    mappings = list(item.intervention_mappings.all())
    return {
        "id": item.id,
        "stableCode": item.stable_code,
        "sourceName": item.source_name,
        "displayName": item.display_name,
        "description": item.description,
        "activityType": item.activity_type,
        "deliveryMethod": item.delivery_method,
        "workflowKind": item.workflow_kind,
        "targetAudience": item.target_audience,
        "status": item.status,
        "staffDeliveryAllowed": item.staff_delivery_allowed,
        "partnerDeliveryAllowed": item.partner_delivery_allowed,
        "individualSchoolAllowed": item.individual_school_allowed,
        "clusterDeliveryAllowed": item.cluster_delivery_allowed,
        "projectDeliveryAllowed": item.project_delivery_allowed,
        "evidenceProfile": item.evidence_profile,
        "salesforceRecordType": item.salesforce_record_type,
        "salesforceExpectedPrefix": item.salesforce_expected_prefix,
        "costingProfile": item.costing_profile,
        "supportObjective": item.support_objective,
        "interventions": [
            {
                "intervention": mapping.intervention,
                "mode": mapping.mapping_mode,
                "primary": mapping.is_primary,
            }
            for mapping in mappings
            if mapping.active
        ],
    }


def _project_from_context(project):
    if not project:
        return None
    if hasattr(project, "pk"):
        return project
    from apps.projects.models import Project

    return Project.objects.filter(id=project, deleted_at__isnull=True).first()


def recommend_activities(
    *,
    school,
    principal=None,
    project=None,
    cluster=None,
    executor_type=DeliveryType.STAFF,
    limit=3,
) -> dict:
    """Return SSA-led, deterministically ranked eligible catalogue responses."""

    from apps.activities.models import Activity
    from apps.ssa.recommendation_engine import prioritized_interventions
    from apps.ssa.services import latest_applicable_record

    project = _project_from_context(project)
    source_ssa = latest_applicable_record(school)
    ranked_needs = prioritized_interventions(school)
    on_date = timezone.localdate()
    fy = get_operational_fy(on_date)

    qs = effective_items(on_date).prefetch_related(
        "intervention_mappings", "project_mappings", "eligibility_rule"
    )
    if executor_type == DeliveryType.PARTNER:
        qs = qs.filter(partner_delivery_allowed=True)
    else:
        qs = qs.filter(staff_delivery_allowed=True)
    if cluster is not None:
        qs = qs.filter(cluster_delivery_allowed=True)
    else:
        qs = qs.filter(individual_school_allowed=True)
    if project:
        qs = qs.filter(
            project_mappings__project=project,
            project_mappings__active=True,
        )

    active_conflicts = Activity.objects.filter(
        catalogue_item_id=OuterRef("pk"),
        school=school,
        fy=fy,
        deleted_at__isnull=True,
        status__in=ACTIVE_SUPPORT_STATUSES,
    )
    recent_completed = Activity.objects.filter(
        catalogue_item_id=OuterRef("pk"),
        school=school,
        deleted_at__isnull=True,
        status__in=COMPLETED_SUPPORT_STATUSES,
        scheduled_date__gte=timezone.now() - timedelta(days=180),
    )
    qs = qs.annotate(
        has_active_conflict=Exists(active_conflicts),
        delivered_recently=Exists(recent_completed),
    )

    if source_ssa is None or not ranked_needs:
        candidates = qs.filter(
            intervention_mappings__mapping_mode=MappingMode.SSA_COMPLETION_PREREQUISITE,
            intervention_mappings__active=True,
        ).distinct()
        reason = "No applicable verified SSA exists. Complete the SSA before intervention support is recommended."
        recommendations = [
            _suggestion(item, None, source_ssa, reason, rank=0)
            for item in candidates.order_by("display_name")
        ]
        return {
            "hasApplicableSsa": False,
            "sourceSsaId": None,
            "verificationState": "none",
            "priority": {
                "label": "Complete SSA",
                "classification": "Mandatory prerequisite",
            },
            "primary": recommendations[:limit],
            "otherEligible": recommendations[limit:],
        }

    rank_by_intervention = {
        need["intervention"]: index for index, need in enumerate(ranked_needs)
    }
    need_by_intervention = {need["intervention"]: need for need in ranked_needs}
    candidates = qs.filter(
        intervention_mappings__intervention__in=list(rank_by_intervention),
        intervention_mappings__mapping_mode__in=[
            MappingMode.FIXED,
            MappingMode.MULTIPLE_ALLOWED,
        ],
        intervention_mappings__active=True,
    ).exclude(activity_type=CatalogueActivityType.ADMIN)

    suggestions = []
    directly_addressed: set[str] = set()
    for item in candidates.distinct():
        try:
            validate_context(
                item,
                school=school,
                cluster=cluster,
                project=project,
                executor_type=executor_type,
            )
            validate_frequency(
                item,
                school=school,
                cluster=cluster,
                fy=fy,
                on_date=on_date,
            )
        except (BadRequest, Forbidden):
            continue
        mapping = min(
            (
                m
                for m in item.intervention_mappings.all()
                if m.active and m.intervention in rank_by_intervention
            ),
            key=lambda m: (
                rank_by_intervention[m.intervention],
                m.priority,
                m.intervention,
            ),
        )
        need = need_by_intervention[mapping.intervention]
        # Only a real intervention mapping counts as addressing a need. The
        # dynamic follow-ups below inherit ranked_needs[0]'s label when no
        # source activity exists, which would otherwise make any need look
        # answered by an activity that does nothing about it.
        directly_addressed.add(mapping.intervention)
        suggestions.append(
            _suggestion(
                item,
                mapping.intervention,
                source_ssa,
                f"{need['label']} is {need['band']} at {need['score']}/10.",
                rank=rank_by_intervention[mapping.intervention],
                need=need,
            )
        )

    # Dynamic follow-ups are never a source of need. They become eligible only
    # when a real prior support Activity supplies the intervention and lineage.
    followups = qs.filter(
        intervention_mappings__mapping_mode=MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
        intervention_mappings__active=True,
    ).distinct()
    for item in followups:
        try:
            validate_context(
                item,
                school=school,
                cluster=cluster,
                project=project,
                executor_type=executor_type,
            )
            validate_frequency(
                item,
                school=school,
                cluster=cluster,
                fy=fy,
                on_date=on_date,
            )
        except (BadRequest, Forbidden):
            continue
        source_query = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                status__in=COMPLETED_SUPPORT_STATUSES,
            )
            .exclude(focus_intervention__isnull=True)
            .exclude(focus_intervention="")
        )
        source_query = (
            source_query.filter(cluster=cluster)
            if cluster is not None
            else source_query.filter(school=school)
        )
        source_activity = source_query.order_by("-planned_date", "-created_at").first()
        if source_activity is not None:
            target_intervention = source_activity.focus_intervention
            need = need_by_intervention.get(target_intervention)
            reason = (
                f"Follow up {source_activity.activity_name_snapshot or source_activity.get_activity_type_display()} "
                f"and inherit its {target_intervention.replace('_', ' ').title()} intervention."
            )
            source_for_suggestion = source_activity.source_ssa or source_ssa
        else:
            need = ranked_needs[0]
            target_intervention = need["intervention"]
            reason = (
                f"No completed source support is available. Address the current "
                f"unresolved {need['label']} need at {need['score']}/10."
            )
            source_for_suggestion = source_ssa
        row = _suggestion(
            item,
            target_intervention,
            source_for_suggestion,
            reason,
            rank=(rank_by_intervention.get(target_intervention, 999) + 20),
            need=need,
        )
        if source_activity is not None:
            row["sourceActivityId"] = source_activity.id
        suggestions.append(row)

    suggestions.sort(
        key=lambda row: (
            row["rank"],
            row["existingSupportConflict"],
            row["deliveredRecently"],
            row["displayName"].casefold(),
            row["stableCode"],
        )
    )
    # The banner names the weakest intervention, but the catalogue may hold no
    # response that can be delivered in THIS context — five of the eight
    # interventions are currently answered only by cluster-level trainings, so
    # a single-school drawer silently fell through to the next-best need and
    # presented it as the recommendation. The score shown and the activity
    # offered then described different problems, which reads as the engine
    # ignoring the SSA.
    #
    # Nothing is hidden and nothing is invented: the lower-ranked activities
    # stay schedulable, and the unmet top need is stated with the reason its
    # own responses are unavailable, so the choice is the planner's.
    top_need = ranked_needs[0]
    unmet_priority = None
    # Standard field support answers ANY intervention, so its availability is
    # what decides whether the top need is actually unaddressable here or
    # merely has no NAMED curriculum title. Before standard support existed
    # those were the same thing, and the banner said "no activity addresses
    # this" when the honest statement was "no curriculum training does".
    standard_support_available = qs.filter(standard_support=True).exists()
    if top_need["intervention"] not in directly_addressed:
        blocked = []
        for item in (
            effective_items(on_date)
            .filter(
                intervention_mappings__intervention=top_need["intervention"],
                intervention_mappings__active=True,
            )
            .distinct()
        ):
            reasons = []
            if cluster is None and not item.individual_school_allowed:
                reasons.append("not delivered to a single school")
            if executor_type == DeliveryType.PARTNER:
                if not item.partner_delivery_allowed:
                    reasons.append("not approved for partner delivery")
            elif not item.staff_delivery_allowed:
                reasons.append("not approved for staff delivery")
            # Name the surface that CAN schedule it. School planning is for
            # visits and partner assignment; a programme activity is planned
            # centrally from the Work Plan as one dated event at a venue, and
            # draws its cost from the same CD Cost Catalogue either way. Saying
            # only "not available here" leaves the planner with a need they
            # cannot act on.
            # A complete short instruction, not a fragment: the third branch
            # is an ask of a person rather than a place to go, so a template
            # that prefixed "schedule from …" would read wrongly for it.
            if item.non_school_allowed:
                route = "schedule from the Work Plan page"
            elif item.cluster_delivery_allowed:
                route = "schedule through a cluster"
            else:
                route = "ask IA to review its catalogue delivery settings"
            blocked.append(
                {
                    "displayName": item.display_name,
                    "reason": " and ".join(reasons)
                    or "not eligible for this school right now",
                    "route": route,
                }
            )
        # Grouped by the (reason, route) they share. Every blocked title used
        # to be its own full sentence, so five titles blocked for the same
        # reason printed that reason five times — and the school's name with
        # it. The reason is a property of the delivery rule, not of the title,
        # so it is stated once and the titles are listed against it.
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in blocked:
            grouped.setdefault((row["reason"], row["route"]), []).append(
                row["displayName"]
            )
        blocked_groups = [
            {"reason": reason, "route": route, "names": sorted(names)}
            for (reason, route), names in sorted(grouped.items())
        ]
        unmet_priority = {
            "need": top_need,
            "blockedBy": blocked,
            "blockedGroups": blocked_groups,
            "standardSupportAvailable": standard_support_available,
        }

    return {
        "hasApplicableSsa": True,
        "standardSupportAvailable": standard_support_available,
        "sourceSsaId": source_ssa.id,
        "verificationState": source_ssa.verification_status,
        "ssaDate": source_ssa.date_of_ssa,
        "priority": top_need,
        "unmetPriority": unmet_priority,
        "primary": suggestions[:limit],
        "otherEligible": suggestions[limit:],
    }


def recommend_cluster_activities(
    *,
    cluster,
    principal=None,
    project=None,
    executor_type=DeliveryType.STAFF,
    limit=3,
) -> dict:
    """Aggregate verified member-school need without inventing a Cluster SSA.

    Each member is evaluated by the same canonical school recommendation
    service. Results are then merged deterministically, preserving every
    contributing SSA in the returned recommendation source.
    """
    from apps.schools.models import School

    # School.cluster_id is a bare CharField (no FK — see apps/schools/models),
    # so membership filters on the id, never a relation lookup.
    members = list(
        School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True).order_by(
            "school_id"
        )
    )
    merged: dict[str, dict] = {}
    schools_with_ssa = 0
    for school in members:
        result = recommend_activities(
            school=school,
            principal=principal,
            project=project,
            cluster=cluster,
            executor_type=executor_type,
            limit=100,
        )
        if not result["hasApplicableSsa"]:
            continue
        schools_with_ssa += 1
        for suggestion in [*result["primary"], *result["otherEligible"]]:
            code = suggestion["stableCode"]
            row = merged.get(code)
            context = {
                "schoolId": school.id,
                "schoolCode": school.school_id,
                "ssaId": result["sourceSsaId"],
                "intervention": suggestion["targetIntervention"],
                "score": suggestion["currentScore"],
                "classification": suggestion["classification"],
            }
            if row is None:
                row = {**suggestion, "schoolContexts": [], "schoolsMatched": 0}
                merged[code] = row
            row["schoolContexts"].append(context)
            row["schoolsMatched"] += 1
            row["rank"] = min(row["rank"], suggestion["rank"])
            row["existingSupportConflict"] = (
                row["existingSupportConflict"] or suggestion["existingSupportConflict"]
            )

    suggestions = list(merged.values())
    for row in suggestions:
        row["recommendationReason"] = (
            f"{row['schoolsMatched']} Cluster member School(s) have verified "
            f"{row['targetIntervention'].replace('_', ' ').title()} need."
        )
    suggestions.sort(
        key=lambda row: (
            row["rank"],
            -row["schoolsMatched"],
            row["existingSupportConflict"],
            row["displayName"].casefold(),
            row["stableCode"],
        )
    )
    return {
        "hasApplicableSsa": bool(schools_with_ssa),
        "sourceSsaId": None,
        "verificationState": "verified" if schools_with_ssa else "none",
        "clusterId": cluster.id,
        "memberCount": len(members),
        "membersWithApplicableSsa": schools_with_ssa,
        "priority": (
            {
                "label": "Verified Cluster member needs",
                "classification": "Aggregated",
            }
            if schools_with_ssa
            else {
                "label": "Complete member SSAs",
                "classification": "Mandatory prerequisite",
            }
        ),
        "primary": suggestions[:limit],
        "otherEligible": suggestions[limit:],
    }


def _suggestion(item, intervention, source_ssa, reason, *, rank, need=None):
    return {
        "catalogueItemId": item.id,
        "stableCode": item.stable_code,
        "displayName": item.display_name,
        "targetIntervention": intervention,
        "currentScore": need.get("score") if need else None,
        "classification": need.get("band") if need else "Prerequisite",
        "recommendationReason": reason,
        "suggestedDeliveryMethod": item.delivery_method,
        "eligibleExecutorTypes": [
            name
            for name, allowed in (
                ("staff", item.staff_delivery_allowed),
                ("partner", item.partner_delivery_allowed),
            )
            if allowed
        ],
        "requiredEvidence": item.evidence_profile,
        "costingProfile": item.costing_profile,
        "confidence": need.get("confidence") if need else "high",
        "existingSupportConflict": bool(getattr(item, "has_active_conflict", False)),
        "deliveredRecently": bool(getattr(item, "delivered_recently", False)),
        "rank": rank,
        "sourceSsaId": getattr(source_ssa, "id", None),
        "workflowKind": item.workflow_kind,
        "targetAudience": item.target_audience,
        "salesforceRecordType": item.salesforce_record_type,
    }


@transaction.atomic
def create_version(item: ActivityCatalogueItem, *, actor_id: str, reason: str):
    if not reason.strip():
        raise BadRequest("A change reason is required.")
    last = (
        ActivityCatalogueVersion.objects.select_for_update()
        .filter(catalogue_item=item)
        .order_by("-version")
        .first()
    )
    return ActivityCatalogueVersion.objects.create(
        catalogue_item=item,
        version=(last.version if last else 0) + 1,
        snapshot=item.snapshot(),
        change_reason=reason.strip(),
        created_by=actor_id,
    )


@transaction.atomic
def resolve_review(review, *, item, actor_id: str, note: str):
    """Mark a review-queue entry resolved — the ONE place this workflow
    state is written (views must not set review.status directly)."""
    from django.utils import timezone

    review.status = "resolved"
    review.resolution_note = note
    review.resolved_by = actor_id
    review.resolved_at = timezone.now()
    review.save(
        update_fields=[
            "status",
            "resolution_note",
            "resolved_by",
            "resolved_at",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="activity_catalogue_review_resolved",
        subject_kind="ActivityCatalogueReviewQueue",
        subject_id=review.id,
        actor_id=actor_id,
        reason=note,
        payload={
            "sourceModel": review.source_model,
            "sourceRecordId": review.source_record_id,
            "stableCode": item.stable_code,
        },
    )
    return review


def transition_item(item, *, status: str, actor_id: str, reason: str):
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("A lifecycle change reason is required.")
    item = ActivityCatalogueItem.objects.select_for_update().get(pk=item.pk)
    if status not in CatalogueStatus.values:
        raise BadRequest("Unknown Catalogue lifecycle status.")
    if status == CatalogueStatus.DRAFT and item.activities.exists():
        raise BadRequest("A used Catalogue item cannot return to Draft.")
    item.status = status
    item.updated_by = actor_id
    item.save(update_fields=["status", "updated_by", "updated_at"])
    create_version(item, actor_id=actor_id, reason=reason)
    return item
