"""Which clusters a school may actually join.

One rule, one place. Four pickers previously each re-derived this and did not
agree, and the drawer offering what the service then refused is the failure
`cluster_in_scope` was written to prevent.

    Eligible cluster
      = active cluster
      + owned by the school's own staff owner
      + in the school's district
      + in the school's sub-county, when the school has one

Each clause answers a different question and none is redundant:

* **Owner.** A cluster is somebody's portfolio. Sharing a district is not
  sharing it, and moving a school into another CCEO's cluster hands away work
  that person is accountable for without either of them agreeing to it.
* **District.** A cluster is built from a district's sub-counties, so a
  cross-district membership contradicts how the cluster was defined.
* **Sub-county.** The narrowest true statement about where a school is. Where
  the school has one, offering the district's other sub-counties is offering a
  cluster the school does not belong in.

Sub-county is applied only when the school has one. Roughly a third of schools
do not, and treating a missing sub-county as "matches nothing" would empty the
picker for them — so the fallback is district-wide *and the drawer says so*,
rather than silently narrowing to zero or silently ignoring the rule.
"""

from __future__ import annotations

from django.db.models import Q

from apps.clusters.models import Cluster
from apps.core.enums import ClusterRecordStatus


def owner_id_variants(owner_id: str) -> set[str]:
    """Both id spaces for one owner.

    `School.account_owner_id` and `Cluster.responsible_staff_id` are plain
    CharFields, and the paths that write them disagree: the cluster edit drawer
    stores a User id, school ingest stores a StaffProfile id. Comparing one
    space against the other silently matches nothing, which would read as "this
    owner has no clusters" rather than as a bug.
    """
    ident = (owner_id or "").strip()
    if not ident:
        return set()
    ids = {ident}
    try:
        from apps.accounts.models import StaffProfile
    except Exception:  # noqa: BLE001 - accounts may not be ready
        return ids
    for profile_id, user_id in StaffProfile.objects.filter(
        Q(id=ident) | Q(user_id=ident)
    ).values_list("id", "user_id"):
        ids.update({i for i in (profile_id, user_id) if i})
    return ids


def eligible_clusters_for_school(school, *, scope=None):
    """Clusters this school may join, narrowed as far as its data allows.

    `scope` additionally constrains the result to what the caller may write —
    passed by the views so the picker cannot offer a cluster outside the user's
    own portfolio even when it matches the school perfectly.
    """
    if school is None:
        return Cluster.objects.none()

    owner_ids = owner_id_variants(getattr(school, "account_owner_id", ""))
    if not owner_ids or not getattr(school, "district_id", None):
        # No owner or no district is a data-quality problem, not a licence to
        # offer everything. The drawer explains which field is missing.
        return Cluster.objects.none()

    qs = Cluster.objects.filter(
        deleted_at__isnull=True,
        status=ClusterRecordStatus.ACTIVE,
        district_id=school.district_id,
        responsible_staff_id__in=owner_ids,
    )

    sub_county_id = getattr(school, "sub_county_id", None)
    if sub_county_id:
        # A cluster reaches a sub-county either as its primary one or through
        # its declared coverage; both are the cluster saying "this ground is
        # mine", so both qualify.
        #
        # A cluster with *no* sub-county also qualifies, and that is not a
        # loophole: the rule excludes another sub-county's clusters, and a
        # district-level cluster is not another sub-county — it has not claimed
        # one. Excluding it would make every district-level cluster unusable by
        # any school that has a sub-county, which is most of the ones that do,
        # and would read as the picker losing clusters that are plainly right.
        # `set_school_cluster_membership` applies the mirror of this: it
        # refuses only when both sides name a sub-county and they differ.
        qs = qs.filter(
            Q(sub_county_id=sub_county_id)
            | Q(covered_sub_counties__sub_county_id=sub_county_id)
            | Q(sub_county__isnull=True)
        ).distinct()

    if scope is not None:
        from apps.core.scoping import cluster_queryset

        writable = cluster_queryset(scope)
        if writable is not None:
            qs = qs.filter(id__in=writable.values("id"))

    return qs.select_related("district", "sub_county").order_by("name")


def ineligibility_reason(school) -> str | None:
    """Why the list is empty, in the words the drawer should use.

    An empty picker with no explanation reads as a broken page. Every branch
    here names the field to fix and who fixes it, because the next action is
    different in each case.
    """
    if school is None:
        return "This school could not be loaded."
    if not getattr(school, "district_id", None):
        return (
            "This school has no district, so no cluster can be matched to it. "
            "Add the district on the school profile first."
        )
    if not (getattr(school, "account_owner_id", "") or "").strip():
        return (
            "This school has no assigned staff owner, and a cluster belongs to "
            "the person responsible for its schools. Assign an owner first."
        )
    return None
