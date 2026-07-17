"""Make School.cluster_id the repaired canonical cluster membership source."""

from django.db import migrations


def repair_membership(apps, schema_editor):
    Cluster = apps.get_model("clusters", "Cluster")
    Assignment = apps.get_model("clusters", "SchoolClusterAssignment")
    School = apps.get_model("schools", "School")

    valid_cluster_ids = set(
        Cluster.objects.filter(deleted_at__isnull=True, status="active").values_list(
            "id", flat=True
        )
    )
    # A historic join row only fills an absent/invalid pointer; it can never
    # override an existing valid School.cluster_id.
    fallback_by_school = {}
    for row in (
        Assignment.objects.filter(cluster_id__in=valid_cluster_ids)
        .order_by("school_id", "-created_at", "-id")
        .values("school_id", "cluster_id")
        .iterator()
    ):
        fallback_by_school.setdefault(row["school_id"], row["cluster_id"])

    for school in School.objects.all().only("id", "cluster_id", "cluster_status").iterator():
        target_cluster_id = (
            school.cluster_id
            if school.cluster_id in valid_cluster_ids
            else fallback_by_school.get(school.id)
        )
        target_status = "clustered" if target_cluster_id else "unclustered"
        if (
            school.cluster_id != target_cluster_id
            or school.cluster_status != target_status
        ):
            School.objects.filter(pk=school.pk).update(
                cluster_id=target_cluster_id, cluster_status=target_status
            )

        Assignment.objects.filter(school_id=school.id).exclude(
            cluster_id=target_cluster_id
        ).delete()
        if target_cluster_id:
            Assignment.objects.get_or_create(
                school_id=school.id,
                cluster_id=target_cluster_id,
                defaults={"assigned_by": "system_canonical_repair"},
            )


class Migration(migrations.Migration):
    dependencies = [
        ("clusters", "0002_cluster_environment_cluster_source"),
        ("schools", "0014_school_school_name_trgm_idx"),
    ]

    operations = [migrations.RunPython(repair_membership, migrations.RunPython.noop)]
