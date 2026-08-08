"""What is already wrong with school and cluster ownership.

The rules now enforced at every write — a school joins a cluster owned by its
own staff owner, in its district, in its sub-county — say nothing about rows
written before they existed. This is the reading of the current data against
them.

It only reads. Every finding carries what was expected, what is actually there,
and who would fix it, because a count of "47 mismatches" tells nobody what to
do next. Classification follows §25:

* **VALID** — matches the rule.
* **REPAIRABLE** — one unambiguous answer exists in the data itself, so a
  command can apply it.
* **MANUAL** — more than one defensible answer, or none. Guessing here writes
  a fabricated owner into the field that decides who may touch a record, which
  is worse than leaving it visibly broken.

The distinction is the point. A cluster whose member schools all share one
owner has an answer; a cluster whose members have three owners has a decision,
and the decision belongs to a person.
"""

from __future__ import annotations

from django.db.models import Count, F, Q

VALID = "valid"
REPAIRABLE = "repairable"
MANUAL = "manual"


def _finding(*, key, label, severity, expected, classification, rows, route=""):
    return {
        "key": key,
        "label": label,
        "severity": severity,
        "expected": expected,
        "classification": classification,
        "count": len(rows),
        "examples": rows[:10],
        "route": route,
        "clean": not rows,
    }


def _active_staff_ids() -> set[str]:
    """Both id spaces for every active staff member.

    An owner id is compared against this to decide whether the person still
    works here, and the two columns disagree about which id they store — so a
    set built from one space would report every correctly-owned record as
    orphaned.
    """
    from apps.accounts.models import StaffProfile

    ids: set[str] = set()
    for profile_id, user_id in StaffProfile.objects.filter(
        deleted_at__isnull=True, user__is_active=True
    ).values_list("id", "user_id"):
        ids.update({i for i in (profile_id, user_id) if i})
    return ids


# ── Schools ──────────────────────────────────────────────────────────────────
def _schools_without_a_district() -> dict:
    from apps.schools.lifecycle_service import active_schools

    rows = [
        {
            "school": s.school_id,
            "name": s.name,
            "expected": "a district",
            "actual": "none",
            "owner": s.account_owner_id or "",
            "resolution": "Set the district on the school profile.",
        }
        for s in active_schools().filter(district__isnull=True)[:200]
    ]
    return _finding(
        key="school_without_district",
        label="Active schools with no district",
        severity="high",
        expected="Every active school has one district",
        # No second source to derive a district from. Guessing one moves a
        # school into a portfolio nobody chose.
        classification=MANUAL,
        rows=rows,
        route="/schools",
    )


def _schools_without_an_owner() -> dict:
    from apps.accounts.models import StaffSchoolAssignment
    from apps.schools.lifecycle_service import active_schools

    unowned = active_schools().filter(
        Q(account_owner_id__isnull=True) | Q(account_owner_id="")
    )[:200]
    rows = []
    for school in unowned:
        # The canonical assignment is the second source §25 allows: exactly one
        # active assignment is an answer, several are a decision.
        staff = list(
            StaffSchoolAssignment.objects.filter(school_id=school.id).values_list(
                "staff_id", flat=True
            )[:3]
        )
        rows.append(
            {
                "school": school.school_id,
                "name": school.name,
                "expected": "an active staff owner",
                "actual": "none",
                "candidates": staff,
                "resolution": (
                    "Adopt the single active assignment."
                    if len(staff) == 1
                    else "Choose an owner — the assignments do not agree."
                ),
            }
        )
    return _finding(
        key="school_without_owner",
        label="Active schools with no staff owner",
        severity="high",
        expected="Every active school has one active internal staff owner",
        classification=REPAIRABLE,
        rows=rows,
        route="/schools",
    )


