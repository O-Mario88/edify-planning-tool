from django.db import migrations


def forwards(apps, schema_editor):
    """Attach every district to its UBOS sub-region.

    Safe on a database whose geography has not been bootstrapped yet -- sync()
    no-ops when there are no regions, and the management command re-runs it
    after an import.
    """
    from apps.geography.subregions import sync

    sync(apps)


def backwards(apps, schema_editor):
    District = apps.get_model("geography", "District")
    SubRegion = apps.get_model("geography", "SubRegion")
    District.objects.filter(sub_region__isnull=False).update(sub_region=None)
    SubRegion.objects.filter(source="UBOS_STATISTICAL").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0002_secondarydistrictgroup_district_district_type_and_more"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
