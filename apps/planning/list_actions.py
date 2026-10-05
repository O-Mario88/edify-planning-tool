"""What a school on a drill-down list offers the person reading it.

Owner, 2026-10-05, of the lists the plan summaries open: "the list should
have the action buttons with schedule or assign for school that need to be
scheduled or assigned ... and for schools that need rescheduling should be in
the action button. double schedule (staff and partner) list should have
option for the staff to cancel and other actions needed and ensure group
actions can be applied to those schools and tables and lists as well."

A list row is a school (apps.planning.planning_monitor.SchoolState). `offer`
reads, for the rows on the page, what the Planning page would offer on the
same school and puts it on the row as ``row.acts``:

* Schedule and Assign, by the same gate as a Planning row
  (apps.planning.visit_gate), each greyed with the gate's own reason;
* Reschedule and Cancel for the staff work already planned there, through
  the single drawer for one activity and the group drawer for several;
* Withdraw from the Partner, where a hand-over is still open: with Cancel,
  the two ways out of a school booked by staff and a Partner both;
* the ids its tick box carries, so the bar's Reschedule, Cancel and Assign
  act on every ticked school.

Only for the reader's own schools. A supervisor reads a colleague's school
and is offered nothing here (§1B); the monitor keeps its "Send to" for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Staff work that is still a plan, so it can be moved or called off.
_OPEN_STAFF_STATUSES = ("planned", "scheduled", "rescheduled")


@dataclass
class RowActions:
    mine: bool = False
    schedule_url: str = ""
    schedule_reason: str = ""
    assign_url: str = ""
    assign_reason: str = ""
    #: (id, label, day) of each open staff activity at the school.
    activities: list = field(default_factory=list)
    reschedule_url: str = ""
    cancel_url: str = ""
    withdraw_url: str = ""

    @property
    def activity_ids(self) -> str:
        return ",".join(a[0] for a in self.activities)

    @property
    def can_tick(self) -> bool:
        """Something the bar can do with the row: move or cancel its work,
        or hand the school to a Partner."""
        return bool(self.activities or self.assign_url)

    @property
    def any(self) -> bool:
        return bool(
            self.schedule_url
            or self.schedule_reason
            or self.assign_url
            or self.assign_reason
            or self.activities
            or self.withdraw_url
        )


def offer(schools, principal, fy: str) -> bool:
    """Set ``acts`` on each of these SchoolStates; whether any row has
    something to tick."""
    from apps.activities.models import Activity
    from apps.core.permissions import RolePermissionService
    from apps.core.scoping import owner_ids
    from apps.partners.models import PartnerAssignment
    from apps.planning.visit_gate import visit_gates

    rows = list(schools)
    for row in rows:
        row.acts = RowActions()
    if not rows:
        return False
    mine = {str(i) for i in owner_ids(principal) if i}
    profile = getattr(principal, "staff_profile_id", None)
    if profile:
        mine.add(str(profile))
    own = [row for row in rows if str(row.officer_id) in mine]
    if not own:
        return False

    may_schedule = RolePermissionService.can_open_schedule_drawer(principal)
    may_assign = RolePermissionService.can_assign_to_partner(principal)
    may_withdraw = RolePermissionService.can_view_page(principal, "partner_oversight")
    may_move = RolePermissionService.can_view_page(principal, "my_plan")
    gates = {}
    if may_schedule or may_assign:
        from apps.schools.models import School

        # The gate reads the school's own record (a Core school's package).
        gates = visit_gates(School.objects.filter(id__in=[row.id for row in own]), fy)

    planned: dict[str, list] = {}
    if may_move:
        for activity in (
            Activity.objects.filter(
                school_id__in=[row.id for row in own],
                deleted_at__isnull=True,
                fy=str(fy),
                delivery_type="staff",
                status__in=_OPEN_STAFF_STATUSES,
                responsible_staff_id__in=mine,
            )
            .order_by("planned_date", "id")
            .only(
                "id",
                "school_id",
                "activity_type",
                "activity_name_snapshot",
                "planned_date",
            )
        ):
            planned.setdefault(activity.school_id, []).append(
                (
                    activity.id,
                    activity.activity_name_snapshot
                    or activity.get_activity_type_display(),
                    activity.planned_date,
                )
            )
    handovers: dict[str, str] = {}
    if may_withdraw:
        for school_id, assignment_id in (
            PartnerAssignment.objects.filter(
                school_id__in=[row.id for row in own],
                status__in=(
                    *PartnerAssignment.UNSCHEDULED_STATUSES,
                    PartnerAssignment.STATUS_PARTNER_SCHEDULED,
                    PartnerAssignment.STATUS_SCHEDULED,
                ),
            )
            .order_by("created_at")
            .values_list("school_id", "id")
        ):
            handovers.setdefault(school_id, assignment_id)

    for row in own:
        acts = row.acts
        acts.mine = True
        gate = gates.get(row.id)
        code = row.code or row.id
        if may_schedule and gate is not None:
            if gate.staff_locked:
                acts.schedule_reason = gate.staff_locked_reason or "Not available."
            else:
                acts.schedule_url = f"/planning/schedule-modal?school_id={code}"
        if may_assign and gate is not None:
            if gate.can_assign_partner:
                acts.assign_url = f"/planning/assign-partner-modal?school_id={code}"
            else:
                acts.assign_reason = gate.assign_reason or "Not available."
        acts.activities = planned.get(row.id, [])
        if len(acts.activities) == 1:
            only = acts.activities[0][0]
            acts.reschedule_url = f"/my-plan/{only}/reschedule-drawer"
            acts.cancel_url = f"/my-plan/{only}/cancel-drawer"
        elif acts.activities:
            acts.reschedule_url = (
                f"/activity-selection/reschedule?ids={acts.activity_ids}"
            )
            acts.cancel_url = f"/activity-selection/cancel?ids={acts.activity_ids}"
        if row.id in handovers:
            acts.withdraw_url = (
                f"/partner-oversight/withdraw?assignment_id={handovers[row.id]}"
            )
    return any(row.acts.can_tick for row in own)
