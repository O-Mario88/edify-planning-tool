"""Clusters, grouped by the person accountable for them.

A cluster belongs to a CCEO. A CCEO reports to a Programme Lead. So the
question an oversight role asks — "who is carrying what?" — is answered by
grouping clusters up that line rather than by listing them flat.

Two lenses, one function, because they are the same question asked from
different heights:

* an oversight role (CD, IA, RVP, Accountant) groups by **Programme Lead** —
  the unit they hold accountable;
* a Programme Lead groups by **CCEO** — grouping their own clusters under
  themselves would produce one box containing everything, which is a list with
  extra steps.

Scope comes from `cluster_queryset`, so this page cannot show a cluster the
pickers would refuse: one definition of who may see what, and this is a
reader of it rather than a second opinion.
"""

from __future__ import annotations

from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.core.scoping import (
    cluster_queryset,
    resolve_user_scope,
    team_oversight_cluster_queryset,
)

#: A cluster with no responsible staff is unassigned, not unowned-by-accident.
#: It groups under its own heading rather than being dropped, because a cluster
#: nobody is carrying is exactly what an oversight page exists to surface.
UNASSIGNED = "__unassigned__"


def _staff_directory(owner_ids: set[str]) -> dict:
    """Resolve owner ids to staff, in both id spaces.

    `responsible_staff_id` holds a User id when the edit drawer wrote it and a
    StaffProfile id when another path did, so a lookup in one space silently
    drops half the rows — the trap `owner_ids` exists for.
    """
    from apps.accounts.models import StaffProfile
    from django.db.models import Q

    ids = {i for i in owner_ids if i}
    if not ids:
        return {}
    profiles = (
        StaffProfile.objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .select_related("user")
        .prefetch_related("supervisor_links__supervisor__user")
    )
    directory = {}
    for profile in profiles:
        for key in (profile.id, profile.user_id):
            if key:
                directory[key] = profile
    return directory


def _supervisor_of(profile):
    """The Programme Lead a CCEO reports to.

    Reads the direct reporting line only. IA and RVP rows exist in the same
    table as overlapping oversight, and treating one as the reporting line
    would file a CCEO's clusters under whoever last reviewed them.
    """
    if profile is None:
        return None
    for link in profile.supervisor_links.all():
        supervisor = link.supervisor
        role = getattr(getattr(supervisor, "user", None), "active_role", "")
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            return supervisor
    return None


def _label(profile) -> str:
    if profile is None:
        return "Unassigned"
    user = getattr(profile, "user", None)
    return getattr(user, "name", "") or getattr(user, "email", "") or "Unnamed"


def grouped_clusters(principal) -> dict:
    """Clusters the caller may see, grouped by who is accountable for them.

    Returns the groups plus the totals they were folded from, so a heading and
    the rows beneath it cannot disagree — the count is the length of the list
    it labels rather than a second query.
    """
    scope = resolve_user_scope(principal)
    is_programme_lead = scope.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value

    if is_programme_lead:
        visible_clusters = team_oversight_cluster_queryset(scope)
    elif scope.country_scope or scope.can_view_summary_only:
        # This page is a read-only oversight lens. Country visibility is valid
        # here even when the role (Accountant/RVP) has no scheduling authority.
        visible_clusters = Cluster.objects.filter(deleted_at__isnull=True)
    else:
        visible_clusters = cluster_queryset(scope)
    clusters = list(
        (visible_clusters or Cluster.objects.none())
        .select_related("district", "sub_county")
        .order_by("name")
    )
    directory = _staff_directory({c.responsible_staff_id for c in clusters})

    # School counts in one query rather than one per cluster.
    from django.db.models import Count

    from apps.schools.models import School

    counts = {
        row["cluster_id"]: row["n"]
        for row in School.objects.filter(
            cluster_id__in=[c.id for c in clusters], deleted_at__isnull=True
        )
        .values("cluster_id")
        .annotate(n=Count("id"))
    }

    groups: dict[str, dict] = {}
    for cluster in clusters:
        owner = directory.get((cluster.responsible_staff_id or "").strip())
        # A PL's page groups by the CCEO who holds the cluster; everyone
        # else's groups by the PL that CCEO reports to.
        head = owner if is_programme_lead else _supervisor_of(owner)
        key = getattr(head, "id", None) or UNASSIGNED
        group = groups.setdefault(
            key,
            {
                "key": key,
                "label": _label(head),
                "role": getattr(getattr(head, "user", None), "active_role", ""),
                "is_unassigned": key == UNASSIGNED,
                "clusters": [],
                "schools": 0,
            },
        )
        group["clusters"].append(
            {
                "cluster": cluster,
                "owner": _label(owner) if owner else "",
                "district": getattr(cluster.district, "name", ""),
                "schools": counts.get(cluster.id, 0),
            }
        )
        group["schools"] += counts.get(cluster.id, 0)

    ordered = sorted(
        groups.values(),
        # Unassigned last: it is the exception, and leading with it would push
        # the people actually carrying work below the fold.
        key=lambda g: (g["is_unassigned"], g["label"].casefold()),
    )
    for group in ordered:
        group["count"] = len(group["clusters"])

    return {
        "groups": ordered,
        "grouped_by": "cceo" if is_programme_lead else "programme_lead",
        "total_clusters": len(clusters),
        "total_schools": sum(counts.values()),
        "unassigned": sum(g["count"] for g in ordered if g["is_unassigned"]),
    }
