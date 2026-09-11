"""Give empty clusters a membership, so they can be planned into.

Every scheduling surface is gated on cluster membership: the Planning page
lists only clustered schools, and the cluster scheduler refuses an empty
cluster outright ("no active schools, so there is nobody to invite"). A
database of unclustered schools and empty clusters therefore cannot be planned
in at all, which presents to a user as "scheduling does not save".

``seed --demo`` now builds membership itself, but re-seeding rebuilds the
demo activity fixture. This command is the additive half on its own: it never
deletes anything and only ever touches clusters that hold no schools, so it is
safe to run against a populated demo or development database, and safe to run
twice.

``set_school_cluster_membership`` stays the authority on the write, so the two
rules it enforces hold here as everywhere else: a school joins a cluster in
its own district, covering its own sub-county, owned by its own portfolio
owner. That is why an empty cluster is re-homed onto its group's geography
first — a cluster sitting on an unrelated district can only refuse the schools
offered to it.
"""

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.clusters.eligibility import portfolio_owner_profile_id
from apps.clusters.models import Cluster, ClusterSubCounty
from apps.clusters.services import active_school_count, set_school_cluster_membership
from apps.core.enums import ClusterRecordStatus
from apps.schools.models import School

DEFAULT_MEMBERS = 6


class Command(BaseCommand):
    help = "Populate empty clusters with unclustered schools from their own portfolio."

    def add_arguments(self, parser):
        parser.add_argument(
            "--members",
            type=int,
            default=DEFAULT_MEMBERS,
            help=f"Schools to place in each empty cluster (default {DEFAULT_MEMBERS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change and write nothing.",
        )

    def handle(self, *args, **options):
        members_per_cluster = max(1, options["members"])
        dry_run = options["dry_run"]

        empty_clusters = [
            cluster
            for cluster in Cluster.objects.filter(
                status=ClusterRecordStatus.ACTIVE, deleted_at__isnull=True
            ).order_by("name")
            if active_school_count(cluster.id) == 0
        ]
        if not empty_clusters:
            self.stdout.write("Every active cluster already holds schools.")
            return

        # Only schools that are genuinely free to join one. A school already
        # pointing at a cluster is somebody's membership, not spare capacity.
        candidates = (
            School.objects.filter(deleted_at__isnull=True)
            .filter(Q(cluster_id__isnull=True) | Q(cluster_id=""))
            .exclude(sub_county_id__isnull=True)
            .select_related("district", "sub_county")
            .order_by("name")
        )

        groups: dict[tuple[str, str], list] = {}
        for school in candidates:
            owner_id = portfolio_owner_profile_id(school)
            if not owner_id:
                # Ownerless schools are a data gap for a person to close, not
                # something to guess at while filling a cluster.
                continue
            groups.setdefault((owner_id, school.sub_county_id), []).append(school)

        # Biggest groups first, then by key, so repeated runs are deterministic.
        ranked = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        if not ranked:
            self.stdout.write(
                "No unclustered school has both a sub-county and a portfolio owner; "
                "nothing can be grouped."
            )
            return

        placed = 0
        filled = 0
        for cluster, ((owner_id, _sub_county_id), group) in zip(empty_clusters, ranked):
            target = group[0]
            if dry_run:
                self.stdout.write(
                    f"  would home {cluster.name} on {target.district.name} / "
                    f"{target.sub_county.name} and add "
                    f"{len(group[:members_per_cluster])} schools"
                )
                filled += 1
                placed += len(group[:members_per_cluster])
                continue

            fields = []
            if cluster.district_id != target.district_id:
                cluster.district_id = target.district_id
                cluster.region_id = target.region_id
                fields += ["district", "region"]
            if cluster.sub_county_id != target.sub_county_id:
                cluster.sub_county_id = target.sub_county_id
                fields.append("sub_county")
            if cluster.responsible_staff_id != owner_id:
                cluster.responsible_staff_id = owner_id
                fields.append("responsible_staff_id")
            if fields:
                cluster.save(update_fields=[*fields, "updated_at"])
            ClusterSubCounty.objects.get_or_create(
                cluster=cluster, sub_county_id=target.sub_county_id
            )

            added = 0
            for school in group[:members_per_cluster]:
                try:
                    set_school_cluster_membership(school, cluster, "backfill-command")
                except Exception as exc:  # noqa: BLE001 - report and continue
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {cluster.name}: could not add {school.school_id}: {exc}"
                        )
                    )
                    continue
                added += 1
            if added:
                filled += 1
                placed += added
            self.stdout.write(f"  {cluster.name}: {added} schools")

        verb = "would place" if dry_run else "placed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {placed} schools across {filled} clusters "
                f"({len(empty_clusters)} were empty)."
            )
        )
