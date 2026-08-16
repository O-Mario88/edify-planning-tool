from django.db import migrations


GOVERNED_PURPOSES = (
    ("LAND_EXPANSION", "Land for Expansion", False),
    ("CLASSROOM_CONSTRUCTION", "Classroom Construction", False),
    ("DORMITORY_CONSTRUCTION", "Dormitory Construction", False),
    ("SCHOOL_VAN", "School Van", False),
    ("SCHOOL_BUS", "School Bus", False),
    ("EDTECH_COMPUTER_LAB", "EdTech - Computer Lab", True),
)

LEGACY_PURPOSE_CODES = (
    "EDTECH",
    "INFRASTRUCTURE",
    "WORKING_CAPITAL",
    "SCHOOL_EQUIPMENT",
    "COMPLIANCE",
    "OTHER",
)


def publish_governed_purposes(apps, schema_editor):
    Purpose = apps.get_model("business_transformation", "LoanPurpose")
    for code, label, is_edtech in GOVERNED_PURPOSES:
        Purpose.objects.update_or_create(
            code=code,
            defaults={"label": label, "is_edtech": is_edtech, "active": True},
        )
    # Preserve historical references while preventing new loans from using
    # broad categories that cannot say what the school financed.
    Purpose.objects.filter(code__in=LEGACY_PURPOSE_CODES).update(active=False)


def restore_legacy_purposes(apps, schema_editor):
    Purpose = apps.get_model("business_transformation", "LoanPurpose")
    Purpose.objects.filter(
        code__in=[code for code, _label, _is_edtech in GOVERNED_PURPOSES]
    ).update(active=False)
    Purpose.objects.filter(code__in=LEGACY_PURPOSE_CODES).update(active=True)


class Migration(migrations.Migration):
    dependencies = [("business_transformation", "0002_seed_uganda_reference_data")]

    operations = [
        migrations.RunPython(publish_governed_purposes, restore_legacy_purposes)
    ]
