"""A Country Director adds an activity to the catalogue.

Owner, 2026-09-06: "activity page should have new activity button and should
be linked to either school activity or non school activity". The form asks
for the few things only a person knows — the name, whether it is school work
or non-school work, its type and delivery, how it is costed and which
intervention it serves — and derives the rest the way the seed rows do, so a
hand-authored item behaves exactly like a governed one: same eligibility
rule, same aliases, same versions, same costing.
"""

from __future__ import annotations

import re

from django.db import transaction

from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    CatalogueActivityType,
    CatalogueStatus,
    DeliveryMethod,
    MappingMode,
)
from apps.activity_catalogue.seed_data import _item
from apps.activity_catalogue.seeding import install_item
from apps.activity_catalogue.services import create_version
from apps.core.enums import ActivityType, SsaIntervention
from apps.core.exceptions import BadRequest

ACTIVITY_KINDS = (
    ("school", "School activity"),
    ("non_school", "Non-school activity"),
)

# The workflow the platform runs for a catalogue type delivered a given way.
_WORKFLOW = {
    (
        CatalogueActivityType.SCHOOL_VISIT,
        DeliveryMethod.SCHOOL_VISIT,
    ): ActivityType.SCHOOL_VISIT,
    (
        CatalogueActivityType.TRAINING,
        DeliveryMethod.IN_SCHOOL_TRAINING,
    ): ActivityType.IN_SCHOOL_TRAINING,
    (
        CatalogueActivityType.TRAINING,
        DeliveryMethod.CLUSTER_TRAINING,
    ): ActivityType.CLUSTER_TRAINING,
    (
        CatalogueActivityType.TRAINING,
        DeliveryMethod.CLUSTER_MEETING,
    ): ActivityType.CLUSTER_MEETING,
    (CatalogueActivityType.TRAINING, DeliveryMethod.ONLINE): ActivityType.TRAINING,
    (CatalogueActivityType.TRAINING, DeliveryMethod.GROUP): ActivityType.TRAINING,
    (
        CatalogueActivityType.TRAINING,
        DeliveryMethod.PROGRAMME_EVENT,
    ): ActivityType.PROGRAMME_EVENT,
    (
        CatalogueActivityType.YOUTH_CAMP,
        DeliveryMethod.GROUP,
    ): ActivityType.PROGRAMME_EVENT,
    (
        CatalogueActivityType.PROGRAMME_EVENT,
        DeliveryMethod.GROUP,
    ): ActivityType.PROGRAMME_EVENT,
    (
        CatalogueActivityType.PROGRAMME_EVENT,
        DeliveryMethod.PROGRAMME_EVENT,
    ): ActivityType.PROGRAMME_EVENT,
    (CatalogueActivityType.FIELD_EVENT, DeliveryMethod.GROUP): ActivityType.FIELD_EVENT,
    (CatalogueActivityType.ADMIN, DeliveryMethod.ADMIN): ActivityType.PARTNER_ACTIVITY,
    (
        CatalogueActivityType.ADMIN,
        DeliveryMethod.CLUSTER_MEETING,
    ): ActivityType.PARTNER_ACTIVITY,
}

# Evidence and Salesforce record by catalogue type: what the seed rows use.
_EVIDENCE = {
    CatalogueActivityType.SCHOOL_VISIT: ("SCHOOL_VISIT_FORM", "VISIT", "SVE-"),
    CatalogueActivityType.TRAINING: ("TRAINING_ATTENDANCE", "TRAINING", "TS-"),
    CatalogueActivityType.YOUTH_CAMP: ("YOUTH_CAMP_SAFEGUARDING", "TRAINING", "TS-"),
    CatalogueActivityType.PROGRAMME_EVENT: ("TRAINING_ATTENDANCE", "TRAINING", "TS-"),
    CatalogueActivityType.FIELD_EVENT: ("ADMIN_NONE", "NONE", ""),
    CatalogueActivityType.ADMIN: ("ADMIN_NONE", "NONE", ""),
}


def stable_code_for(name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "_", name.strip().upper()).strip("_")[:80]
    if not base:
        raise BadRequest("Give the activity a name.")
    code = base
    suffix = 2
    while ActivityCatalogueItem.objects.filter(stable_code=code).exists():
        code = f"{base}_{suffix}"
        suffix += 1
    return code


@transaction.atomic
def create_catalogue_item(data: dict, *, actor_id: str) -> ActivityCatalogueItem:
    """Create one activity from a Country Director's form.

    `data`: name, kind ('school' | 'non_school'), activityType, deliveryMethod,
    costingProfile, intervention (optional), targetAudience (optional),
    participantCounts (bool), multiDay (bool), reason.
    """
    from apps.budget.costing_service import COSTING_PROFILE_CHOICES

    name = str(data.get("name") or "").strip()
    if not name:
        raise BadRequest("Give the activity a name.")
    if ActivityCatalogueItem.objects.filter(display_name__iexact=name).exists():
        raise BadRequest("An activity with this name already exists.")
    kind = data.get("kind")
    if kind not in {k for k, _ in ACTIVITY_KINDS}:
        raise BadRequest(
            "Say whether this is a school activity or a non-school activity."
        )
    activity_type = data.get("activityType")
    if activity_type not in CatalogueActivityType.values:
        raise BadRequest("Choose the activity type.")
    delivery = data.get("deliveryMethod")
    if delivery not in DeliveryMethod.values:
        raise BadRequest("Choose how the activity is delivered.")
    workflow = _WORKFLOW.get((activity_type, delivery))
    if workflow is None:
        raise BadRequest("That activity type is not delivered that way.")
    profile = data.get("costingProfile")
    if profile not in COSTING_PROFILE_CHOICES:
        raise BadRequest("Choose the cost recipe.")
    intervention = data.get("intervention") or None
    if intervention is not None and intervention not in SsaIntervention.values:
        raise BadRequest("Unknown intervention.")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A change reason is required.")

    school = kind == "school"
    evidence, record_type, prefix = _EVIDENCE[activity_type]
    cluster = delivery in (
        DeliveryMethod.CLUSTER_TRAINING,
        DeliveryMethod.CLUSTER_MEETING,
    )
    row = _item(
        stable_code_for(name),
        name,
        activity_type,
        delivery,
        workflow,
        intervention=intervention,
        # A mapping row without an intervention is an administrative one;
        # the table's shape constraint says so.
        mapping_mode=MappingMode.FIXED if intervention else MappingMode.ADMINISTRATIVE,
        target_audience=str(
            data.get("targetAudience") or ("School staff" if school else "Programme")
        ),
        evidence_profile=evidence,
        salesforce_record_type=record_type,
        salesforce_expected_prefix=prefix,
        costing_profile=profile,
        staff=True,
        partner=school,
        school=school and not cluster,
        cluster=cluster,
        project=school,
        requires_ssa=False,
        non_school=not school
        or delivery in (DeliveryMethod.GROUP, DeliveryMethod.PROGRAMME_EVENT),
        multi_day=bool(data.get("multiDay")),
        participant_counts=bool(data.get("participantCounts")),
        support_objective="SSA_INTERVENTION_SUPPORT" if intervention else "",
    )
    row["description"] = str(data.get("description") or "").strip()
    item, _outcome = install_item(row, actor_id=actor_id, status=CatalogueStatus.ACTIVE)
    create_version(item, actor_id=actor_id, reason=reason)
    return item
