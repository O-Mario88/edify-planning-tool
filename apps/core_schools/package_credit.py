"""A Core School's visits and trainings count toward its package, wherever
they were scheduled.

Owner, 2026-09-27: "make sure all core planned whether through cluster, or
through planning page core school tab or through core school page all reflect
on core school visit plan and core training plan and counted as V1 or v2 or
v3 ... irrespective of where the visits scheduling or training scheduling is
done from. the packages should be counted."

The package is counted from its slots (`CorePackageSchedulingService`), and
My Plan numbers a row V1..V4 / T1..T4 from the slot the activity fills. Three
routes already link a slot as they book: the Core Schools drawers, the
Planning drawer's core visit routing (`visit_routing`) and a partner dating a
Core Schools handover. Cluster sessions are credited to invited schools by
`cluster_credit`. Everything else that puts a visit or a training on a Core
School — autopilot, a field debrief's follow-up, catch-up plans, the API, a
Planning-page partner handover — made an activity with no slot, so the school
was visited and the package never heard of it.

This is the catch-all behind them: once the transaction that saved the
activity commits, an unlinked visit or training at a Core School takes the
package's next open slot of its kind. It runs after commit on purpose. The
routes above create the activity first and link their chosen slot a moment
later in the same transaction; by the time this runs they have, and it finds
the activity already linked and does nothing. Nothing here refuses work — the
2 + 2 split belongs to the doors that create it (`package_split`).

Special Project work at a Core School counts too (owner, 2026-09-30: "all
scheduling visit or training can contribute to the core school packages").
It stays costed and reported as the project's; it also takes the package slot
its visit or training fills.

An in-school training is a training AND a visit (owner, 2026-10-03: at a Core
School it should "record the visit package V1, V2, V3, V4 and training
package T1, T2, T3, T4"). The Training takes the package's next training slot
and the School Visit written beside it the next visit slot, each on the half
of whoever delivers it (`slot_kind`). Until then the companion visit took no
slot, so the school read one training and no visit for a day that was both.
No door refuses the pair over the visit half: a door asks `package_kind_for`,
which still reads the companion visit as outside the package, the way it
reads SSA Support whose deliverer it does not know.

Not credited here, each for its reason:

* donor, content/story, invitation and social visits — not package support
  (owner, 2026-09-30), and unlimited wherever they are planned;
* data collection (SSA Support) visits — "those visits don't count" (owner,
  2026-10-02), and unlimited too;
* a group training planned through the school's cluster — it does count
  (owner, 2026-10-02), and is credited apart, by `cluster_credit`, on the half
  of whoever delivers it; a cluster meeting is not a training and takes no
  slot;
* the work of a project no SSA intervention measures (owner, 2026-10-02:
  Alumni "is not an intervention ... it should not restrict another project
  from being assigned to that school") — it takes no slot and no side of the
  split (`apps.projects.models.measured_by_ssa`);
* a universal training, which is SSA Training (owner, 2026-10-06: "School
  Improvement Planning training is universal every schools can attend ...
  Core gets 4 training ... ontop of School improvement training", and
  "School improvement Planning is actually SSA training") — it is on top of
  the package's four, so it takes no training slot and is on neither half,
  and the School Visit an in-school delivery writes beside it takes no visit
  slot (`apps.planning.training_entitlement`);
* work at a school whose package is for an earlier year than the work's own —
  a past year's visit is not this year's V1.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Q

from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES
from apps.core.clock import local_day
from apps.planning.visit_gate import (
    COMPANION_VISIT_PURPOSE,
    DEAD_STATUSES,
    FOLLOW_UP_VISIT_TYPES,
    NOT_YET_PLANNED_STATUSES,
)

logger = logging.getLogger(__name__)

#: Visits that are not package support (owner, 2026-09-30): donor visits,
#: content/story gathering, school invitations and social visits have no limit
#: and never take one of the package's four visits. Both spellings, because a
#: Core Schools visit booked before the rule carries the purpose on a
#: ``core_visit`` row rather than the visit's own type.
OUTREACH_VISIT_TYPES = frozenset(
    {"donor_visit", "story_gathering_visit", "school_invitation", "social_visit"}
)
OUTREACH_VISIT_PURPOSES = frozenset(
    {"donor_visit", "story_gathering", "school_invitation", "social_visit"}
)
#: Data collection (SSA Support). Owner, 2026-10-03: "SSA should be part of
#: the core package v1-v4" and "Staff scheduled SSA Support for both core and
#: clients schools counts towards the core visit package"; "if it is assigned
#: to the partner it does not count". So an SSA Support visit STAFF schedule
#: is a package visit, on the staff half, and one handed to a Partner takes
#: no slot and is on neither half. (From 2026-10-02 until then it was outside
#: the package for everybody.) Nothing refuses one: a door that asks before
#: the activity exists does not say who delivers it, reads it as outside the
#: package and applies no limit; the visit takes its slot when it is saved.
DATA_COLLECTION_VISIT_TYPES = frozenset(
    {"school_visit_ssa_collection", "baseline_ssa_visit", "partner_ssa_collection"}
)
DATA_COLLECTION_VISIT_PURPOSES = frozenset({"ssa_support"})
#: What a door that does not know the deliverer treats as outside the package.
NON_PACKAGE_VISIT_TYPES = OUTREACH_VISIT_TYPES | DATA_COLLECTION_VISIT_TYPES
NON_PACKAGE_VISIT_PURPOSES = OUTREACH_VISIT_PURPOSES | DATA_COLLECTION_VISIT_PURPOSES

#: The visit family — the same set the Core Schools drawer turns into a core
#: visit, and the one `backfill_core_school_visits` converts.
PACKAGE_VISIT_TYPES = frozenset(
    (set(FOLLOW_UP_VISIT_TYPES) | set(PURPOSE_ACTIVITY_TYPES.values()) | {"core_visit"})
    - {"in_school_training"}
    - NON_PACKAGE_VISIT_TYPES
)
#: A training delivered AT the school (a cluster session is credited apart).
PACKAGE_TRAINING_TYPES = frozenset(str(t) for t in SCHOOL_TRAINING_TYPES)

#: Statuses in which work does not hold a slot: abandoned, or a visit request
#: the school's owner has not approved yet (it is linked when they do).
UNCREDITED_STATUSES = frozenset(DEAD_STATUSES) | frozenset(NOT_YET_PLANNED_STATUSES)


def _is_staff(delivery_type) -> bool:
    return delivery_type is not None and str(delivery_type) != "partner"


def is_data_collection_shape(activity_type, purpose_type) -> bool:
    return (
        str(activity_type or "") in DATA_COLLECTION_VISIT_TYPES
        or str(purpose_type or "") in DATA_COLLECTION_VISIT_PURPOSES
    )


def package_kind_for(
    activity_type: str | None,
    purpose_type: str | None = None,
    *,
    cluster_id=None,
    delivery_type: str | None = None,
) -> str | None:
    """ "visit", "training", or None, for work of this shape at a Core School.

    Read from the shape alone so a door can ask before the activity exists.
    ``delivery_type`` is who delivers it, when the caller knows: SSA Support
    is a package visit for staff, and outside the package for a Partner or
    for a caller that does not say.
    """
    if cluster_id:
        return None
    purpose = str(purpose_type or "")
    if purpose == COMPANION_VISIT_PURPOSE or purpose in OUTREACH_VISIT_PURPOSES:
        return None
    activity_type = str(activity_type or "")
    if activity_type in OUTREACH_VISIT_TYPES:
        return None
    if is_data_collection_shape(activity_type, purpose):
        return "visit" if _is_staff(delivery_type) else None
    if activity_type in PACKAGE_VISIT_TYPES:
        return "visit"
    if activity_type in PACKAGE_TRAINING_TYPES:
        return "training"
    return None


def _names_universal_course(activity) -> bool:
    from apps.planning.training_entitlement import names_universal_course

    return names_universal_course(activity)


def package_kind(activity) -> str | None:
    """ "visit", "training", or None when this work is not package work."""
    if _names_universal_course(activity):
        return None
    return package_kind_for(
        activity.activity_type,
        activity.purpose_type,
        cluster_id=activity.cluster_id,
        delivery_type=activity.delivery_type or "staff",
    )


def slot_kind_for(
    activity_type: str | None,
    purpose_type: str | None = None,
    *,
    cluster_id=None,
    delivery_type: str | None = None,
) -> str | None:
    """The package slot SAVED work of this shape takes, and the half it is
    counted on: `package_kind_for`, plus the School Visit an in-school
    training writes beside itself, which is a package visit (owner,
    2026-10-03). The doors keep asking `package_kind_for`, so the pair is
    never refused over the visit half."""
    if not cluster_id and str(purpose_type or "") == COMPANION_VISIT_PURPOSE:
        return "visit"
    return package_kind_for(
        activity_type,
        purpose_type,
        cluster_id=cluster_id,
        delivery_type=delivery_type,
    )


def slot_kind(activity) -> str | None:
    """ "visit", "training", or None: the slot this saved work takes. A
    universal training takes none. The visit written beside one is told apart
    where the package is read (`credit_school_activity`), not here: this is
    asked on every save and that visit is found through its training."""
    if _names_universal_course(activity):
        return None
    return slot_kind_for(
        activity.activity_type,
        activity.purpose_type,
        cluster_id=activity.cluster_id,
        delivery_type=activity.delivery_type or "staff",
    )


def staff_data_collection_q(prefix: str = "") -> Q:
    """Staff's own SSA Support at a school: a package visit."""
    p = prefix
    return (
        (
            Q(**{f"{p}activity_type__in": sorted(DATA_COLLECTION_VISIT_TYPES)})
            | Q(**{f"{p}purpose_type__in": sorted(DATA_COLLECTION_VISIT_PURPOSES)})
        )
        & ~Q(**{f"{p}delivery_type": "partner"})
        & Q(**{f"{p}cluster__isnull": True})
        & ~Q(**{f"{p}activity_type__in": sorted(OUTREACH_VISIT_TYPES)})
        & ~Q(
            **{
                f"{p}purpose_type__in": sorted(
                    {COMPANION_VISIT_PURPOSE, *OUTREACH_VISIT_PURPOSES}
                )
            }
        )
    )


