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

Owner, 2026-10-26: five more, each one of My Plan's tables
(``apps.my_plan.table_export``): Schools with Planned Training, Schools with
Planned Cluster Meeting, Core School Visits, Client School Visits and Core
Schools with Planned Trainings. Their activity types pick the work as any kind
does; the table then lists it exactly as My Plan does. And the Plan Status is
two choices: "All scheduled plans" (the work not yet completed) or "Scheduled
and completed plans".
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
TRAINING_SCHOOLS = "training_schools"
MEETING_SCHOOLS = "meeting_schools"
CORE_VISITS = "core_visits"
CLIENT_VISITS = "client_visits"
CORE_TRAININGS = "core_trainings"

#: The five lists of schools (owner, 2026-10-26), each one of My Plan's
#: tables (``apps.my_plan.table_export.KIND_TABLES``).
SCHOOL_LIST_CHOICES = (
    (TRAINING_SCHOOLS, "Schools with Planned Training"),
    (MEETING_SCHOOLS, "Schools with Planned Cluster Meeting"),
    (CORE_VISITS, "Core School Visits"),
    (CLIENT_VISITS, "Client School Visits"),
    (CORE_TRAININGS, "Core Schools with Planned Trainings"),
)
SCHOOL_LISTS = frozenset(key for key, _ in SCHOOL_LIST_CHOICES)

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
    *SCHOOL_LIST_CHOICES,
    (ALL, "All activities (meetings and events included)"),
)

#: The drawer's Plan Status, in its order (owner, 2026-10-26: "All Scheduled
#: Plans, scheduled and completed plans"); the first opens selected. They are
#: the export's own vocabulary, never an activity's status: ``scheduled`` is
#: the work not yet completed, ``all`` adds the completed work.
SCHEDULED = "scheduled"
STATUS_CHOICES = (
    (SCHEDULED, "All scheduled plans"),
    ("all", "Scheduled and completed plans"),
)
#: Every status an export still reads: the two the drawer offers, and the two
#: links sent before 2026-10-26 can still carry.
STATUS_LABELS = {
    **dict(STATUS_CHOICES),
    "completed": "Completed only",
    "in_progress": "In progress only",
}
#: The statuses that name a phase of live work.
LIVE_STATUSES = frozenset(k for k in STATUS_LABELS if k not in ("all", "completed"))


def keeps_status(choice: str, activity_status: str) -> bool:
    """Whether an activity in ``activity_status`` belongs to the drawer's
    Plan Status ``choice``: ``scheduled`` keeps the work not yet completed,
    ``completed`` the completed work, anything else everything."""
    from apps.core.activity_types import COMPLETED_WORK_STATUSES

    done = (activity_status or "") in COMPLETED_WORK_STATUSES
    if choice == "completed":
        return done
    if choice in (SCHEDULED, "in_progress"):
        return not done
    return True


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
    # A list of schools picks the work its My Plan table is drawn from; the
    # table then decides each row (``apps.my_plan.table_export``).
    TRAINING_SCHOOLS: frozenset(TRAINING_TYPES),
    MEETING_SCHOOLS: frozenset(CLUSTER_MEETING_TYPES),
    CORE_VISITS: frozenset(VISIT_TYPES) | frozenset(TRAINING_TYPES),
    CLIENT_VISITS: frozenset(VISIT_TYPES),
    CORE_TRAININGS: frozenset(TRAINING_TYPES) | frozenset(VISIT_TYPES),
}
KINDS = frozenset(_TYPES) | {ALL}


#: Planning Oversight's activity tabs (``?activity=``,
#: ``oversight_service.ACTIVITY_FAMILIES``) as kinds. Its Group Trainings tab
#: holds every training type, in-school ones too, so it is ``trainings``.
TAB_KINDS = {"visits": VISITS, "meetings": MEETINGS, "trainings": TRAININGS}
#: How the drawer names ``trainings``, offered when the page's tab chose it.
TRAININGS_CHOICE = (TRAININGS, "Trainings only (group and in-school)")


def read_kind(source) -> str:
    """The kind a request (or any mapping with ``get``) asks for; a blank or
    unknown value is the whole page."""
    query = getattr(source, "GET", source)
    kind = (query.get("activity_type") or "").strip().lower()
    return kind if kind in KINDS else ALL


def tab_kind(source) -> str | None:
    """The kind Planning Oversight's activity tab narrowed the page to, or
    None for All Activities (owner, 2026-10-19: "When i select Visit only it
    was exporting everything")."""
    query = getattr(source, "GET", source)
    return TAB_KINDS.get((query.get("activity") or "").strip().lower())


def read_kind_or_tab(source) -> str:
    """The drawer's kind when it sent one, else the page's tab: the plain
    Export link and an old bookmark carry the tab alone."""
    query = getattr(source, "GET", source)
    if (query.get("activity_type") or "").strip():
        return read_kind(query)
    return tab_kind(query) or ALL


def choices_for(kind: str | None) -> tuple:
    """The drawer's choices, with ``trainings`` added after group trainings
    when the page's tab asks for it."""
    if kind != TRAININGS:
        return KIND_CHOICES
    at = [value for value, _ in KIND_CHOICES].index(GROUP_TRAININGS) + 1
    return (*KIND_CHOICES[:at], TRAININGS_CHOICE, *KIND_CHOICES[at:])


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
