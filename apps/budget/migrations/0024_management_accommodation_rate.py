"""Give the night away a second accommodation rate.

Owner, 2026-10-05: "the accommodation for program leads, cd, IA and accountant
should be separate from the accommodation of CCEO. add a new accommodation
cost for the above roles." Asked whether the other staff roles (HR, Project
Coordinator, Business Transformation Officer, Regional Vice President,
Regional Program Lead, Admin) use it too, the owner said yes: the first row
is the CCEO's alone.

Until now every traveller's night fetched the one Accommodation row. The new
row is created here for every rate card that carries that one, copying its
figure and its minimum, so nobody's planned night changes price on deploy and
the Country Director then prices the two apart on Cost Settings. Cards without
an accommodation row get the new one from ensure_cost_reference at its
default, as every other canonical rate does.

The existing row is the CCEO's from here on and is renamed to say so, unless
the Country Director has already given it a name of their own. Its key is
unchanged, so every saved cost line still reads.
"""

from django.db import migrations

CCEO_KEY = "secondary_accommodation_per_night"
NEW_KEY = "management_accommodation_per_night"
CCEO_LABEL = "Accommodation - CCEO"
NEW_LABEL = "Accommodation - PL, CD, IA, Accountant and other staff"


def forwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    rows = CostSetting.objects.filter(key=CCEO_KEY, catalogue_item__isnull=True)
    for cceo in rows.order_by("catalogue_id"):
        _row, created = CostSetting.objects.get_or_create(
            catalogue_id=cceo.catalogue_id,
            key=NEW_KEY,
            defaults={
                "label": NEW_LABEL,
                "unit_cost": cceo.unit_cost,
                "approved_minimum": cceo.approved_minimum
                if cceo.approved_minimum is not None
                else cceo.unit_cost,
                "fy": cceo.fy,
                "version": 1,
                "unit": "per night",
            },
        )
        if created:
            print(
                f"[0024_management_accommodation_rate] added {NEW_LABEL} at UGX "
                f"{cceo.unit_cost} to catalogue {cceo.catalogue_id}."
            )
        if (cceo.label or "").strip() == "Accommodation":
            cceo.label = CCEO_LABEL
            cceo.save(update_fields=["label"])


def backwards(apps, schema_editor):
    """Remove the second rate and give the first its old name back. A night
    already priced at the second rate keeps its own saved cost line."""
    CostSetting = apps.get_model("budget", "CostSetting")
    CostSetting.objects.filter(key=NEW_KEY, catalogue_item__isnull=True).delete()
    CostSetting.objects.filter(key=CCEO_KEY, label=CCEO_LABEL).update(
        label="Accommodation"
    )


class Migration(migrations.Migration):
    dependencies = [("budget", "0023_retire_cluster_session_rates")]
    operations = [migrations.RunPython(forwards, backwards)]