def package_work_q(kind: str | None = None, prefix: str = "") -> Q:
    """Activities that are package work of ``kind`` (both kinds when None) —
    `slot_kind_for` as a filter. Status and deletion are the caller's."""
    p = prefix
    if kind == "visit":
        types = PACKAGE_VISIT_TYPES
    elif kind == "training":
        types = PACKAGE_TRAINING_TYPES
    else:
        types = PACKAGE_VISIT_TYPES | PACKAGE_TRAINING_TYPES
    ordinary = (
        Q(**{f"{p}activity_type__in": sorted(types)})
        & Q(**{f"{p}cluster__isnull": True})
        & ~Q(
            **{
                f"{p}purpose_type__in": sorted(
                    {COMPANION_VISIT_PURPOSE, *NON_PACKAGE_VISIT_PURPOSES}
                )
            }
        )
    )
    if kind == "training":
        return ordinary
    # The visit an in-school training writes beside itself is a package
    # visit (owner, 2026-10-03), whatever type it was written with.
    companion = Q(**{f"{p}purpose_type": COMPANION_VISIT_PURPOSE}) & Q(
        **{f"{p}cluster__isnull": True}
    )
    return ordinary | staff_data_collection_q(p) | companion


def outside_package(project_id) -> bool:
    """Whether work of this project is outside the package: a project no SSA
    intervention measures (Alumni). False for work of no project."""
    if not project_id:
        return False
    from apps.projects.models import is_outside_ssa

    return is_outside_ssa(project_id)


