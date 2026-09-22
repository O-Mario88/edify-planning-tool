"""What a partner organisation does: interventions, and the activities under them.

Owner, 2026-09-22:

  "Some partners are doing more than one activity. Can you make sure the list
  of interventions and their activities are in checkbox so that many activities
  can be assigned to partners."

The form had one dropdown, `Linked SSA intervention`, and one answer. A partner
that runs literacy training and financial-health coaching had to be recorded as
doing one of them, and the other simply was not written down — so the register
that says who does what was wrong about most of the organisations in it.

WHAT IS OFFERED

The catalogue already knows both halves. `ActivityInterventionMapping` says
which intervention each catalogue item is meant to move, and the item itself
says whether a partner may deliver it at all (`partner_delivery_allowed`). So
the tick-list is not a second list somebody has to maintain: it is the live
catalogue, grouped by intervention, filtered to the work a partner can actually
be given.

Two groups exist that are not an SSA intervention, and both are drawn rather
than dropped — an activity nobody can tick is an activity no partner can be
recorded as doing:

* work mapped to *any* intervention (`NULL_INTERVENTION_MODES`), which the
  planner chooses per school;
* partner-deliverable work with no mapping at all.

WHAT IS STORED

`Partner.ssa_interventions` and `Partner.activity_codes`, both arrays.
`ssa_intervention` — the single column the register, the oversight grouping and
the partner profile have always read — is kept, and holds the first ticked
intervention. Nothing that reads it needs to change, and a partner saved before
this change still reads correctly.

Codes are validated against what the form offered. A browser can post anything,
and an activity code nobody can deliver is a claim about the catalogue rather
than a fact about the partner.
"""

from __future__ import annotations

from apps.core.enums import SsaIntervention

#: The two groups that are not an SSA intervention. Their keys cannot collide
#: with an intervention value, which is why they carry a prefix.
ANY_INTERVENTION_KEY = "group:any"
UNMAPPED_KEY = "group:unmapped"


def _intervention_labels() -> dict[str, str]:
    return {value: label for value, label in SsaIntervention.choices}


def intervention_activity_options() -> list[dict]:
    """Each intervention with the activities a partner may be given under it.

    Returns ``[{key, label, kind, activities: [{code, name, type}]}]`` in the
    order the SSA intervention enum declares, with the two non-intervention
    groups last. An intervention with no partner-deliverable activity still
    appears: a partner can be recorded as covering it before the catalogue has
    anything under it.
    """
    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityInterventionMapping,
        CatalogueStatus,
        NULL_INTERVENTION_MODES,
    )

    items = {
        item.stable_code: item
        for item in ActivityCatalogueItem.objects.filter(
            status=CatalogueStatus.ACTIVE,
            partner_delivery_allowed=True,
        ).order_by("display_name")
    }
    if not items:
        return _groups({}, {})

    mappings = ActivityInterventionMapping.objects.filter(
        active=True,
        catalogue_item__stable_code__in=list(items),
    ).values_list("catalogue_item__stable_code", "intervention", "mapping_mode")

    by_intervention: dict[str, list[str]] = {}
    mapped: set[str] = set()
    for code, intervention, mode in mappings:
        key = intervention
        if not key or mode in NULL_INTERVENTION_MODES:
            key = ANY_INTERVENTION_KEY
        by_intervention.setdefault(key, [])
        if code not in by_intervention[key]:
            by_intervention[key].append(code)
        mapped.add(code)

    unmapped = [code for code in items if code not in mapped]
    if unmapped:
        by_intervention[UNMAPPED_KEY] = unmapped

    return _groups(by_intervention, items)


def _groups(by_intervention: dict[str, list[str]], items: dict):
    labels = _intervention_labels()

    def activities(key):
        return [
            {
                "code": code,
                "name": getattr(items.get(code), "display_name", code),
                "type": getattr(items.get(code), "activity_type", ""),
            }
            for code in by_intervention.get(key, [])
        ]

    groups = [
        {
            "key": value,
            "label": label,
            "kind": "intervention",
            "activities": activities(value),
        }
        for value, label in labels.items()
    ]
    for key, label, kind in (
        (ANY_INTERVENTION_KEY, "Any SSA intervention", "any"),
        (UNMAPPED_KEY, "Not mapped to an intervention", "unmapped"),
    ):
        if by_intervention.get(key):
            groups.append(
                {
                    "key": key,
                    "label": label,
                    "kind": kind,
                    "activities": activities(key),
                }
            )
    return groups


def selected_capabilities(posted_interventions, posted_activities) -> dict:
    """The ticked interventions and activities, kept only where they are real.

    An unknown code is dropped rather than refused: the form is a tick-list
    built from the live catalogue, so an unknown value means the catalogue
    moved under an open drawer, and losing the whole save over it would cost
    the operator every other tick they had made.
    """
    groups = intervention_activity_options()
    valid_groups = {group["key"] for group in groups}
    valid_activities = {
        activity["code"] for group in groups for activity in group["activities"]
    }

    interventions = [
        value
        for value in dict.fromkeys(str(v).strip() for v in posted_interventions or [])
        if value in valid_groups
    ]
    activities = [
        value
        for value in dict.fromkeys(str(v).strip() for v in posted_activities or [])
        if value in valid_activities
    ]
    return {
        "ssa_interventions": interventions,
        "activity_codes": activities,
        # The one column every existing reader knows about. First ticked wins,
        # and a group that is not an intervention never becomes one.
        "ssa_intervention": next(
            (value for value in interventions if value in _intervention_labels()),
            None,
        ),
    }


def describe(partner) -> dict:
    """A saved partner's capabilities, for a profile or a register row."""
    labels = _intervention_labels()
    codes = list(getattr(partner, "activity_codes", None) or [])
    names = {}
    if codes:
        from apps.activity_catalogue.models import ActivityCatalogueItem

        names = dict(
            ActivityCatalogueItem.objects.filter(stable_code__in=codes).values_list(
                "stable_code", "display_name"
            )
        )
    group_labels = {
        **labels,
        ANY_INTERVENTION_KEY: "Any SSA intervention",
        UNMAPPED_KEY: "Not mapped to an intervention",
    }
    stored = list(getattr(partner, "ssa_interventions", None) or [])
    # A partner saved before the tick-list has one intervention and no array.
    if not stored and getattr(partner, "ssa_intervention", None):
        stored = [partner.ssa_intervention]
    return {
        "interventions": [
            {"key": key, "label": group_labels.get(key, key.replace("_", " ").title())}
            for key in stored
        ],
        "activities": [{"code": code, "name": names.get(code, code)} for code in codes],
    }
