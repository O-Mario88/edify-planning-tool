"""Declare, for each cluster, the sub-counties its schools are actually in.

`active_cluster_for_geography` matches a school to a cluster on district AND
sub-county. A cluster that declares no sub-county therefore claims nothing —
the Add-to-Cluster drawer offers no automatic answer, the School Profile shows
none, and School.save() leaves the school unclustered. All three fail the same
way and none of them says why, because "no cluster covers this sub-county" and
"no cluster has declared any sub-county" are indistinguishable from outside.

Clusters that predate the coverage model carry only a district. Their schools
already know where they are, so the coverage can be read back off the
membership rather than typed in again.

Read-only unless --commit is passed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clusters.models import Cluster, ClusterSubCounty
from apps.schools.models import School


class Command(BaseCommand):
    help = "Derive each cluster's sub-county coverage from its member schools."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Write the coverage. Without it, only reports what it would do.",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        clusters = list(
            Cluster.objects.filter(deleted_at__isnull=True).select_related("district")
        )

        planned, no_members, already = [], [], []
        for cluster in clusters:
            declared = set(
                ClusterSubCounty.objects.filter(cluster=cluster).values_list(
                    "sub_county_id", flat=True
                )
            )
            if cluster.sub_county_id:
                declared.add(cluster.sub_county_id)

            member_sub_counties = set(
                School.objects.filter(
                    cluster_id=cluster.id,
                    deleted_at__isnull=True,
                    sub_county__isnull=False,
                )
                # A school whose sub-county sits in another district is a
                # geography error of its own; adopting it here would spread
                # that error into the cluster's declared coverage.
                .filter(sub_county__district_id=cluster.district_id)
                .values_list("sub_county_id", flat=True)
            )

            missing = member_sub_counties - declared
            if not member_sub_counties:
                no_members.append(cluster)
            elif not missing:
                already.append(cluster)
            else:
                planned.append((cluster, missing))

        for cluster, missing in planned:
            self.stdout.write(
                f"{cluster.name}: +{len(missing)} sub-count"
                f"{'y' if len(missing) == 1 else 'ies'}"
            )

        if commit and planned:
            with transaction.atomic():
                for cluster, missing in planned:
                    for sub_county_id in missing:
                        ClusterSubCounty.objects.get_or_create(
                            cluster=cluster, sub_county_id=sub_county_id
                        )
                    if not cluster.sub_county_id:
                        cluster.sub_county_id = sorted(missing)[0]
                        cluster.save(update_fields=["sub_county", "updated_at"])

        self.stdout.write("")
        self.stdout.write(f"clusters                : {len(clusters)}")
        self.stdout.write(f"  coverage already right: {len(already)}")
        self.stdout.write(f"  coverage to add       : {len(planned)}")
        self.stdout.write(
            f"  no member school with a sub-county to read: {len(no_members)}"
        )
        if no_members and not planned:
            self.stdout.write("")
            self.stdout.write(
                "Nothing to derive: these clusters hold no school that records "
                "which sub-county it is in. Coverage has to be declared on the "
                "cluster itself before any school can be matched to it."
            )
        if planned and not commit:
            self.stdout.write("")
            self.stdout.write("Nothing written. Re-run with --commit to apply.")