def not_outside_package_q(prefix: str = "") -> Q:
    """Rows that are not the work of a project outside the package —
    `outside_package` as a filter, for activities and hand-overs alike."""
    from apps.projects.models import projects_outside_ssa

    outside = list(projects_outside_ssa())
    if not outside:
        return Q()
    return ~Q(**{f"{prefix}project_id__in": outside})


def schedule_package_credit(activity) -> None:
    """Ask for this activity to be credited once its transaction commits.

    Cheap on purpose — `Activity.save` calls it on every save — so only the
    shape of the row is read here; the school and the package are read after
    commit, by `credit_school_activity`.
    """
    if not activity.school_id or activity.deleted_at is not None:
        return
    if activity.status in UNCREDITED_STATUSES or slot_kind(activity) is None:
        return
    if outside_package(activity.project_id):
        return
    activity_id = activity.id
    transaction.on_commit(lambda: _credit_safely(activity_id))


def _credit_safely(activity_id: str) -> None:
    # After commit: a failure here must not surface as an error on a request
    # whose work was saved, but it must be seen.
    try:
        credit_school_activity(activity_id)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Core package credit failed for activity %s", activity_id, exc_info=True
        )


def plan_for_activity(activity):
    """The Core package this work belongs to, or None.

    The package of the work's own fiscal year, made if this is the first work
    planned into that year (``services.ensure_core_plan``; owner, 2026-10-02).
    It used to fall back to the school's newest package, which filed October's
    work in last year's. An earlier year's work is never credited to a later
    package, and a year that has passed is not given a package after the fact.
    """
    from apps.core.fy import get_operational_fy
    from apps.core_schools.models import CorePlan
    from apps.core_schools.services import CORE_PLAN_CLOSED_STATUSES, ensure_core_plan

    school = activity.school
    fy = str(activity.fy or "")
    if not fy:
        return None
    if fy < get_operational_fy():
        return (
            CorePlan.objects.filter(school_id=school.school_id, fy=fy)
            .exclude(status__in=CORE_PLAN_CLOSED_STATUSES)
            .first()
        )
    return ensure_core_plan(school, fy)


