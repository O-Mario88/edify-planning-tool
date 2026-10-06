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


#: What a training's record lets its editor change, and the form field each
#: comes from. The SSA intervention a training is linked to is not among
#: them: Impact Assessment sets it, through a reviewed rule
#: (apps.activity_catalogue.intervention_mapping).
TRAINING_EDITABLE_FIELDS = (
    ("display_name", "name", 255),
    ("description", "description", 4000),
    ("training_category", "trainingCategory", 64),
    ("ssa_indicator_label", "ssaIndicatorLabel", 128),
    ("target_audience", "targetAudience", 128),
)


@transaction.atomic
def update_training(
    item_id: str, data: dict, *, actor_id: str
) -> ActivityCatalogueItem:
    """Change a training's definition from its own record (owner, 2026-10-06).

    Only the catalogue entry changes. A training already scheduled keeps what
    it was scheduled with: every Activity carries its own name, profile and
    intervention snapshots and the catalogue version it was planned under, and
    none of them is touched here. The change is written as a new catalogue
    version with the editor's reason, and each changed field is marked as the
    editor's so a later seed run does not put the old value back.
    """
    from apps.activity_catalogue.models import ActivityCatalogueAlias
    from apps.activity_catalogue.seeding import normalize_alias

    item = ActivityCatalogueItem.objects.select_for_update().filter(id=item_id).first()
    if item is None:
        raise BadRequest("That training was not found.")
    if not item.is_training_course:
        raise BadRequest("Only a training in the Training Catalogue is edited here.")
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("Say why the training is changing.")

    changed = []
    for field, key, limit in TRAINING_EDITABLE_FIELDS:
        if key not in data:
            continue
        value = str(data.get(key) or "").strip()
        if len(value) > limit:
            raise BadRequest(f"That text is longer than {limit} characters.")
        if field == "display_name":
            if not value:
                raise BadRequest("Give the training a name.")
            if (
                ActivityCatalogueItem.objects.filter(display_name__iexact=value)
                .exclude(id=item.id)
                .exists()
            ):
                raise BadRequest("Another activity already has this name.")
        if field == "target_audience" and not value:
            raise BadRequest("Say who the training is for.")
        if getattr(item, field) != value:
            setattr(item, field, value)
            changed.append(field)
    if not changed:
        raise BadRequest("Nothing was changed.")

    item.edited_fields = sorted({*(item.edited_fields or []), *changed})
    item.updated_by = actor_id
    item.save(update_fields=[*changed, "edited_fields", "updated_by", "updated_at"])
    if "display_name" in changed:
        ActivityCatalogueAlias.objects.get_or_create(
            normalized_alias=normalize_alias(item.display_name),
            defaults={"catalogue_item": item, "source_alias": item.display_name},
        )
    create_version(item, actor_id=actor_id, reason=reason)
    return item
