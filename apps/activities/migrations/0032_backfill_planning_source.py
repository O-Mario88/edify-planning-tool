from django.db import migrations


def backfill(apps, schema_editor):
    """Stamp planning_source / activity_context_type on existing activities.

    §1: every budget amount originates from a dated plan. Historical rows are
    classified from their relations — core types → core planning; a project
    link → project planning; a cluster link → cluster planning; a school link
    → school planning. Programme events (new type) get the manual work-plan
    source. Rows with no relation at all (drafts from severed demo data) are
    left unstamped for the health check to surface rather than guessed.
    """
    Activity = apps.get_model("activities", "Activity")

    core_types = ("core_visit", "core_training", "core_assessment_visit")
    Activity.objects.filter(planning_source="", activity_type__in=core_types).update(
        planning_source="core_planning", activity_context_type="school"
    )
    Activity.objects.filter(planning_source="", activity_type="programme_event").update(
        planning_source="manual_work_plan", activity_context_type="programme"
    )
    Activity.objects.filter(planning_source="", project_id__isnull=False).exclude(
        project_id=""
    ).update(planning_source="project_planning", activity_context_type="project")
    Activity.objects.filter(planning_source="", cluster__isnull=False).update(
        planning_source="cluster_planning", activity_context_type="cluster"
    )
    Activity.objects.filter(planning_source="", school__isnull=False).update(
        planning_source="school_planning", activity_context_type="school"
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "activities",
            "0031_activity_activity_context_type_activity_end_date_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
