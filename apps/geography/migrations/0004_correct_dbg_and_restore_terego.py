from django.db import migrations


TEREGO_SUBCOUNTIES = (
    ("340101", "Imvepi Refugee Settlement"),
    ("340102", "Odupi"),
    ("340103", "Omugo"),
    ("340104", "Rhino Camp Refugee Settlement"),
    ("340105", "Uriama"),
    ("340201", "Aii-Vu"),
    ("340202", "Beleafe"),
    ("340203", "Katrini"),
    ("340204", "Leju Town Council"),
)


def forwards(apps, schema_editor):
    Region = apps.get_model("geography", "Region")
    SubRegion = apps.get_model("geography", "SubRegion")
    District = apps.get_model("geography", "District")
    SubCounty = apps.get_model("geography", "SubCounty")

    # Remove the two invalid test-like registry entries. Database restrictions
    # deliberately stop the migration if an unexpected durable reference has
    # appeared, instead of silently cascading across operational records.
    invalid_regions = Region.objects.filter(name__iexact="DbgR")
    District.objects.filter(
        name__iexact="DbgD",
        region__in=invalid_regions,
    ).delete()
    invalid_regions.filter(districts__isnull=True, sub_regions__isnull=True).delete()

    northern = (
        Region.objects.filter(name__iexact="Northern Region").first()
        or Region.objects.filter(name__iexact="Northern").first()
    )
    if northern is None:
        # Fresh databases are populated after migrations by the geography
        # bootstrap, which uses the corrected current registry.
        return

    west_nile, _ = SubRegion.objects.update_or_create(
        name="West Nile",
        defaults={
            "region": northern,
            "normalized_name": "west nile",
            "source": "UBOS_STATISTICAL",
            "confidence": "VERIFIED",
            "notes": "UBOS survey sub-region; partitions the parent region.",
        },
    )
    terego = District.objects.filter(name__iexact="Terego").first()
    if terego is None:
        terego = District.objects.create(
            region=northern,
            name="Terego",
            code="340",
            source="UBOS_NPHC_2024_LIVE",
            sub_region=west_nile,
        )
    else:
        terego.region = northern
        terego.code = "340"
        terego.source = "UBOS_NPHC_2024_LIVE"
        terego.sub_region = west_nile
        terego.save(update_fields=["region", "code", "source", "sub_region"])

    arua = District.objects.filter(
        region=northern,
        name__iexact="Arua",
    ).first()
    for pcode, name in TEREGO_SUBCOUNTIES:
        row = SubCounty.objects.filter(pcode=pcode).first()
        if row is None and arua is not None:
            row = SubCounty.objects.filter(
                district=arua,
                name__iexact=name,
            ).first()
        if row is None:
            SubCounty.objects.create(
                district=terego,
                name=name,
                pcode=pcode,
                source="UBOS_NPHC_2024_LIVE",
                seeded=True,
            )
            continue

        row.district = terego
        row.pcode = pcode
        row.source = "UBOS_NPHC_2024_LIVE"
        row.seeded = True
        row.save(update_fields=["district", "pcode", "source", "seeded"])


def backwards(apps, schema_editor):
    # Correct reference data is intentionally retained on rollback. Re-folding
    # Terego into Arua would corrupt any assignments created after this repair.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0003_populate_sub_regions"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
