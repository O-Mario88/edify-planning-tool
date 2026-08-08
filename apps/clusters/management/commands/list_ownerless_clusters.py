"""Clusters nobody is responsible for.

A cluster is scoped to whoever is responsible for it, so one with no
`responsible_staff_id` reaches no CCEO's and no Programme Lead's pickers. That
is the rule working — an unowned cluster is unassigned — but it is invisible
work, and invisible work is what this command exists to make visible.

It reports rather than guesses. Ownership could be inferred from the district,
or from whoever happens to hold schools nearby, and both would be a fabricated
answer to "whose cluster is this" written into the column that decides who can
touch it. The suggestion column names candidates; a person chooses.

Usage:
  python manage.py list_ownerless_clusters
  python manage.py list_ownerless_clusters --suggest   # name likely owners
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.clusters.models import Cluster


class Command(BaseCommand):
    help = "List clusters with no responsible staff member."

    def add_arguments(self, parser):
        parser.add_argument(
            "--suggest",
            action="store_true",
            help="Name the staff who hold schools in each cluster's district.",
        )

    def handle(self, *args, **options):
        ownerless = list(
            Cluster.objects.filter(deleted_at__isnull=True)
            .filter(responsible_staff_id__isnull=True)
            .select_related("district")
            .order_by("district__name", "name")
        ) + list(
            Cluster.objects.filter(deleted_at__isnull=True, responsible_staff_id="")
            .select_related("district")
            .order_by("district__name", "name")
        )

        total = Cluster.objects.filter(deleted_at__isnull=True).count()
        if not ownerless:
            self.stdout.write(
                self.style.SUCCESS(f"All {total} cluster(s) have a responsible staff.")
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"{len(ownerless)} of {total} cluster(s) have no responsible staff, "
                "so they appear in no CCEO or Programme Lead picker:"
            )
        )
        for cluster in ownerless:
            district = getattr(cluster.district, "name", "—")
            self.stdout.write(f"  {cluster.name}  ({district})")
            if options["suggest"]:
                for name in self._candidates(cluster):
                    self.stdout.write(f"      candidate: {name}")

        self.stdout.write(
            "\nAssign one from the cluster's Edit drawer, which writes "
            "responsible_staff_id."
        )

    def _candidates(self, cluster):
        """Staff holding schools in this cluster's district — a shortlist, not
        an answer. Named so somebody can choose without going to look."""
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        from apps.schools.models import School

        if not cluster.district_id:
            return []
        school_ids = School.objects.filter(
            district_id=cluster.district_id, deleted_at__isnull=True
        ).values_list("id", flat=True)
        staff_ids = set(
            StaffSchoolAssignment.objects.filter(school_id__in=school_ids).values_list(
                "staff_id", flat=True
            )
        )
        return [
            f"{p.user.name} ({p.user.active_role})"
            for p in StaffProfile.objects.filter(id__in=staff_ids)
            .select_related("user")
            .order_by("user__name")[:5]
        ]