def _owner_status_index() -> tuple[dict, set]:
    """Every owner id mapped to its account status, plus the unresolvable ones.

    Split deliberately. "Not an active staff member" covers two states that
    call for opposite responses, and merging them produced a 16,274-row
    high-severity finding that actually said "your staff have not accepted
    their invitations yet".

    * **pending_invited** — the intended owner, mid-onboarding. Nothing to
      repair; the invitation needs accepting.
    * **deactivated, or no staff record at all** — the school has no reachable
      owner, and somebody has to be given it.
    """
    from apps.accounts.models import StaffProfile

    index = {}
    for profile in StaffProfile.objects.select_related("user").all():
        status = getattr(profile.user, "status", "") or ""
        active = bool(getattr(profile.user, "is_active", False))
        for key in (profile.id, profile.user_id):
            if key:
                index[key] = {
                    "status": status,
                    "active": active and profile.deleted_at is None,
                    "email": getattr(profile.user, "email", ""),
                }
    return index, set()


def _schools_owned_by_a_pending_invite() -> dict:
    from apps.schools.lifecycle_service import active_schools

    index, _ = _owner_status_index()
    pending = {
        key
        for key, meta in index.items()
        if not meta["active"] and meta["status"].startswith("pending")
    }
    if not pending:
        return _finding(
            key="school_owner_pending_invite",
            label="Schools whose owner has not accepted their invitation",
            severity="medium",
            expected="A school's owner has an active account",
            classification=MANUAL,
            rows=[],
            route="/staff",
        )
    qs = active_schools().filter(account_owner_id__in=pending)
    total = qs.count()
    rows = [
        {
            "school": s.school_id,
            "name": s.name,
            "expected": "an owner with an active account",
            "actual": f"{index[s.account_owner_id]['email']} is still invited",
            "resolution": "Chase the invitation; the owner itself is correct.",
        }
        for s in qs.select_related("district")[:200]
    ]
    finding = _finding(
        key="school_owner_pending_invite",
        label="Schools whose owner has not accepted their invitation",
        severity="medium",
        expected="A school's owner has an active account",
        # Nothing to repair in the data: the assignment is right and the
        # account is mid-onboarding.
        classification=MANUAL,
        rows=rows,
        route="/staff",
    )
    finding["count"] = total  # the true total, not the sampled rows
    finding["clean"] = total == 0
    return finding


def _schools_owned_by_a_departed_or_unknown_person() -> dict:
    from apps.schools.lifecycle_service import active_schools

    index, _ = _owner_status_index()
    broken = set()
    owned = (
        active_schools()
        .exclude(account_owner_id__isnull=True)
        .exclude(account_owner_id="")
    )
    for owner_id in set(owned.values_list("account_owner_id", flat=True)):
        meta = index.get(owner_id)
        if meta is None or (
            not meta["active"] and not meta["status"].startswith("pending")
        ):
            broken.add(owner_id)
    if not broken:
        rows, total = [], 0
    else:
        qs = owned.filter(account_owner_id__in=broken)
        total = qs.count()
        rows = [
            {
                "school": s.school_id,
                "name": s.name,
                "expected": "an active staff owner",
                "actual": (f"owner {s.account_owner_id} has no active staff record"),
                "resolution": "Transfer the school to an active owner.",
            }
            for s in qs[:200]
        ]
    finding = _finding(
        key="school_owner_unreachable",
        label="Schools whose owner has left or cannot be resolved",
        severity="high",
        expected="A school's owner is a real, active staff member",
        classification=MANUAL,
        rows=rows,
        route="/schools",
    )
    finding["count"] = total
    finding["clean"] = total == 0
    return finding


def _school_sub_county_outside_its_district() -> dict:
    from apps.schools.lifecycle_service import active_schools

    rows = [
        {
            "school": s.school_id,
            "name": s.name,
            "expected": f"a sub-county in {getattr(s.district, 'name', '—')}",
            "actual": f"{getattr(s.sub_county, 'name', '—')} is in another district",
            "resolution": "Correct the sub-county or the district.",
        }
        for s in active_schools()
        .select_related("district", "sub_county")
        .filter(sub_county__isnull=False, district__isnull=False)
        # F(), not a bare name: this compares two columns on the same row.
        .exclude(sub_county__district_id=F("district_id"))[:200]
    ]
    return _finding(
        key="school_sub_county_outside_district",
        label="Schools whose sub-county belongs to another district",
        severity="high",
        expected="Country → District → Sub-county stays consistent",
        classification=MANUAL,
        rows=rows,
        route="/schools",
    )


