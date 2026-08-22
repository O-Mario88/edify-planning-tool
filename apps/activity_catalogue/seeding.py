from __future__ import annotations

import re
from copy import deepcopy

from django.db import transaction

from .models import (
    MACHINE_AUTHORS,
    MappingAuthor,
    ActivityCatalogueAlias,
    ActivityCatalogueItem,
    ActivityCatalogueVersion,
    ActivityEligibilityRule,
    ActivityInterventionMapping,
    CatalogueStatus,
)
from .seed_data import ALTERNATE_STABLE_CODES, CATALOGUE_ITEMS


def normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


@transaction.atomic
def seed_activity_catalogue(*, actor_id: str = "system", dry_run: bool = False) -> dict:
    """Idempotently install the governed source catalogue.

    Existing lifecycle status is preserved.  A rerun repairs source-owned
    metadata and mappings, but never reactivates an item governance retired.
    """

    result = {
        "source": len(CATALOGUE_ITEMS),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "mappings": 0,
        "versions": 0,
    }
    for source_row in CATALOGUE_ITEMS:
        row = deepcopy(source_row)
        mapping_mode = row.pop("mapping_mode")
        intervention = row.pop("intervention")
        code = row.pop("stable_code")
        defaults = {
            **row,
            "status": CatalogueStatus.ACTIVE,
            "created_by": actor_id,
            "updated_by": actor_id,
        }
        item = ActivityCatalogueItem.objects.filter(stable_code=code).first()
        if item is None:
            item = ActivityCatalogueItem.objects.create(
                stable_code=code,
                **defaults,
            )
            result["created"] += 1
        else:
            changed = []
            # Lifecycle is governance-owned after the initial insert.
            for field, value in row.items():
                if getattr(item, field) != value:
                    setattr(item, field, value)
                    changed.append(field)
            if item.updated_by != actor_id:
                item.updated_by = actor_id
                changed.append("updated_by")
            if changed:
                item.save(update_fields=[*changed, "updated_at"])
                result["updated"] += 1
            else:
                result["unchanged"] += 1

        mapping, _ = ActivityInterventionMapping.objects.update_or_create(
            catalogue_item=item,
            intervention=intervention,
            mapping_mode=mapping_mode,
            defaults={
                "priority": 10,
                "is_primary": True,
                "active": True,
                "authored_by": MappingAuthor.SEED,
            },
        )
        result["mappings"] += 1
        # Retire only what a machine wrote. This used to deactivate EVERY
        # other mapping for the item, which made a second intervention
        # impossible to keep — the next seed run silently retired it — and
        # would have thrown away Impact Assessment's measurement rules with
        # it.
        ActivityInterventionMapping.objects.filter(
            catalogue_item=item, authored_by__in=MACHINE_AUTHORS
        ).exclude(id=mapping.id).update(active=False)

        ActivityEligibilityRule.objects.get_or_create(
            catalogue_item=item,
            defaults={
                "allowed_target_audiences": [item.target_audience],
                "core_school_only": bool(item.core_slot_type),
                "client_school_only": item.counts_toward_client_visit
                or item.counts_toward_client_training,
                "requires_project_membership": item.requires_project,
                "requires_cluster_membership": item.requires_cluster,
                "counts_toward_entitlement": item.counts_toward_client_visit
                or item.counts_toward_client_training
                or bool(item.core_slot_type),
            },
        )
        for source_alias in {item.source_name, item.display_name, code}:
            ActivityCatalogueAlias.objects.get_or_create(
                normalized_alias=normalize_alias(source_alias),
                defaults={"catalogue_item": item, "source_alias": source_alias},
            )

        if not item.versions.exists():
            ActivityCatalogueVersion.objects.create(
                catalogue_item=item,
                version=1,
                snapshot=item.snapshot(),
                change_reason="Initial governed Edify catalogue seed.",
                created_by=actor_id,
            )
            result["versions"] += 1

    for alternate, canonical in ALTERNATE_STABLE_CODES.items():
        item = ActivityCatalogueItem.objects.get(stable_code=canonical)
        ActivityCatalogueAlias.objects.get_or_create(
            normalized_alias=normalize_alias(alternate),
            defaults={"catalogue_item": item, "source_alias": alternate},
        )

    if dry_run:
        transaction.set_rollback(True)
    return result