def _open_slot(plan, slots, kind: str, activity):
    """The slot this work takes: the one a partner holds for it, else the
    package's next open one, else a new one past the fourth — the package's
    ceiling was lifted on 2026-09-17, and work that has happened is counted,
    not refused. ``slots`` are the plan's slots of this kind, locked."""
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
    )
    from apps.core_schools.models import CoreActivitySlot, cslot_id
    from apps.core_schools.services import CORE_SLOT_KIND_TO_TYPE

    if activity.delivery_type == "partner" and activity.assigned_partner_id:
        held = next(
            (
                slot
                for slot in slots
                if (slot.status or "").strip().lower() == "assigned"
                and slot.assigned_partner_id == activity.assigned_partner_id
                and not slot.activity_id
            ),
            None,
        )
        if held is not None:
            return held
    for slot in slots:
        if not CorePackageSchedulingService.status_is_taken(slot.status):
            return slot

    letter = next(k for k, value in CORE_SLOT_KIND_TO_TYPE.items() if value == kind)
    sequence = max((s.sequence_number for s in slots), default=0) + 1
    slot, _created = CoreActivitySlot.objects.get_or_create(
        id=cslot_id(plan.school_id, letter, sequence, fy=plan.fy),
        defaults={
            "core_plan": plan,
            "school_id": plan.school_id,
            "intervention": (plan.interventions or ["christlike_behaviour"])[0],
            "activity_type": kind,
            "sequence_number": sequence,
        },
    )
    return slot


def credit_school_activity(activity_id: str):
    """Link this visit or training to its Core School's package, if it is
    package work and holds no slot yet. Returns the slot linked, or None.

    Idempotent: work already in a slot — by this pass or by the route that
    booked it — is left exactly where it is.
    """
    from apps.activities.models import Activity
    from apps.core_schools.core_planning_services import core_slot_status
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.services import resync_plan_completion

    activity = Activity.objects.select_related("school").filter(id=activity_id).first()
    if activity is None or activity.deleted_at is not None:
        return None
    school = activity.school
    if school is None or school.school_type != "core":
        return None
    if activity.status in UNCREDITED_STATUSES:
        return None
    kind = slot_kind(activity)
    if kind is None or outside_package(activity.project_id):
        return None
    from apps.planning.training_entitlement import activity_is_universal

    if activity_is_universal(activity):
        # The visit a universal training wrote beside itself: on top of the
        # package, like its training.
        return None

    if CoreActivitySlot.objects.filter(activity_id=activity.id).exists():
        return None

    with transaction.atomic():
        plan = plan_for_activity(activity)
        if plan is None:
            return None
        slots = list(
            plan.slots.select_for_update()
            .filter(activity_type=kind)
            .order_by("sequence_number")
        )
        # Asked again under the lock: two commits crediting the same activity
        # both found it unlinked above, and the second must not take a second
        # slot once the first has linked one.
        if CoreActivitySlot.objects.filter(activity_id=activity.id).exists():
            return None
        slot = _open_slot(plan, slots, kind, activity)
        from apps.evidence.models import EvidenceRecord

        when = (
            local_day(activity.scheduled_date)
            if activity.scheduled_date
            else activity.planned_date
        )
        slot.activity_id = activity.id
        slot.status = core_slot_status(activity.status)
        slot.owner = "partner" if activity.delivery_type == "partner" else "staff"
        slot.assigned_staff_id = activity.responsible_staff_id
        if activity.assigned_partner_id:
            slot.assigned_partner_id = activity.assigned_partner_id
        slot.scheduled_for = when
        slot.scheduled_month = (
            str(activity.planned_month) if activity.planned_month else None
        )
        slot.scheduled_week = activity.planned_week
        if activity.salesforce_activity_id:
            slot.salesforce_id = activity.salesforce_activity_id
        if not slot.evidence_uri:
            slot.evidence_uri = (
                EvidenceRecord.objects.filter(
                    activity_id=activity.id, quarantined=False
                )
                .order_by("-created_at")
                .values_list("uri", flat=True)
                .first()
            )
        slot.save()
        resync_plan_completion(plan)
    return slot


def release_work(activity_ids) -> int:
    """Give back the package slots this work holds, because it has stopped
    being package work — a training renamed as a universal one, with the
    visit written beside it. Returns how many slots went back. The work
    itself is not touched: only which slot points at it."""
    from apps.core_schools.cluster_credit import _release
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.services import resync_plan_completion

    ids = [activity_id for activity_id in activity_ids if activity_id]
    if not ids:
        return 0
    plans = {}
    released = 0
    with transaction.atomic():
        for slot in (
            CoreActivitySlot.objects.select_for_update(of=("self",))
            .filter(activity_id__in=ids)
            .select_related("core_plan")
        ):
            _release(slot)
            released += 1
            plans[slot.core_plan_id] = slot.core_plan
        for plan in plans.values():
            resync_plan_completion(plan)
    return released