# ── Clusters ─────────────────────────────────────────────────────────────────
def _clusters_without_an_owner() -> dict:
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    rows = []
    for cluster in Cluster.objects.filter(deleted_at__isnull=True).filter(
        Q(responsible_staff_id__isnull=True) | Q(responsible_staff_id="")
    )[:200]:
        # §25: derive from the member schools only when they agree.
        owners = set(
            School.objects.filter(cluster_id=cluster.id, deleted_at__isnull=True)
            .exclude(account_owner_id__isnull=True)
            .exclude(account_owner_id="")
            .values_list("account_owner_id", flat=True)[:50]
        )
        rows.append(
            {
                "cluster": cluster.name,
                "district": getattr(cluster.district, "name", "—"),
                "expected": "an active staff owner",
                "actual": "none",
                "member_owners": sorted(owners)[:5],
                "resolution": (
                    "Adopt the single owner its schools share."
                    if len(owners) == 1
                    else "No cluster is offered to anybody until an owner is set."
                    if not owners
                    else "Members have different owners — split or review."
                ),
            }
        )
    return _finding(
        key="cluster_without_owner",
        label="Clusters with no staff owner",
        severity="high",
        expected="Every active cluster has one active staff owner",
        classification=REPAIRABLE,
        rows=rows,
        route="/clusters",
    )


def _clusters_owned_by_inactive_staff() -> dict:
    from apps.clusters.models import Cluster

    live = _active_staff_ids()
    rows = [
        {
            "cluster": c.name,
            "district": getattr(c.district, "name", "—"),
            "expected": "an active staff owner",
            "actual": f"owner {c.responsible_staff_id} is not active",
            "resolution": "Transfer the cluster to an active owner.",
        }
        for c in Cluster.objects.filter(deleted_at__isnull=True)
        .exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
        .select_related("district")[:2000]
        if c.responsible_staff_id not in live
    ][:200]
    return _finding(
        key="cluster_owner_inactive",
        label="Clusters whose owner is no longer active",
        severity="high",
        expected="A cluster's owner is an active staff member",
        classification=MANUAL,
        rows=rows,
        route="/clusters",
    )


def _clusters_without_a_district() -> dict:
    from apps.clusters.models import Cluster

    rows = [
        {
            "cluster": c.name,
            "expected": "a district",
            "actual": "none",
            "resolution": "Set the district, or retire the cluster.",
        }
        for c in Cluster.objects.filter(deleted_at__isnull=True, district__isnull=True)[
            :200
        ]
    ]
    return _finding(
        key="cluster_without_district",
        label="Clusters with no district",
        severity="high",
        expected="Every cluster belongs to one district",
        classification=MANUAL,
        rows=rows,
        route="/clusters",
    )


# ── Membership ───────────────────────────────────────────────────────────────
def _membership_owner_mismatch() -> dict:
    """A school sitting in someone else's cluster.

    The condition the new rule refuses at every write, read against rows that
    predate it.
    """
    from apps.clusters.eligibility import owner_id_variants
    from apps.clusters.models import Cluster
    from apps.schools.lifecycle_service import active_schools

    clusters = {
        c.id: c
        for c in Cluster.objects.filter(deleted_at__isnull=True).select_related(
            "district", "sub_county"
        )
    }
    rows = []
    for school in (
        active_schools()
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .select_related("district", "sub_county")[:5000]
    ):
        cluster = clusters.get(school.cluster_id)
        if cluster is None:
            continue
        cluster_owner = (cluster.responsible_staff_id or "").strip()
        if not cluster_owner:
            continue
        if cluster_owner not in owner_id_variants(school.account_owner_id or ""):
            rows.append(
                {
                    "school": school.school_id,
                    "name": school.name,
                    "cluster": cluster.name,
                    "expected": f"a cluster owned by {school.account_owner_id}",
                    "actual": f"{cluster.name} is owned by {cluster_owner}",
                    "resolution": (
                        "End the membership and reassign, or transfer the "
                        "school. History is preserved either way."
                    ),
                }
            )
        if len(rows) >= 200:
            break
    return _finding(
        key="membership_owner_mismatch",
        label="Schools in another staff member's cluster",
        severity="high",
        expected="School owner and cluster owner are the same person",
        classification=MANUAL,
        rows=rows,
        route="/clusters",
    )


