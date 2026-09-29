"""Link every planned training to its course's SSA intervention.

Owner, 2026-09-29: "make sure the SSA interventions are linked to every
training created and exported as well." Trainings saved with no intervention
whose course (the in-school ``training_course``, else the catalogue item) is
fixed to one take that intervention. A planner's own choice is never
replaced, and courses that move no single intervention (orientations,
"Other") are left alone. Historical models only; each linked id is printed
to the deploy log.
"""

from django.db import migrations
from django.db.models import Q

TRAINING_TYPES = (
    "training",
    "in_school_training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
    "cluster_training_ssa_collection",
)


def link(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    Mapping = apps.get_model("activity_catalogue", "ActivityInterventionMapping")

    fixed = {}
    for item_id, intervention in (
        Mapping.objects.filter(
            active=True, mapping_mode="fixed", intervention__isnull=False
        )
        .exclude(intervention="")
        .order_by("-is_primary", "priority", "id")
        .values_list("catalogue_item_id", "intervention")
    ):
        fixed.setdefault(item_id, intervention)
    if not fixed:
        return

    missing = Activity.objects.filter(activity_type__in=TRAINING_TYPES).filter(
        Q(focus_intervention__isnull=True) | Q(focus_intervention=""),
        Q(purpose_intervention__isnull=True) | Q(purpose_intervention=""),
    )
    linked = 0
    for activity_id, course_id, item_id in missing.values_list(
        "id", "training_course_id", "catalogue_item_id"
    ):
        intervention = fixed.get(course_id) or fixed.get(item_id)
        if not intervention:
            continue
        Activity.objects.filter(id=activity_id).update(
            focus_intervention=intervention, purpose_intervention=intervention
        )
        linked += 1
        print(f"  training {activity_id} -> {intervention}")
    print(f"  linked {linked} training(s) to their course's SSA intervention")


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0062_activity_schedule_change"),
        ("activity_catalogue", "0014_mapping_review"),
    ]

    operations = [migrations.RunPython(link, migrations.RunPython.noop)]