def uncredited_package_work(*, fy: str | None = None, school_code: str | None = None):
    """Live visits and trainings at Core Schools that fill no package slot —
    what `credit_school_activity` would link. For the backfill command."""
    from apps.activities.models import Activity
    from apps.core_schools.models import CoreActivitySlot

    from apps.planning.training_entitlement import not_universal_q

    qs = (
        Activity.objects.filter(deleted_at__isnull=True, school__school_type="core")
        .filter(package_work_q())
        .filter(not_outside_package_q())
        .filter(not_universal_q())
        .exclude(status__in=UNCREDITED_STATUSES)
        .exclude(
            id__in=CoreActivitySlot.objects.filter(activity_id__isnull=False).values(
                "activity_id"
            )
        )
        .select_related("school")
        .order_by("school__school_id", "planned_date", "created_at", "id")
    )
    if fy:
        qs = qs.filter(fy=str(fy))
    if school_code:
        qs = qs.filter(school__school_id=school_code)
    return qs


# ── Partner handovers ───────────────────────────────────────────────────────
#
# A Core Schools handover names its slot (support_type + visit_number or
# training_number) and `commit_assign` marks the slot "Assigned". A handover
# from the Planning page names none, so the package did not hear of it until
# the partner dated it. It now holds a slot from the moment it is made — the
# package counts it, and it reads V3 or T2 while it waits for the partner.
#
# The handover itself is not rewritten to name the slot: the one-open-handover
# rule (uniq_open_partner_school_assignment) compares those columns, and
# filling them would let the same school be handed to the same partner again.
# The slot is found from the partner holding it instead.


def assignment_kind(assignment) -> str | None:
    """ "visit" or "training" for a handover at a Core School, else None —
    None too for the hand-over of a project outside the package, and for the
    hand-over of a universal training."""
    if outside_package(getattr(assignment, "project_id", None)):
        return None
    from apps.planning.training_entitlement import is_universal

    if is_universal(getattr(assignment, "training_course_id", None)):
        # A universal training is on top of the package (owner, 2026-10-06):
        # its hand-over holds none of the partner's two.
        return None
    support = (assignment.support_type or "").strip().lower()
    if support in ("visit", "training"):
        return support
    if assignment.visit_number:
        return "visit"
    if assignment.training_number:
        return "training"
    if str(assignment.purpose_of_visit or "") in NON_PACKAGE_VISIT_PURPOSES:
        return None
    expected = str(assignment.expected_activity_type or "")
    if not expected and assignment.purpose_of_visit:
        expected = PURPOSE_ACTIVITY_TYPES.get(str(assignment.purpose_of_visit), "")
    if expected in PACKAGE_TRAINING_TYPES or expected == "in_school_training":
        return "training"
    if expected in PACKAGE_VISIT_TYPES:
        return "visit"
    return None


def _names_its_slot(assignment) -> bool:
    return bool(
        (assignment.support_type or "").strip()
        or assignment.visit_number
        or assignment.training_number
    )


def slot_held_by_assignment(assignment):
    """The package slot this handover holds, or None."""
    from apps.core_schools.models import CoreActivitySlot
    from apps.partners.models import PartnerAssignment

    school = assignment.school
    kind = assignment_kind(assignment)
    if school is None or school.school_type != "core" or kind is None:
        return None
    slots = CoreActivitySlot.objects.filter(
        school_id=school.school_id, activity_type=kind
    ).order_by("-core_plan__fy", "sequence_number")
    if _names_its_slot(assignment):
        number = (
            assignment.visit_number if kind == "visit" else assignment.training_number
        )
        try:
            sequence = int(number or 0)
        except ValueError:
            sequence = 0
        candidates = [s for s in slots.filter(sequence_number=sequence)]
        return next(
            (s for s in candidates if s.assigned_partner_id == assignment.partner_id),
            None,
        )
    # Unnamed: an "Assigned" slot this partner holds that no named handover of
    # theirs at this school accounts for.
    named = set()
    for other in PartnerAssignment.objects.filter(
        school_id=assignment.school_id,
        partner_id=assignment.partner_id,
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
    ).exclude(id=assignment.id):
        if _names_its_slot(other) and assignment_kind(other) == kind:
            number = other.visit_number if kind == "visit" else other.training_number
            try:
                named.add(int(number or 0))
            except ValueError:
                pass
    return next(
        (
            s
            for s in slots.filter(
                assigned_partner_id=assignment.partner_id, activity_id__isnull=True
            )
            if (s.status or "").strip().lower() == "assigned"
            and s.sequence_number not in named
        ),
        None,
    )


