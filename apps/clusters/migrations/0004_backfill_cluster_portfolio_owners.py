from django.db import migrations
from django.db.models import Q


def backfill_cluster_portfolio_owners(apps, schema_editor):
    """Adopt the one portfolio owner shared by an ownerless cluster's schools."""
    Cluster = apps.get_model("clusters", "Cluster")
    School = apps.get_model("schools", "School")
    StaffProfile = apps.get_model("accounts", "StaffProfile")

    ownerless = Cluster.objects.filter(deleted_at__isnull=True).filter(
        Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id="")
    )
    for cluster in ownerless.iterator(chunk_size=200):
        raw_owner_ids = set(
            School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
            .exclude(account_owner_id__isnull=True)
            .exclude(account_owner_id="")
            .values_list("account_owner_id", flat=True)
            .distinct()
        )
        if not raw_owner_ids:
            continue

        profiles = StaffProfile.objects.filter(
            Q(id__in=raw_owner_ids) | Q(user_id__in=raw_owner_ids)
        ).values_list("id", "user_id")
        canonical_by_identifier = {}
        for profile_id, user_id in profiles:
            canonical_by_identifier[profile_id] = profile_id
            if user_id:
                canonical_by_identifier[user_id] = profile_id

        canonical_owners = {
            canonical_by_identifier[owner_id]
            for owner_id in raw_owner_ids
            if owner_id in canonical_by_identifier
        }
        # One shared answer may be written automatically. Zero is missing
        # data; more than one is a portfolio decision and must not be guessed.
        if len(canonical_owners) == 1:
            Cluster.objects.filter(pk=cluster.pk).update(
                responsible_staff_id=canonical_owners.pop()
            )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0021_admin_also_field_officer"),
        ("clusters", "0003_repair_canonical_school_cluster_membership"),
        ("schools", "0019_school_closed_at_school_closure_effective_date_and_more"),
    ]

    operations = [
        migrations.RunPython(
            backfill_cluster_portfolio_owners, migrations.RunPython.noop
        )
    ]
