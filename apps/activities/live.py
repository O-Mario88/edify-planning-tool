"""Tell every open page that shows the plan when the plan changes.

Owner, 2026-10-05, of the group reschedule and cancel: "This should happen in
real time", and then: "Every event should update (schedules, school
withdrawal from the partner or project, training schedules, activity
completion etc) should update in real time and fast."

The stream was already there: `apps.realtime` keeps one bounded queue per
user, shared across web replicas over Redis, and serves it at
``GET /api/realtime/stream``. Nothing in the browser listened to it. This
module is the sending half: what counts as a change, who is told, and what
they are told.

**What counts.** Any save or delete of an activity, of a school's or a
cluster's hand-over to a partner, or of a school's place in a project. The
records say so themselves (`connect` hangs this on their signals), so a door
added later announces without being taught to: scheduling, rescheduling,
cancelling, starting, completing, verifying, handing over, withdrawing.

**What they are told** is next to nothing: a ``plan.changed`` event with the
time. The page that hears it reads itself again from the server
(static/js/live-regions.js), so each reader sees the change through their own
scope and no detail of anyone's work travels in the event.

**Who is told** is everyone whose pages show the record: the person
responsible and the staff member monitoring, the people they report to,
whoever holds the school or the cluster, the partner, the project's
coordinator, and the readers with the whole country in view.

Sent after the change commits and never allowed to undo it: a stream that
cannot be reached leaves a page stale, which the next visit puts right. One
commit that saves a hundred activities sends each person one event, and the
audience of a school is worked out once a minute, not once a save.
"""

from __future__ import annotations

import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

EVENT = "plan.changed"

#: How far up the reporting line a change is announced: the officer's
#: Program Lead and the person the lead reports to.
_LEVELS_UP = 2
#: A reader who was away learns on their return that something changed
#: (`last_change`). A day covers a tab left open overnight.
_STAMP_SECONDS = 60 * 60 * 24
#: How long an audience is remembered. A new reporting line or a school
#: handed on is heard of within the minute.
_AUDIENCE_SECONDS = 60.0
_AUDIENCE_KEPT = 2000
#: One commit saves many records and each asks to be announced; a person
#: already told a moment ago is not told again. Shorter than the pause the
#: page takes before it reads itself again, so nothing committed is missed.
_QUIET_SECONDS = 0.3

_audiences: dict[tuple, tuple[float, frozenset[str]]] = {}
_audiences_lock = threading.Lock()
_told = threading.local()


def enabled() -> bool:
    """Off under the test runner, where it would add its queries to every
    query count in the suite; its own tests turn it on."""
    return bool(getattr(settings, "LIVE_UPDATES_ENABLED", True))


def _stamp_key(user_id: str) -> str:
    return f"live:plan:{user_id}"


def last_change(user_id: str) -> str | None:
    """When the plan this user sees last changed, as the stream's own ISO
    time; None if nothing has since the stamp was last kept."""
    try:
        return cache.get(_stamp_key(user_id))
    except Exception:  # noqa: BLE001 - a cache outage leaves a page stale, no more
        return None


def announce_activity(activity) -> None:
    """An activity was saved or deleted."""
    announce(
        staff_ids=(
            activity.responsible_staff_id,
            getattr(activity, "monitored_by_staff_id", None),
        ),
        school_id=activity.school_id,
        cluster_id=activity.cluster_id,
        project_id=activity.project_id,
        partner_ids=(
            activity.assigned_partner_id,
            getattr(activity, "facilitating_partner_id", None),
        ),
    )


def announce(
    *,
    staff_ids=(),
    school_id=None,
    cluster_id=None,
    project_id=None,
    partner_ids=(),
) -> None:
    """Push ``plan.changed`` to everyone these belong to, once the change
    has committed."""
    if not enabled():
        return
    key = (
        tuple(sorted({str(i) for i in staff_ids if i})),
        str(school_id or ""),
        str(cluster_id or ""),
        str(project_id or ""),
        tuple(sorted({str(i) for i in partner_ids if i})),
    )
    transaction.on_commit(lambda: _publish(key))