def reserve_for_assignment(assignment):
    """Hold the package's next open slot for a handover that names none.

    Returns the slot held, or None when the handover is not Core package
    work, already names its slot, or the package has no open slot left (the
    work is counted when the partner dates it, like any other).
    """
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
    )
    from apps.core_schools.services import ensure_core_plan, resync_plan_completion

    school = assignment.school
    if school is None or school.school_type != "core" or _names_its_slot(assignment):
        return None
    kind = assignment_kind(assignment)
    if kind is None:
        return None
    with transaction.atomic():
        # A hand-over has no date yet: it holds a slot of the running year's
        # package.
        plan = ensure_core_plan(school)
        if plan is None:
            return None
        slots = list(
            plan.slots.select_for_update()
            .filter(activity_type=kind)
            .order_by("sequence_number")
        )
        slot = next(
            (
                s
                for s in slots
                if not CorePackageSchedulingService.status_is_taken(s.status)
            ),
            None,
        )
        if slot is None:
            return None
        partner = getattr(assignment, "partner", None)
        slot.status = "Assigned"
        slot.activity_id = None
        slot.owner = "partner"
        slot.assigned_partner_id = assignment.partner_id
        slot.assigned_partner_name = getattr(partner, "name", None)
        slot.save()
        resync_plan_completion(plan)
    return slot


# ── Work that is called off ──────────────────────────────────────────────────
# Owner, 2026-10-08: "the cancelled activities should not remain counting for
# example if i scheduled school visits on core school and cancelled, it should
# stop counting and the v1 or v2 v3 or v4 should be reset back to the actual
# scheduled activities. Apply the same on training, T1, T2, T3, T4 display."
#
# A cancelled visit stopped being counted, but it stayed on its slot: with V1
# cancelled and V2 booked the package read "V1 not planned, V2 planned", and
# the slot still pointed at the cancelled visit. The slot now goes back to the
# package and the work that is live takes the first slots again, in the order
# it held them, so two visits read V1 and V2 whichever was cancelled.


def _is_taken(slot) -> bool:
    """Whether a slot is spoken for: filled by work that is still live —
    whatever stage it has reached — or held for a Partner who has not dated
    it. A slot left pointing at work that was called off is not."""
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.core_schools import package_year
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
        slot_state,
    )

    status = (slot.status or "").strip().lower()
    if slot.activity_id:
        return status not in NOT_IN_PLAN_ACTIVITY_STATUSES and not package_year.is_open(
            status
        )
    return slot_state(
        slot.status
    ) == "done" or CorePackageSchedulingService.status_is_taken(slot.status)


def close_gaps(plan, kind: str) -> dict[int, int]:
    """Renumber one kind of a package so its live work holds the first slots.

    The slots that are taken keep their order and move down over any that
    opened before them; the rest are open. A hand-over that names its slot
    (a Core Schools hand-over: "Visit 3") is renumbered with it, so the
    Partner dating it later still finds the slot it holds.

    Returns ``{old number: new number}`` for what moved; empty when the
    package already reads from its first slot. Call inside a transaction.
    """
    from apps.core_schools import package_year
    from apps.core_schools.models import CoreActivitySlot

    slots = list(
        CoreActivitySlot.objects.select_for_update(of=("self",))
        .filter(core_plan=plan, activity_type=kind)
        .order_by("sequence_number")
    )
    taken = [slot for slot in slots if _is_taken(slot)]
    if [slot.id for slot in taken] == [slot.id for slot in slots[: len(taken)]]:
        # No gap among the taken ones. A slot left linked to work that is no
        # longer live is still cleared, so nothing reads as held by it.
        for slot in slots[len(taken) :]:
            if slot.activity_id or not package_year.is_open(slot.status):
                package_year._clear(slot)
                slot.save()
        return {}
    work = [
        (
            {name: getattr(slot, name) for name in package_year.SLOT_WORK_FIELDS},
            slot.sequence_number,
        )
        for slot in taken
    ]
    moves: dict[int, int] = {}
    for position, slot in enumerate(slots):
        if position < len(work):
            fields, was = work[position]
            for name, value in fields.items():
                setattr(slot, name, value)
            if was != slot.sequence_number:
                moves[was] = slot.sequence_number
        else:
            package_year._clear(slot)
        slot.save()
    _renumber_named_handovers(plan, kind, moves)
    return moves


def _renumber_named_handovers(plan, kind: str, moves: dict[int, int]) -> None:
    """Keep the hand-overs that name a slot of this package on the slot they
    hold, after it has moved. Lowest new number first: the number each takes
    was given up by the one before it."""
    from apps.partners.models import PartnerAssignment
    from apps.schools.models import School

    if not moves:
        return
    school_ids = list(
        School.objects.filter(school_id=plan.school_id).values_list("id", flat=True)
    )
    field = "visit_number" if kind == "visit" else "training_number"
    named = [
        handover
        for handover in PartnerAssignment.objects.filter(school_id__in=school_ids)
        .exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
        .exclude(**{f"{field}__isnull": True})
        .exclude(**{field: ""})
        if assignment_kind(handover) == kind
    ]

    def number_of(handover) -> int:
        try:
            return int(getattr(handover, field) or 0)
        except ValueError:
            return 0

    for handover in sorted(named, key=lambda h: moves.get(number_of(h), 0)):
        target = moves.get(number_of(handover))
        if not target:
            continue
        try:
            with transaction.atomic():
                setattr(handover, field, str(target))
                handover.save(update_fields=[field, "updated_at"])
        except Exception:  # noqa: BLE001 - bookkeeping never blocks the release
            logger.warning(
                "Could not renumber hand-over %s to %s %s",
                handover.id,
                kind,
                target,
                exc_info=True,
            )