def _membership_geography_mismatch() -> dict:
    from apps.clusters.models import Cluster
    from apps.schools.lifecycle_service import active_schools

    clusters = {
        c.id: c
        for c in Cluster.objects.filter(deleted_at__isnull=True).select_related(
            "district", "sub_county"
        )
    }
    rows = []
    for school in (
        active_schools()
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .select_related("district", "sub_county")[:5000]
    ):
        cluster = clusters.get(school.cluster_id)
        if cluster is None:
            continue
        if school.district_id and cluster.district_id != school.district_id:
            rows.append(
                {
                    "school": school.school_id,
                    "name": school.name,
                    "cluster": cluster.name,
                    "expected": f"a cluster in {getattr(school.district, 'name', '—')}",
                    "actual": f"{cluster.name} is in {getattr(cluster.district, 'name', '—')}",
                    "resolution": "End the membership; reassign in the right district.",
                }
            )
        elif (
            school.sub_county_id
            and cluster.sub_county_id
            and cluster.sub_county_id != school.sub_county_id
            and not cluster.covered_sub_counties.filter(
                sub_county_id=school.sub_county_id
            ).exists()
        ):
            rows.append(
                {
                    "school": school.school_id,
                    "name": school.name,
                    "cluster": cluster.name,
                    "expected": f"a cluster covering {getattr(school.sub_county, 'name', '—')}",
                    "actual": f"{cluster.name} covers {getattr(cluster.sub_county, 'name', '—')}",
                    "resolution": "End the membership; reassign in the right sub-county.",
                }
            )
        if len(rows) >= 200:
            break
    return _finding(
        key="membership_geography_mismatch",
        label="Schools in a cluster outside their district or sub-county",
        severity="high",
        expected="A school's cluster covers the ground the school stands on",
        classification=MANUAL,
        rows=rows,
        route="/clusters",
    )


def _duplicate_active_membership() -> dict:
    """`School.cluster_id` is the canonical membership, so duplicates can only
    appear in the legacy projection — where they are still read by older
    reports."""
    from apps.clusters.models import SchoolClusterAssignment

    dupes = (
        SchoolClusterAssignment.objects.values("school_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)[:200]
    )
    rows = [
        {
            "school": d["school_id"],
            "expected": "one active cluster membership",
            "actual": f"{d['n']} rows",
            "resolution": "Collapse to the canonical School.cluster_id.",
        }
        for d in dupes
    ]
    return _finding(
        key="duplicate_active_membership",
        label="Schools with more than one cluster-assignment row",
        severity="medium",
        expected="One active membership per school",
        classification=REPAIRABLE,
        rows=rows,
        route="/clusters",
    )


CHECKS = (
    _schools_without_a_district,
    _schools_without_an_owner,
    _schools_owned_by_a_pending_invite,
    _schools_owned_by_a_departed_or_unknown_person,
    _school_sub_county_outside_its_district,
    _clusters_without_an_owner,
    _clusters_owned_by_inactive_staff,
    _clusters_without_a_district,
    _membership_owner_mismatch,
    _membership_geography_mismatch,
    _duplicate_active_membership,
)


def report() -> dict:
    checks = [check() for check in CHECKS]
    issues = sum(c["count"] for c in checks)
    return {
        "clean": issues == 0,
        "issueCount": issues,
        "checks": checks,
        "repairable": sum(
            c["count"] for c in checks if c["classification"] == REPAIRABLE
        ),
        "manual": sum(c["count"] for c in checks if c["classification"] == MANUAL),
    }