def audience(
    *, staff_ids=(), school_id=None, cluster_id=None, project_id=None, partner_ids=()
) -> frozenset[str]:
    """The user ids of everyone whose pages show a record with these."""
    from django.db.models import Q

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User

    staff = {str(i) for i in staff_ids if i}
    if school_id:
        from apps.schools.models import School

        staff.add(
            School.objects.filter(id=school_id)
            .values_list("account_owner_id", flat=True)
            .first()
        )
    if cluster_id:
        from apps.clusters.models import Cluster

        staff.add(
            Cluster.objects.filter(id=cluster_id)
            .values_list("responsible_staff_id", flat=True)
            .first()
        )
    if project_id:
        from apps.projects.models import Project

        staff.add(
            Project.objects.filter(id=project_id)
            .values_list("manager_staff_id", flat=True)
            .first()
        )
    staff.discard(None)
    staff.discard("")

    users: set[str] = set()
    # An owner is written as a StaffProfile id or as a User id
    # (apps.core.scoping.owner_ids): read both.
    line: set[str] = set()
    if staff:
        for profile_id, user_id in StaffProfile.objects.filter(
            Q(id__in=staff) | Q(user_id__in=staff)
        ).values_list("id", "user_id"):
            line.add(profile_id)
            if user_id:
                users.add(user_id)
    known = set(line)
    for _ in range(_LEVELS_UP):
        if not line:
            break
        above = set()
        for profile_id, user_id in StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=line
        ).values_list("supervisor_id", "supervisor__user_id"):
            if profile_id and profile_id not in known:
                above.add(profile_id)
                if user_id:
                    users.add(user_id)
        known |= above
        line = above

    partners = [i for i in partner_ids if i]
    if partners:
        from apps.partners.models import Partner

        users.update(
            Partner.objects.filter(id__in=partners, user_id__isnull=False).values_list(
                "user_id", flat=True
            )
        )

    from apps.core.scoping import COUNTRY_SCHEDULING_ROLES

    users.update(
        User.objects.filter(
            active_role__in=COUNTRY_SCHEDULING_ROLES, is_active=True
        ).values_list("id", flat=True)
    )
    return frozenset(str(user) for user in users if user)


def _audience_for(key: tuple) -> frozenset[str]:
    now = time.monotonic()
    with _audiences_lock:
        kept = _audiences.get(key)
        if kept and now - kept[0] < _AUDIENCE_SECONDS:
            return kept[1]
    staff_ids, school_id, cluster_id, project_id, partner_ids = key
    found = audience(
        staff_ids=staff_ids,
        school_id=school_id,
        cluster_id=cluster_id,
        project_id=project_id,
        partner_ids=partner_ids,
    )
    with _audiences_lock:
        if len(_audiences) >= _AUDIENCE_KEPT:
            _audiences.clear()
        _audiences[key] = (now, found)
    return found


def _publish(key: tuple) -> None:
    try:
        user_ids = _audience_for(key)
    except Exception:  # noqa: BLE001 - announcing never breaks the change
        logger.warning("live audience failed", exc_info=True)
        return
    now = time.monotonic()
    told = getattr(_told, "at", None)
    if told is None or len(told) > 5000:
        told = _told.at = {}
    due = [user for user in user_ids if now - told.get(user, -1.0) >= _QUIET_SECONDS]
    if not due:
        return
    for user in due:
        told[user] = now

    from apps.realtime.bus import bus

    at = timezone.now().isoformat()
    try:
        cache.set_many({_stamp_key(user): at for user in due}, timeout=_STAMP_SECONDS)
    except Exception:  # noqa: BLE001
        logger.debug("live stamp not kept", exc_info=True)
    try:
        bus.publish_many(due, {"type": EVENT, "at": at})
    except Exception:  # noqa: BLE001 - committed work stays committed
        logger.warning("live push failed", exc_info=True)


def reset() -> None:
    """Forget remembered audiences and who was just told (tests)."""
    with _audiences_lock:
        _audiences.clear()
    _told.at = {}


# ── The records that announce themselves ─────────────────────────────────────


def _activity_changed(sender, instance, **kwargs):
    announce_activity(instance)


def _partner_assignment_changed(sender, instance, **kwargs):
    announce(
        staff_ids=(
            instance.assigning_staff_id,
            getattr(instance, "monitoring_staff_id", None),
        ),
        school_id=instance.school_id,
        cluster_id=instance.cluster_id,
        project_id=getattr(instance, "project_id", None),
        partner_ids=(instance.partner_id,),
    )


def _project_school_changed(sender, instance, **kwargs):
    announce(
        staff_ids=(instance.assigned_staff_id, instance.assigned_by),
        school_id=instance.school_id,
        project_id=instance.project_id,
    )


def connect() -> None:
    """Hang the announcement on the records' own signals."""
    from django.db.models.signals import post_delete, post_save

    watched = (
        ("activities.Activity", _activity_changed),
        ("partners.PartnerAssignment", _partner_assignment_changed),
        ("projects.ProjectSchoolAssignment", _project_school_changed),
    )
    for sender, receiver in watched:
        uid = f"live:{sender}"
        post_save.connect(receiver, sender=sender, dispatch_uid=f"{uid}:save")
        post_delete.connect(receiver, sender=sender, dispatch_uid=f"{uid}:delete")