def give_back_slots(activity) -> int:
    """Give back the package slots held by work that has been called off —
    cancelled, rejected, deferred or no longer planned
    (``NOT_IN_PLAN_ACTIVITY_STATUSES``) — and renumber what is left
    (``close_gaps``). Returns how many slots went back.

    A visit waiting for its owner's approval keeps its slot: it is on its way
    into the plan, not out of it.

    Called on every save of an activity (``Activity.save``): for live work it
    does nothing.
    """
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.core_schools.cluster_credit import _release
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.services import resync_plan_completion

    if (activity.status or "") not in NOT_IN_PLAN_ACTIVITY_STATUSES:
        return 0
    with transaction.atomic():
        slots = list(
            CoreActivitySlot.objects.select_for_update(of=("self",))
            .filter(activity_id=activity.id)
            .select_related("core_plan")
        )
        packages = {}
        for slot in slots:
            _release(slot)
            packages[(slot.core_plan_id, slot.activity_type)] = slot.core_plan
        for (_plan_id, kind), plan in packages.items():
            close_gaps(plan, kind)
            resync_plan_completion(plan)
    return len(slots)


def hold_slot_again(assignment):
    """A hand-over whose date was undone is waiting again, and holds a place
    in its Core School's package as it did before the Partner dated it: the
    package's next open slot of its kind, marked Assigned. One that names its
    slot is renumbered to the slot it takes. Returns the slot, or None."""
    from apps.core_schools.core_planning_services import (
        CorePackageSchedulingService,
    )
    from apps.core_schools.services import ensure_core_plan, resync_plan_completion

    if not _names_its_slot(assignment):
        return reserve_for_assignment(assignment)
    school = assignment.school
    kind = assignment_kind(assignment)
    if school is None or school.school_type != "core" or kind is None:
        return None
    with transaction.atomic():
        plan = ensure_core_plan(school)
        if plan is None:
            return None
        slot = next(
            (
                candidate
                for candidate in plan.slots.select_for_update()
                .filter(activity_type=kind)
                .order_by("sequence_number")
                if not CorePackageSchedulingService.status_is_taken(candidate.status)
            ),
            None,
        )
        if slot is None:
            return None
        slot.status = "Assigned"
        slot.activity_id = None
        slot.owner = "partner"
        slot.assigned_partner_id = assignment.partner_id
        slot.assigned_partner_name = getattr(assignment.partner, "name", None)
        slot.save()
        field = "visit_number" if kind == "visit" else "training_number"
        if str(getattr(assignment, field) or "") != str(slot.sequence_number):
            setattr(assignment, field, str(slot.sequence_number))
            assignment.save(update_fields=[field, "updated_at"])
        resync_plan_completion(plan)
    return slot


def release_assignment_slot(assignment, *, replacement=None):
    """Give back the slot a handover held, now that the partner no longer
    holds the work — withdrawn by staff, or returned by the partner.

    A slot the partner had not dated goes back to the package, open to be
    scheduled again; with a ``replacement`` handover it passes to the new
    partner instead. A slot the partner had dated is left to its activity:
    cancelling that activity is what frees it (the Activity -> slot mirror).
    """
    from apps.core_schools.services import resync_plan_completion

    if getattr(assignment, "scheduled_activity_id", None):
        # Dated work holds its slot through its activity. Looking for one the
        # handover holds by itself could only find the slot of another
        # handover the same partner has at this school, and reopen that.
        return None
    slot = slot_held_by_assignment(assignment)
    if slot is None or slot.activity_id:
        return None
    if (slot.status or "").strip().lower() != "assigned":
        return None
    if replacement is not None:
        slot.assigned_partner_id = replacement.partner_id
        slot.assigned_partner_name = getattr(replacement.partner, "name", None)
    else:
        slot.status = "Planned"
        slot.owner = "unassigned"
        slot.assigned_partner_id = None
        slot.assigned_partner_name = None
        slot.assigned_staff_id = None
        slot.scheduled_for = None
        slot.scheduled_month = None
        slot.scheduled_week = None
    slot.save()
    resync_plan_completion(slot.core_plan)
    return slot


def non_package_slots():
    """Slots linked to a visit that is not package work — a donor, story,
    invitation or social visit the Core Schools drawer booked as a
    ``core_visit`` before 2026-09-30, or a Partner's data collection visit.
    Staff's own SSA Support keeps its slot (owner, 2026-10-03)."""
    from apps.activities.models import Activity
    from apps.core_schools.models import CoreActivitySlot

    outside = (
        Activity.all_objects.filter(
            Q(activity_type__in=sorted(NON_PACKAGE_VISIT_TYPES))
            | Q(purpose_type__in=sorted(NON_PACKAGE_VISIT_PURPOSES))
        )
        .exclude(staff_data_collection_q())
        .values("id")
    )
    return list(
        CoreActivitySlot.objects.filter(activity_id__in=outside).select_related(
            "core_plan"
        )
    )


