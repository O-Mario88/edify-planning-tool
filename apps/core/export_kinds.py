"""What work an export holds: visits, group trainings, cluster meetings,
online trainings, visits and trainings together, or everything.

Owner, 2026-10-12: "modify the export drawer for users to decide what they
want to export (Only group training, Only visit, only cluster meeting, only
online meeting or All)". One vocabulary, read by every Export options drawer
and applied by every export route, so "group trainings only" means the same
rows on Planning Oversight, My Plan, Partner Oversight, the Budget and the
Weekly Advance Request. (Cluster Oversight's plans export moved to Planning
Oversight on 2026-10-17, when that page became analysis only.)

The kinds are the platform's own groupings (``apps.core.activity_types``). A
group training is a cluster training, in person or online
(``apps.budget.costing.CLUSTER_TRAINING_TYPES``); an online training is a
group training whose ``programme_delivery_mode`` is online
(``apps.activities.online_training``) — the one kind that is not an activity
type, so a reader hands over the ids of the online activities among its rows.
"""

from __future__ import annotations

from apps.budget.costing import CLUSTER_TRAINING_TYPES
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

ALL = "all"
PLANNED = "planned"
VISITS_TRAININGS = "visits_trainings"
VISITS = "visits"
GROUP_TRAININGS = "group_trainings"
TRAININGS = "trainings"
MEETINGS = "meetings"
ONLINE = "online"

#: The drawer's choices, in its order. ``planned`` opens selected: the plan
#: is "only planned activities (visits and trainings and cluster meetings)
#: with dates of activity and their budget" (owner, 2026-10-12), so the
#: default leaves out the programme events and the general work only.
#: ``trainings`` (group and in-school together) is kept for the links that
#: already ask for it.
KIND_CHOICES = (
    (PLANNED, "Visits, trainings & cluster meetings"),
    (VISITS_TRAININGS, "Visits & trainings"),
    (VISITS, "Visits only"),
    (GROUP_TRAININGS, "Group trainings only"),
    (MEETINGS, "Cluster meetings only"),
    (ONLINE, "Online trainings only"),
    (ALL, "All activities (meetings and events included)"),
)

#: The drawer's plan statuses, by their key. They are the export's own
#: vocabulary (``scheduled`` is live work, moved or not, read through each
#: page's own phase), never an activity's status.
STATUS_LABELS = {
    "all": "All planned activities",
    "completed": "Completed only",
    "scheduled": "Scheduled / live only",
    "in_progress": "In progress only",
}
#: The statuses that name a phase of live work.
LIVE_STATUSES = frozenset(k for k in STATUS_LABELS if k not in ("all", "completed"))

_TYPES = {
    PLANNED: frozenset(VISIT_TYPES)
    | frozenset(TRAINING_TYPES)
    | frozenset(CLUSTER_MEETING_TYPES),
    VISITS_TRAININGS: frozenset(VISIT_TYPES) | frozenset(TRAINING_TYPES),
    VISITS: frozenset(VISIT_TYPES),
    GROUP_TRAININGS: frozenset(CLUSTER_TRAINING_TYPES),
    TRAININGS: frozenset(TRAINING_TYPES),
    MEETINGS: frozenset(CLUSTER_MEETING_TYPES),
    ONLINE: frozenset(CLUSTER_TRAINING_TYPES),
}
KINDS = frozenset(_TYPES) | {ALL}


def read_kind(source) -> str:
    """The kind a request (or any mapping with ``get``) asks for; a blank or
    unknown value is the whole page."""
    query = getattr(source, "GET", source)
    kind = (query.get("activity_type") or "").strip().lower()
    return kind if kind in KINDS else ALL


def keeps(kind: str, activity_type, *, online: bool = False) -> bool:
    """Whether work of ``activity_type`` is of this kind. ``online`` says the
    activity is delivered online; only the online kind reads it."""
    types = _TYPES.get(kind)
    if types is None:
        return True
    if (activity_type or "") not in types:
        return False
    return online if kind == ONLINE else True


def online_activity_ids(activity_ids) -> set:
    """The ids among ``activity_ids`` that are online group trainings, in one
    query, for a reader whose rows do not say so themselves."""
    from apps.activities.models import Activity
    from apps.activities.online_training import ONLINE_TRAINING

    ids = [i for i in set(activity_ids) if i]
    if not ids:
        return set()
    return set(
        Activity.objects.filter(id__in=ids)
        .filter(ONLINE_TRAINING)
        .values_list("id", flat=True)
    )


def filter_items(items, kind: str, *, type_of, id_of):
    """The items of this kind. ``type_of`` and ``id_of`` read an item's
    activity type and activity id; the online lookup runs only when asked."""
    items = list(items)
    if kind not in _TYPES:
        return items
    online = online_activity_ids(id_of(i) for i in items) if kind == ONLINE else set()
    return [
        i for i in items if keeps(kind, type_of(i), online=(id_of(i) or "") in online)
    ]


def label(kind: str) -> str:
    return dict(KIND_CHOICES).get(kind, "All activities")
