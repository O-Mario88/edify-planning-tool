"""Retire the legacy ready/limited/locked planning-readiness vocabulary."""

from django.db import migrations, models


CANONICAL_VALUES = {
    "requires_cluster",
    "ready_for_baseline_ssa",
    "ready_for_support_planning",
    "ready_for_partner_assignment",
    "scheduled",
    "in_my_plan",
    "awaiting_evidence",
    "awaiting_ia",
    "finance_pending",
    "closed",
    "data_cleanup_required",
    "cost_catalogue_required",
}


def normalize_readiness(apps, schema_editor):
    School = apps.get_model("schools", "School")
    for school in School.objects.exclude(planning_readiness__in=CANONICAL_VALUES).iterator():
        if not school.cluster_id:
            readiness = "requires_cluster"
        elif school.current_fy_ssa_status == "done":
            readiness = "ready_for_support_planning"
        else:
            readiness = "ready_for_baseline_ssa"
        School.objects.filter(pk=school.pk).update(planning_readiness=readiness)


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0014_school_school_name_trgm_idx"),
        ("clusters", "0003_repair_canonical_school_cluster_membership"),
    ]

    operations = [
        migrations.RunPython(normalize_readiness, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="school",
            name="planning_readiness",
            field=models.CharField(
                choices=[
                    ("requires_cluster", "Requires Cluster"),
                    ("ready_for_baseline_ssa", "SSA Required"),
                    ("ready_for_support_planning", "Ready for Support Planning"),
                    ("ready_for_partner_assignment", "Ready for Partner Assignment"),
                    ("scheduled", "Scheduled"),
                    ("in_my_plan", "In My Plan"),
                    ("awaiting_evidence", "Awaiting Evidence"),
                    ("awaiting_ia", "Awaiting IA"),
                    ("finance_pending", "Finance Pending"),
                    ("closed", "Closed"),
                    ("data_cleanup_required", "Data Cleanup Required"),
                    ("cost_catalogue_required", "Cost Catalogue Required"),
                ],
                default="requires_cluster",
                max_length=32,
            ),
        ),
    ]