def _open_slot_again(slot) -> None:
    slot.status = "Planned"
    slot.activity_id = None
    slot.owner = "unassigned"
    slot.assigned_staff_id = None
    slot.assigned_partner_id = None
    slot.assigned_partner_name = None
    slot.scheduled_for = None
    slot.scheduled_month = None
    slot.scheduled_week = None
    slot.salesforce_id = None
    slot.evidence_uri = None
    slot.save()


def stale_partner_slots():
    """Slots still "Assigned" to a partner who no longer holds any open
    handover at that school — withdrawn or returned before this module
    released them."""
    from apps.core_schools.models import CoreActivitySlot
    from apps.partners.models import PartnerAssignment

    held = CoreActivitySlot.objects.filter(
        activity_id__isnull=True, assigned_partner_id__isnull=False
    ).filter(status__iexact="assigned")
    open_pairs = set(
        PartnerAssignment.objects.filter(
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
            school__school_type="core",
        ).values_list("school__school_id", "partner_id")
    )
    return [
        slot
        for slot in held
        if (slot.school_id, slot.assigned_partner_id) not in open_pairs
    ]


def unreserved_core_handovers():
    """Open handovers at Core Schools that hold no package slot."""
    from apps.partners.models import PartnerAssignment

    handovers = PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        school__school_type="core",
        school__deleted_at__isnull=True,
    ).select_related("school", "partner")
    return [
        h
        for h in handovers
        if not _names_its_slot(h)
        and assignment_kind(h) is not None
        and slot_held_by_assignment(h) is None
    ]


def repair_package_links(*, apply: bool, fy=None, school_code=None) -> dict:
    """Bring the packages up to date with the work already on the calendar.

    Three passes, in this order so a slot released by the first can be used
    by the next two: slots held for partners who let the work go are given
    back; waiting Planning-page handovers take a slot; and live visits and
    trainings with no slot are linked, oldest first, so V1 is the earliest.
    Dry run unless ``apply``. Returns what was (or would be) done.
    """
    from apps.core_schools.services import resync_plan_completion

    report = {"released": [], "reserved": [], "credited": [], "unplaced": []}

    # Donor, story, invitation and social visits give their slots back (owner,
    # 2026-09-30): they are not package work.
    for slot in non_package_slots():
        if school_code and slot.school_id != school_code:
            continue
        report["released"].append(slot.id)
        if apply:
            _open_slot_again(slot)
            resync_plan_completion(slot.core_plan)

    for slot in stale_partner_slots():
        if school_code and slot.school_id != school_code:
            continue
        report["released"].append(slot.id)
        if apply:
            slot.status = "Planned"
            slot.owner = "unassigned"
            slot.assigned_partner_id = None
            slot.assigned_partner_name = None
            slot.scheduled_for = None
            slot.scheduled_month = None
            slot.scheduled_week = None
            slot.save()
            resync_plan_completion(slot.core_plan)

    for handover in unreserved_core_handovers():
        if school_code and handover.school.school_id != school_code:
            continue
        if apply:
            slot = reserve_for_assignment(handover)
            if slot is None:
                report["unplaced"].append(handover.id)
                continue
        report["reserved"].append(handover.id)

    for activity in uncredited_package_work(fy=fy, school_code=school_code):
        if not apply:
            if plan_for_activity(activity) is None:
                report["unplaced"].append(activity.id)
            else:
                report["credited"].append(activity.id)
            continue
        slot = credit_school_activity(activity.id)
        if slot is None:
            report["unplaced"].append(activity.id)
        else:
            report["credited"].append(activity.id)
    return report


__all__ = [
    "NON_PACKAGE_VISIT_PURPOSES",
    "NON_PACKAGE_VISIT_TYPES",
    "OUTREACH_VISIT_PURPOSES",
    "OUTREACH_VISIT_TYPES",
    "staff_data_collection_q",
    "PACKAGE_TRAINING_TYPES",
    "PACKAGE_VISIT_TYPES",
    "UNCREDITED_STATUSES",
    "assignment_kind",
    "credit_school_activity",
    "non_package_slots",
    "package_kind",
    "package_kind_for",
    "package_work_q",
    "plan_for_activity",
    "release_assignment_slot",
    "repair_package_links",
    "reserve_for_assignment",
    "schedule_package_credit",
    "slot_held_by_assignment",
    "slot_kind",
    "slot_kind_for",
    "uncredited_package_work",
]
