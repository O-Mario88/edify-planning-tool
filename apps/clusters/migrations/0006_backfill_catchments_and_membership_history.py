"""Backfill cluster catchments and the open membership rows (2026-09-15).

* Every existing cluster serves its own district: one PRIMARY catchment row.
  No neighbouring district is invented — those are approved by a person.
* Every school currently in a cluster gets one open membership row, dated from
  its assignment projection where one exists. A membership that crosses a
  district is recorded as it is, with no catchment, so the Catchment Review
  list shows it for a person to approve or end. Nothing is removed or moved.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Cluster = apps.get_model("clusters", "Cluster")
    ClusterServiceDistrict = apps.get_model("clusters", "ClusterServiceDistrict")
    SchoolClusterAssignment = apps.get_model("clusters", "SchoolClusterAssignment")
    SchoolClusterMembership = apps.get_model("clusters", "SchoolClusterMembership")
    School = apps.get_model("schools", "School")

    primaries = {}
    rows = []
    for cluster in Cluster.objects.filter(deleted_at__isnull=True).only(
        "id", "district_id", "created_at"
    ):
        if not cluster.district_id:
            continue
        rows.append(
            ClusterServiceDistrict(
                cluster_id=cluster.id,
                district_id=cluster.district_id,
                relationship_type="primary",
                reason="The cluster's own district (backfilled 2026-09-15).",
                effective_from=cluster.created_at.date(),
                active=True,
                created_by="migration",
                approved_by="migration",
            )
        )
    ClusterServiceDistrict.objects.bulk_create(rows, batch_size=500)
    for row in ClusterServiceDistrict.objects.filter(active=True).only(
        "id", "cluster_id", "district_id"
    ):
        primaries[row.cluster_id] = row

    clusters = {c.id: c for c in Cluster.objects.all().only("id", "district_id")}
    projection = {
        a.school_id: a
        for a in SchoolClusterAssignment.objects.all().only(
            "school_id", "cluster_id", "assigned_by", "created_at"
        )
    }
    memberships = []
    for school in (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .only("id", "cluster_id", "district_id", "updated_at")
        .iterator(chunk_size=1000)
    ):
        cluster = clusters.get(school.cluster_id)
        if cluster is None:
            continue
        assignment = projection.get(school.id)
        primary = primaries.get(cluster.id)
        same_district = (
            primary is not None and school.district_id == primary.district_id
        )
        memberships.append(
            SchoolClusterMembership(
                school_id=school.id,
                cluster_id=cluster.id,
                started_at=(
                    assignment.created_at
                    if assignment is not None and assignment.cluster_id == cluster.id
                    else school.updated_at
                ),
                started_by=(assignment.assigned_by if assignment else "") or "",
                start_reason="Existing membership (backfilled 2026-09-15).",
                school_district_id=school.district_id,
                cluster_district_id=cluster.district_id,
                relationship_type="primary" if same_district else "",
                catchment_id=primary.id if same_district else None,
            )
        )
        if len(memberships) >= 1000:
            SchoolClusterMembership.objects.bulk_create(memberships)
            memberships = []
    if memberships:
        SchoolClusterMembership.objects.bulk_create(memberships)


class Migration(migrations.Migration):
    dependencies = [
        ("clusters", "0005_cluster_catchments_and_membership_history"),
        ("schools", "0021_school_uniq_school_salesforce_account_id"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
