"""Backfill the Core Assessment slot (the 9th package slot) onto every
existing CorePlan. Before this, onboarding created only 8 slots (4 visits +
4 trainings); the mandate requires a tracked Core Assessment slot too. Uses
the same deterministic id scheme (cslot-<school>-a1) so it is idempotent and
matches what create_package_slots() now writes for new plans.
"""

from django.db import migrations

from apps.core.cuid import deterministic


def add_assessment_slots(apps, schema_editor):
    CorePlan = apps.get_model("core_schools", "CorePlan")
    CoreActivitySlot = apps.get_model("core_schools", "CoreActivitySlot")

    for plan in CorePlan.objects.all().iterator():
        slot_id = deterministic("cslot", plan.school_id, "a1")
        if CoreActivitySlot.objects.filter(id=slot_id).exists():
            continue
        interventions = plan.interventions or []
        intervention = (
            interventions[0]
            if isinstance(interventions, list) and interventions
            else "christlike_behaviour"
        )
        CoreActivitySlot.objects.create(
            id=slot_id,
            core_plan=plan,
            school_id=plan.school_id,
            intervention=intervention,
            activity_type="assessment",
            sequence_number=1,
            status="Planned",
        )


def remove_assessment_slots(apps, schema_editor):
    CoreActivitySlot = apps.get_model("core_schools", "CoreActivitySlot")
    CoreActivitySlot.objects.filter(activity_type="assessment").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0002_coreactivityslot_netsuite_status_and_more"),
    ]

    operations = [
        migrations.RunPython(add_assessment_slots, remove_assessment_slots),
    ]
