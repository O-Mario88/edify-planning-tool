"""Add a school to a scheduled cluster session at once (owner, 2026-10-27).

"Add new school to the training … save and add to the cluster and training
immediately … It should also allow users to add already existing school."

A school found in Edify, or one just typed in through the Add New School form,
joins the session's cluster and is invited to the session in one step. The
cluster move goes through `set_school_cluster_membership`, so the portfolio
rule holds (a school joins only a cluster held by the person responsible for
it); the invitation goes through `editing.edit`, so the training ceiling, the
head count, the cost and a sent fund request follow exactly as when a box is
ticked in the Edit drawer and saved. Either refusal undoes both.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q

from apps.core.exceptions import BadRequest, Forbidden

#: Shortest search the Edit drawer's "+ Add School" runs (school IDs are short
#: numbers), and how many schools it lists.
SEARCH_MIN = 2
SEARCH_LIMIT = 8


def open_session(activity_id: str, principal):
    """The cluster session, when the reader may still edit it; else refused."""
    from apps.activities import editing
    from apps.activities.models import Activity

    activity = (
        Activity.objects.select_related("cluster")
        .filter(id=activity_id, deleted_at__isnull=True)
        .first()
    )
    if activity is None or not editing.is_cluster_session(activity):
        raise BadRequest("Only a cluster training or meeting invites schools.")
    state = editing.edit_state(activity, principal)
    if state == "locked":
        raise BadRequest(editing.LOCKED_REASON)
    if state != "open":
        raise Forbidden("This session is not yours to change.")
    return activity


def _invited_ids(activity) -> list[str]:
    from apps.activities.models import ClusterActivityAttendance

    return list(
        ClusterActivityAttendance.objects.filter(
            activity=activity, invited=True
        ).values_list("school_id", flat=True)
    )


def _assert_may_be_invited(school) -> None:
    from apps.planning.visit_gate import OWN_TABLE_SCHOOL_TYPES
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    if school.operational_status not in OPERATING_STATUSES:
        raise BadRequest(f"{school.name} is closed, so it cannot be invited.")
    if school.school_type in OWN_TABLE_SCHOOL_TYPES:
        raise BadRequest(
            "Champion schools receive no cluster training or meeting, so "
            "they cannot be invited to this session."
        )


def add_school_to_session(activity_id: str, school_pk: str, principal):
    """Put the school in the session's cluster and invite it. Returns the
    school; a school already invited is left as it is."""
    from apps.activities import editing
    from apps.audit.services import log as audit_log
    from apps.clusters.services import set_school_cluster_membership
    from apps.schools.models import School

    activity = open_session(activity_id, principal)
    school = School.objects.filter(id=school_pk, deleted_at__isnull=True).first()
    if school is None:
        raise BadRequest("That school is not in Edify.")
    _assert_may_be_invited(school)

    actor_id = str(getattr(principal, "id", "") or "")
    actor_role = getattr(principal, "active_role", "") or ""
    with transaction.atomic():
        joined = school.cluster_id != activity.cluster_id
        if joined:
            school = set_school_cluster_membership(
                school,
                activity.cluster,
                actor_id,
                reason=f"Added to the session on {activity.planned_date}.",
                actor_role=actor_role,
            )
        invited = _invited_ids(activity)
        if school.id in invited:
            return school
        editing.edit(
            activity.id, {"invitedSchoolIds": [*invited, school.id]}, principal
        )
        audit_log(
            action="activity.school_added",
            subject_kind="Activity",
            subject_id=str(activity.id),
            actor_id=actor_id,
            actor_role=actor_role,
            payload={
                "school_id": school.id,
                "cluster_id": activity.cluster_id,
                "joined_cluster": joined,
            },
        )
    return school


def school_row(school, *, invited: bool, notice: str = "") -> dict:
    """What the Edit drawer needs to list a school it just added."""
    return {
        "id": school.id,
        "name": school.name,
        "schoolId": school.school_id,
        "invited": invited,
        "notice": notice
        or f"{school.name} is in this cluster and invited to this session.",
    }


def invite_new_school(school, activity, principal) -> dict:
    """The row for a school just typed in from a session's Edit drawer: put
    in the session's cluster, it is invited at once; put elsewhere, it is
    saved where it was put and the drawer says why it is not invited."""
    from apps.clusters.models import Cluster

    cluster_name = activity.cluster.name
    if school.cluster_id != activity.cluster_id:
        put_in = (
            Cluster.objects.filter(id=school.cluster_id)
            .values_list("name", flat=True)
            .first()
            or "no cluster"
        )
        return school_row(
            school,
            invited=False,
            notice=(
                f"{school.name} is saved in {put_in}. Only schools in "
                f"{cluster_name} are invited to this session."
            ),
        )
    try:
        add_school_to_session(activity.id, school.id, principal)
    except (BadRequest, Forbidden) as exc:
        return school_row(
            school,
            invited=False,
            notice=f"{school.name} is saved in {cluster_name} but not invited: {exc}",
        )
    return school_row(school, invited=True)


def addable_schools(activity, principal, query: str) -> list:
    """Schools in Edify this session can take: operating, not Champion, not
    already in its cluster, and held by the cluster's officer (the only
    schools `set_school_cluster_membership` lets join it)."""
    from apps.clusters.eligibility import owner_id_variants
    from apps.planning.visit_gate import OWN_TABLE_SCHOOL_TYPES
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    query = (query or "").strip()[:80]
    if len(query) < SEARCH_MIN:
        return []
    holder = (activity.cluster.responsible_staff_id or "").strip() or str(
        getattr(principal, "staff_profile_id", "") or ""
    )
    owners = owner_id_variants(holder)
    if not owners:
        return []
    from apps.clusters.models import Cluster

    schools = list(
        School.objects.filter(
            deleted_at__isnull=True,
            operational_status__in=OPERATING_STATUSES,
            account_owner_id__in=owners,
        )
        .exclude(school_type__in=OWN_TABLE_SCHOOL_TYPES)
        .exclude(cluster_id=activity.cluster_id)
        .filter(
            Q(name__icontains=query)
            | Q(school_id__icontains=query)
            | Q(salesforce_account_id__iexact=query)
        )
        .select_related("district")
        .order_by("name")[:SEARCH_LIMIT]
    )
    names = dict(
        Cluster.objects.filter(
            id__in={s.cluster_id for s in schools if s.cluster_id}
        ).values_list("id", "name")
    )
    for school in schools:
        school.cluster_name = names.get(school.cluster_id, "")
    return schools
