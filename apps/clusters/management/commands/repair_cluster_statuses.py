"""Repair clusters whose `status` holds a value from the wrong vocabulary.

`Cluster.status` takes `ClusterRecordStatus` — active / needs_review /
inactive. `ClusterStatus` — unclustered / clustered / needs_review — is a
*school's* clustering state and belongs on `School.cluster_status`. The seed
wrote "clustered" into the cluster column, and because Django enforces choices
in `full_clean()` rather than in the database, `objects.create` accepted it
without complaint.

The consequence is silent. Every cluster surface selects active/needs_review,
so an affected cluster is absent from the list, the pickers and the dashboards
while still counting in `Cluster.objects.count()` — a country with 16 clusters
showed one, and nothing anywhere reported an error.

Anything outside the vocabulary becomes ACTIVE. That is the field's own default
and the only value that restores a cluster to the surfaces it was missing from;
INACTIVE would preserve the invisibility this exists to end.

Usage:
  python manage.py repair_cluster_statuses            # apply
  python manage.py repair_cluster_statuses --dry-run  # report only
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.clusters.models import Cluster
from apps.core.enums import ClusterRecordStatus

VALID = {choice.value for choice in ClusterRecordStatus}


class Command(BaseCommand):
    help = "Set any cluster whose status is outside ClusterRecordStatus to active."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Soft-deleted clusters are left alone: they are not on any surface by
        # design, so "invisible" is not a defect for them, and rewriting them
        # would edit records somebody deliberately retired.
        offenders = list(
            Cluster.objects.filter(deleted_at__isnull=True)
            .exclude(status__in=VALID)
            .order_by("name")
        )

        if not offenders:
            self.stdout.write(self.style.SUCCESS("No clusters need repair."))
            return

        self.stdout.write(
            f"{len(offenders)} cluster(s) carry a status outside " f"{sorted(VALID)}:"
        )
        for cluster in offenders:
            self.stdout.write(f"  {cluster.name}: {cluster.status!r} → active")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return

        updated = Cluster.objects.filter(id__in=[c.id for c in offenders]).update(
            status=ClusterRecordStatus.ACTIVE
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Repaired {updated} cluster(s); they now appear on the cluster "
                "surfaces they were missing from."
            )
        )
