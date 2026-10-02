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

Not credited here, each for its reason:

* cluster sessions — `cluster_credit` owns them (one session, many schools);
* the companion visit an in-school training creates — it is the training;
* donor, content/story, invitation and social visits — not package support
  (owner, 2026-09-30), and unlimited wherever they are planned;
* the work of a project no SSA intervention measures (owner, 2026-10-02:
  Alumni "is not an intervention ... it should not restrict another project
  from being assigned to that school") — it takes no slot and no side of the
  split (`apps.projects.models.measured_by_ssa`);
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
NON_PACKAGE_VISIT_TYPES = frozenset(
    {"donor_visit", "story_gathering_visit", "school_invitation", "social_visit"}
)
NON_PACKAGE_VISIT_PURPOSES = frozenset(
    {"donor_visit", "story_gathering", "school_invitation", "social_visit"}
)

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


def package_kind_for(
    activity_type: str | None,
    purpose_type: str | None = None,
    *,
    cluster_id=None,
) -> str | None:
    """ "visit", "training", or None, for work of this shape at a Core School.

    Read from the shape alone so a door can ask before the activity exists.
    """
    if cluster_id:
        return None
    purpose = str(purpose_type or "")
    if purpose == COMPANION_VISIT_PURPOSE or purpose in NON_PACKAGE_VISIT_PURPOSES:
        return None
    activity_type = str(activity_type or "")
    if activity_type in PACKAGE_VISIT_TYPES:
        return "visit"
    if activity_type in PACKAGE_TRAINING_TYPES:
        return "training"
    return None


def package_kind(activity) -> str | None:
    """ "visit", "training", or None when this work is not package work."""
    return package_kind_for(
        activity.activity_type, activity.purpose_type, cluster_id=activity.cluster_id
    )


def package_work_q(kind: str | None = None, prefix: str = "") -> Q:
    """Activities that are package work of ``kind`` (both kinds when None) —
    `package_kind_for` as a filter. Status and deletion are the caller's."""
    p = prefix
    if kind == "visit":
        types = PACKAGE_VISIT_TYPES
    elif kind == "training":
        types = PACKAGE_TRAINING_TYPES
    else:
        types = PACKAGE_VISIT_TYPES | PACKAGE_TRAINING_TYPES
    return (
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
    if activity.status in UNCREDITED_STATUSES or package_kind(activity) is None:
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

    The package of the work's own fiscal year. With none, a later year's work
    goes to the school's live package — the FY restriction on core scheduling
    was lifted on 2026-09-17, so a package's work may land in the next year —
    but an earlier year's work is never credited to a later package.
    """
    from apps.core.fy import get_operational_fy
    from apps.core_schools.models import CorePlan
    from apps.core_schools.services import (
        CORE_PLAN_CLOSED_STATUSES,
        get_live_core_plan,
    )

    school = activity.school
    fy = str(activity.fy or "")
    plan = (
        CorePlan.objects.filter(school_id=school.school_id, fy=fy)
        .exclude(status__in=CORE_PLAN_CLOSED_STATUSES)
        .first()
        if fy
        else None
    )
    if plan is not None:
        return plan
    if fy and fy < get_operational_fy():
        return None
    return get_live_core_plan(school.school_id)


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
    kind = package_kind(activity)
    if kind is None or outside_package(activity.project_id):
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


def uncredited_package_work(*, fy: str | None = None, school_code: str | None = None):
    """Live visits and trainings at Core Schools that fill no package slot —
    what `credit_school_activity` would link. For the backfill command."""
    from apps.activities.models import Activity
    from apps.core_schools.models import CoreActivitySlot

    qs = (
        Activity.objects.filter(deleted_at__isnull=True, school__school_type="core")
        .filter(package_work_q())
        .filter(not_outside_package_q())
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
    None too for the hand-over of a project outside the package."""
    if outside_package(getattr(assignment, "project_id", None)):
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
    from apps.core_schools.services import get_live_core_plan, resync_plan_completion

    school = assignment.school
    if school is None or school.school_type != "core" or _names_its_slot(assignment):
        return None
    kind = assignment_kind(assignment)
    if kind is None:
        return None
    with transaction.atomic():
        plan = get_live_core_plan(school.school_id)
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


def release_assignment_slot(assignment, *, replacement=None):
    """Give back the slot a handover held, now that the partner no longer
    holds the work — withdrawn by staff, or returned by the partner.

    A slot the partner had not dated goes back to the package, open to be
    scheduled again; with a ``replacement`` handover it passes to the new
    partner instead. A slot the partner had dated is left to its activity:
    cancelling that activity is what frees it (the Activity -> slot mirror).
    """
    from apps.core_schools.services import resync_plan_completion

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
    ``core_visit`` before 2026-09-30, or one credited before that rule."""
    from apps.activities.models import Activity
    from apps.core_schools.models import CoreActivitySlot

    outreach = Activity.all_objects.filter(
        Q(activity_type__in=sorted(NON_PACKAGE_VISIT_TYPES))
        | Q(purpose_type__in=sorted(NON_PACKAGE_VISIT_PURPOSES))
    ).values("id")
    return list(
        CoreActivitySlot.objects.filter(activity_id__in=outreach).select_related(
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
    "uncredited_package_work",
]
