"""
Management command: repair_dangling_clusters

Find — and optionally clear — schools whose cluster_id points at a Cluster that
no longer exists.

`School.cluster_id` is a CharField, not a foreign key, so the database cannot
refuse a dangling reference and deleting a Cluster does not cascade. A school
left pointing at a removed cluster still reads as `cluster_status="clustered"`,
so it passes the Planning filter and appears there with its cluster gone — the
raw identifier was even rendered as the cluster's name until that fallback was
fixed.

The repair is to clear the link, which is the honest state: the school is not
in a cluster, because the cluster does not exist. It is deliberately NOT to
invent a replacement cluster or to guess from the sub-county — a school
assigned to the wrong cluster is worse than one visibly assigned to none,
because the first is invisible.

Idempotent, counted before and after, and read-only unless --apply is passed.

Usage:
    python manage.py repair_dangling_clusters              # report only
    python manage.py repair_dangling_clusters --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Report or clear School.cluster_id values pointing at a missing Cluster."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Clear the dangling links. Without this the command only reports.",
        )
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        from apps.clusters.models import Cluster
        from apps.schools.models import School

        apply_changes = options["apply"]
        batch_size = max(1, options["batch_size"])

        # Soft-deleted clusters count as gone: a school must not sit in a
        # cluster that has been withdrawn.
        live_cluster_ids = set(
            Cluster.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
        )

        dangling = (
            School.objects.filter(deleted_at__isnull=True)
            .exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .exclude(cluster_id__in=live_cluster_ids)
        )

        total_schools = School.objects.filter(deleted_at__isnull=True).count()
        count = dangling.count()
        self.stdout.write(f"Schools: {total_schools}")
        self.stdout.write(f"Pointing at a missing cluster: {count}")

        if not count:
            self.stdout.write(self.style.SUCCESS("Nothing to repair."))
            return

        by_target: dict[str, int] = {}
        for ref in dangling.values_list("cluster_id", flat=True):
            by_target[ref] = by_target.get(ref, 0) + 1
        self.stdout.write("\nMissing cluster ids and how many schools reference them:")
        for ref, n in sorted(by_target.items(), key=lambda kv: -kv[1])[:20]:
            self.stdout.write(f"  {n:>6}  {ref}")

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("\nDry run. Re-run with --apply to clear these.")
            )
            return

        pending = []
        cleared = 0
        for school in dangling.iterator(chunk_size=batch_size):
            school.cluster_id = None
            school.cluster_status = "unclustered"
            pending.append(school)
            cleared += 1
            if len(pending) >= batch_size:
                self._flush(pending)
        if pending:
            self._flush(pending)

        # One audit row for the repair itself, not one per school: this is a
        # single administrative action with a count, and 16,000 rows would bury
        # the trail rather than record it.
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="schools.dangling_cluster_links_cleared",
                subject_kind="School",
                subject_id="bulk",
                actor_id=None,
                actor_role=None,
                success=True,
                reason="cluster_id referenced a Cluster that no longer exists",
                payload={"cleared": cleared, "targets": by_target},
            )
        except Exception:  # noqa: BLE001 — the repair matters more than its record
            self.stdout.write(self.style.WARNING("  (audit row could not be written)"))

        remaining = (
            School.objects.filter(deleted_at__isnull=True)
            .exclude(cluster_id__isnull=True)
            .exclude(cluster_id="")
            .exclude(cluster_id__in=live_cluster_ids)
            .count()
        )
        self.stdout.write(self.style.SUCCESS(f"\nCleared {cleared} school(s)."))
        self.stdout.write(f"Remaining dangling references: {remaining}")

    @staticmethod
    def _flush(pending: list) -> None:
        # bulk_update, not save(): School.save() re-derives clustering from
        # sub-county coverage, which would fight the repair on any school whose
        # sub-county happens to be covered.
        with transaction.atomic():
            type(pending[0]).objects.bulk_update(
                pending, ["cluster_id", "cluster_status"]
            )
        pending.clear()
