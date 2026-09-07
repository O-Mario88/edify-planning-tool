"""The Country Cost Catalogue becomes the owner's list of 2026-09-06.

Owner: "These are the list of activities to put in the cost catalog. remove
the ones you have now." Twenty-two rows: four per-activity rates, three partner
rates, nine group-session components and six travel per-diems.

What happens to the rows the platform had, on every ACTIVE rate card (the
operational card and its reference card; superseded cards keep their rows so
the snapshots that point at them still read):

  renamed   primary_lunch_per_day            -> lunch_per_day ("Lunch")
            partner_visit_lump_sum           -> client_partner_visit
            group_training_participant_meal… -> tot_trainings_meals
  copied    partner_visit_lump_sum's rate    -> core_partner_visit, partner_meetings
  relabeled the transport, venue, facilitation, breakfast, dinner and
            accommodation rows (keys kept, so saved cost lines still read)
  created   the eleven rates the list added, at 0 until the Country
            Director sets them (a 0 rate adds nothing; it is not a blocker)
  deleted   secondary_lunch_per_day (a second lunch),
            secondary_incidentals_per_day and the cluster snack rate (no row
            in the list), partner_training_lump_sum (its 16,000 has no row;
            a partner-run training now carries Partner Meetings)

History is untouched: every costed activity keeps its ActivityScheduleCostLine
rows with the key, unit and amount it was priced at.
"""

from django.db import migrations

RENAMES = {
    "primary_lunch_per_day": "lunch_per_day",
    "partner_visit_lump_sum": "client_partner_visit",
    "group_training_participant_meal_cost_per_head": "tot_trainings_meals",
}
COPIES = {
    "client_partner_visit": ("core_partner_visit", "partner_meetings"),
}
DELETED = (
    "secondary_lunch_per_day",
    "secondary_incidentals_per_day",
    "cluster_meeting_participant_meal_cost_per_head",
    "partner_training_lump_sum",
)


def forwards(apps, schema_editor):
    from apps.budget.reference import CANONICAL_RATES, RATE_UNITS

    CostCatalogue = apps.get_model("budget", "CostCatalogue")
    CostSetting = apps.get_model("budget", "CostSetting")
    active = list(CostCatalogue.objects.filter(is_active=True))
    for card in active:
        for extra in CostCatalogue.objects.filter(
            country=card.country, fy=card.fy, kind="reference"
        ):
            if extra not in active:
                active.append(extra)
    labels = {key: label for key, label, _cost in CANONICAL_RATES}
    for card in active:
        rows = {row.key: row for row in CostSetting.objects.filter(catalogue=card)}
        for old, new in RENAMES.items():
            if old in rows and new not in rows:
                row = rows.pop(old)
                row.key = new
                row.label = labels[new]
                row.unit = RATE_UNITS[new]
                row.save(update_fields=["key", "label", "unit", "updated_at"])
                rows[new] = row
        for source, targets in COPIES.items():
            if source not in rows:
                continue
            for target in targets:
                if target in rows:
                    continue
                base = rows[source]
                rows[target] = CostSetting.objects.create(
                    catalogue=card,
                    key=target,
                    label=labels[target],
                    unit=RATE_UNITS[target],
                    unit_cost=base.unit_cost,
                    approved_minimum=base.approved_minimum,
                    fy=base.fy,
                    version=1,
                    geographic_scope=base.geographic_scope,
                    costing_profile_scope=base.costing_profile_scope,
                )
        for key, label, default_cost in CANONICAL_RATES:
            row = rows.get(key)
            if row is None:
                if card.kind == "reference":
                    # The reference card is configured by hand; never seed it.
                    continue
                CostSetting.objects.create(
                    catalogue=card,
                    key=key,
                    label=label,
                    unit=RATE_UNITS[key],
                    unit_cost=default_cost,
                    approved_minimum=default_cost,
                    fy=card.fy,
                    version=1,
                )
                continue
            if row.label != label or row.unit != RATE_UNITS[key]:
                row.label = label
                row.unit = RATE_UNITS[key]
                row.save(update_fields=["label", "unit", "updated_at"])
        CostSetting.objects.filter(catalogue=card, key__in=DELETED).delete()


def backwards(apps, schema_editor):
    """Deliberately does not restore the previous list; the owner replaced it."""


class Migration(migrations.Migration):
    dependencies = [("budget", "0015_backfill_minimum_viable_costs")]
    operations = [migrations.RunPython(forwards, backwards)]
