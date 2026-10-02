"""Which planned work may still be changed (owner, 2026-10-02).

"Only planned activities that are still at scheduled mode should be editable.
Activities that are already [executed and completed] should have the greyed
out disabled button."

An activity is a plan until somebody starts delivering it. From then on its
day, its schools and its purpose are a record of what happened, and the record
changes only through the workflow that owns it: completion, a reviewer's
return, a budget amendment, a cancellation with its reason.

This module is the one place that says where that line is. The Edit drawer,
the Reschedule drawer and ``apps.activities.services.reschedule`` all ask it,
so a button is never offered for something the service would refuse.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

#: Still a plan the planner may change: dated, not yet started.
EDITABLE_STATUSES = frozenset({"planned", "scheduled", "rescheduled"})

#: Started or delivered. ``completed`` is the legacy delivered value; the
#: rest are the completion and review steps and what follows them.
EXECUTED_STATUSES = frozenset(
    {
        "in_progress",
        "completion_started",
        "evidence_uploaded",
        "evidence_accepted",
        "salesforce_id_required",
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "accountant_confirmed",
        "completed",
        "closed",
    }
)


def is_executed(activity) -> bool:
    """Whether delivery of this activity has started or finished."""
    return (getattr(activity, "status", "") or "") in EXECUTED_STATUSES


def is_editable(activity) -> bool:
    """Whether this activity is staff work that is still only a plan.

    Partner-delivered work is the partner's to date and change, from its own
    plan; it is not edited here.
    """
    return (getattr(activity, "status", "") or "") in EDITABLE_STATUSES and getattr(
        activity, "delivery_type", ""
    ) != "partner"


def assert_not_executed(activity, *, action: str = "changed") -> None:
    """Refuse a change to work that has started or been delivered."""
    if is_executed(activity):
        raise BadRequest(
            f"This activity has already been carried out, so it can no longer "
            f"be {action}. Only an activity that is still scheduled can be."
        )


#: Types whose place in a school's Core package is a numbered slot. Such work
#: belongs to that school's package and is not moved to another school.
_PACKAGE_SLOT_TYPES = frozenset(
    {"core_visit", "core_training", "core_assessment_visit"}
)


def assert_editable(activity) -> None:
    """Refuse to edit anything that is not staff work still on the plan."""
    assert_not_executed(activity, action="edited")
    if getattr(activity, "delivery_type", "") == "partner":
        raise BadRequest(
            "A partner delivers this activity and changes it from its own plan."
        )
    if (getattr(activity, "status", "") or "") not in EDITABLE_STATUSES:
        raise BadRequest(
            "Only an activity that is still scheduled can be edited. This one "
            f"is {str(activity.status or 'not planned').replace('_', ' ')}."
        )


def is_cluster_session(activity) -> bool:
    """A cluster training or meeting: it invites member schools by name."""
    return bool(activity.cluster_id) and not activity.school_id


def may_move_school(activity) -> bool:
    """Whether Edit offers this single-school activity another school."""
    return (
        bool(activity.school_id)
        and (activity.activity_type or "") not in _PACKAGE_SLOT_TYPES
    )


def movable_schools(activity, principal):
    """The schools a planner may move this activity to: their own operating
    portfolio, which is the set a new plan there would be accepted for."""
    from apps.core.scoping import resolve_user_scope, school_queryset
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return (
        school_queryset(resolve_user_scope(principal), direct_only=True)
        .filter(deleted_at__isnull=True, operational_status__in=OPERATING_STATUSES)
        .order_by("name")
    )


def may_change_project(activity) -> bool:
    """Whether Edit offers this activity another project: project work at one
    school that holds no numbered place in the school's Core package."""
    return (
        bool(activity.project_id)
        and bool(activity.school_id)
        and (activity.activity_type or "") not in _PACKAGE_SLOT_TYPES
    )


def project_interventions(project) -> list[tuple[str, str]]:
    """The interventions a project is linked to, as the Edit drawer offers
    them (owner, 2026-10-02: "they should be able to select an intervention
    the new project is linked to").

    A project that states its targets offers exactly those: CC-SEL Secondary
    offers Christlike Behaviour, Alumni offers General. One that states none
    measures against any, so it offers every SSA intervention.
    """
    from apps.core.enums import SsaIntervention
    from apps.projects.models import PROJECT_INTERVENTION_CHOICES

    labels = dict(PROJECT_INTERVENTION_CHOICES)
    targets = [code for code in project.target_intervention_list() if code in labels]
    if not targets:
        return list(SsaIntervention.choices)
    return [(code, labels[code]) for code in targets]


def changeable_projects(activity, principal) -> list:
    """The projects this activity may be filed under: its own first, then
    every open project the school is in, then the ones it may still join
    (`projects_open_for_enrolment`, the list "Add to Project" offers)."""
    from apps.projects.models import OPEN_PROJECT_STATUSES, Project
    from apps.projects.services import projects_open_for_enrolment

    if not may_change_project(activity):
        return []
    current = Project.objects.filter(id=activity.project_id).first()
    enrolled = list(
        Project.objects.filter(
            deleted_at__isnull=True,
            status__in=[status.value for status in OPEN_PROJECT_STATUSES],
            school_assignments__school_id=activity.school_id,
        )
        .exclude(id=activity.project_id)
        .distinct()
        .order_by("name")
    )
    joinable = [
        project
        for project in projects_open_for_enrolment(principal, activity.school)
        if project.id != activity.project_id
    ]
    return [*([current] if current else []), *enrolled, *joinable]


def _clean_focus(raw, project) -> str | None:
    """The focus a form posted, read against the project it is filed under.

    General is a project's way of saying no SSA intervention measures its
    work, so an activity under it carries no focus. Anything else must be an
    intervention the project is linked to.
    """
    from apps.projects.models import GENERAL_INTERVENTION

    focus = str(raw or "").strip()
    if not focus or focus == GENERAL_INTERVENTION:
        return None
    if project is not None:
        offered = dict(project_interventions(project))
        if focus not in offered:
            linked = ", ".join(
                label for code, label in offered.items() if code != GENERAL_INTERVENTION
            )
            raise BadRequest(
                f"'{project.name}' is not linked to that intervention. "
                + (f"Choose {linked}." if linked else "It is a General project.")
            )
    return focus


def edit(activity_id: str, data: dict, principal) -> dict:
    """Change a planned activity (owner, 2026-10-02).

    "The users should be able to edit and change the activities, add or
    remove schools, change dates which should ask them for reason to
    reschedule … only planned activities that are still at scheduled mode
    should be editable."

    ``data`` carries only what the form posts; a key that is absent is left
    as it is:

    * ``scheduledDate`` (and ``endDate``) — a new day. Moving it needs
      ``reason`` and goes through ``services.reschedule``, so every date rule,
      the re-pricing and the partner notices are that function's. An
      in-school Training and its School Visit move together.
    * ``invitedSchoolIds`` — the member schools a cluster session invites
      (``cluster_attendance.set_invited_schools``: the head count and the
      price follow the ticks).
    * ``schoolId`` — another school for a single-school activity. Needs
      ``reason``. The activity is cancelled with that reason and scheduled
      again at the new school through the scheduling service, so the visit
      caps, the package rules and the costing of the new school all apply;
      both steps land or neither does.
    * ``projectId`` — another project for project work at one school
      (owner, 2026-10-02: "if a user wants to change a project to another
      they should be able to select an intervention the new project is linked
      to"). Needs ``reason``. Like a move to another school it is cancelled
      and scheduled again, under the new project, so the allowance and
      package rules read the project it now belongs to: Alumni work uses no
      support visit and no package place, CC-SEL work does. A school that is
      not in the new project yet joins it through ``projects.assign_school``.
      ``focusIntervention`` is then one the new project is linked to; General
      is no SSA focus.
    * ``facilitatingPartnerId`` — who facilitates a training or cluster
      meeting; blank is Staff (``services.set_facilitator``).
    * ``activityPurposeText``, ``expectedOutcome``, ``focusIntervention`` —
      ``services.patch_activity``.

    Returns the serialised activity — the new one after a move.
    """
    from django.db import transaction

    from apps.activities import services
    from apps.core.clock import local_day

    activity = services._get_for_execution(activity_id, principal)
    services._assert_may_schedule(activity, principal)
    services._assert_not_awaiting_owner(activity)
    assert_editable(activity)

    reason = str(data.get("reason") or "").strip()
    current_day = activity.planned_date or local_day(activity.scheduled_date)
    new_day = current_day
    if data.get("scheduledDate"):
        new_day = local_day(services._parse_date(data["scheduledDate"]))
    date_moves = new_day != current_day
    end_raw = str(data.get("endDate") or "").strip()
    end_moves = (
        bool(end_raw)
        and activity.end_date is not None
        and local_day(services._parse_date(end_raw)) != activity.end_date
    )

    new_school = None
    if "schoolId" in data and activity.school_id:
        wanted = str(data.get("schoolId") or "").strip()
        if wanted and wanted not in (activity.school_id, activity.school.school_id):
            if not may_move_school(activity):
                raise BadRequest(
                    "This activity holds a place in its school's Core package "
                    "and stays with that school. Cancel it and schedule the "
                    "other school from Core Schools."
                )
            from django.db.models import Q

            new_school = (
                movable_schools(activity, principal)
                .filter(Q(id=wanted) | Q(school_id=wanted))
                .first()
            )
            if new_school is None:
                raise BadRequest(
                    "Choose a school in your own portfolio to move this activity to."
                )

    new_project = None
    if "projectId" in data and activity.project_id:
        wanted_project = str(data.get("projectId") or "").strip()
        if wanted_project and wanted_project != activity.project_id:
            new_project = next(
                (
                    project
                    for project in changeable_projects(activity, principal)
                    if project.id == wanted_project
                ),
                None,
            )
            if new_project is None:
                raise BadRequest(
                    "Choose a project this school is in, or one it can join."
                )

    if (date_moves or end_moves) and not reason:
        raise BadRequest("Give the reason the date is changing.")
    if new_school is not None and not reason:
        raise BadRequest("Give the reason this activity is moving to another school.")
    if new_project is not None and not reason:
        raise BadRequest("Give the reason this activity is moving to another project.")

    patch = {
        key: data[key]
        for key in ("activityPurposeText", "expectedOutcome", "focusIntervention")
        if key in data
    }
    if "focusIntervention" in patch:
        # Read against the project the activity ends up under, so a focus
        # left over from the old project is refused rather than carried.
        filed_under = new_project
        if filed_under is None and activity.project_id:
            from apps.projects.models import Project

            filed_under = Project.objects.filter(id=activity.project_id).first()
        focus = str(patch["focusIntervention"] or "").strip()
        if focus == (activity.focus_intervention or "") and new_project is None:
            patch.pop("focusIntervention")
        else:
            patch["focusIntervention"] = _clean_focus(focus, filed_under)
            if new_project is None and patch["focusIntervention"] == (
                activity.focus_intervention or None
            ):
                patch.pop("focusIntervention")

    with transaction.atomic():
        if new_school is not None or new_project is not None:
            return _schedule_again(
                activity,
                new_school or activity.school,
                project=new_project,
                day=new_day,
                reason=reason,
                data={**data, **patch},
                principal=principal,
            )

        if patch:
            services.patch_activity(activity.id, patch, principal)
        if "facilitatingPartnerId" in data:
            from apps.activities.facilitation import takes_facilitator

            wanted_partner = str(data.get("facilitatingPartnerId") or "").strip()
            if takes_facilitator(activity.activity_type) and wanted_partner != (
                activity.facilitating_partner_id or ""
            ):
                services.set_facilitator(activity.id, wanted_partner, principal)
        if "invitedSchoolIds" in data and is_cluster_session(activity):
            _set_invited(activity, data.get("invitedSchoolIds"), principal)
        if date_moves or end_moves:
            payload = {
                "scheduledDate": new_day.isoformat(),
                "reason": reason,
                "plannedMonth": new_day.month,
                "plannedWeek": min(5, (new_day.day - 1) // 7 + 1),
            }
            if end_raw:
                payload["endDate"] = end_raw
            for member in _moves_together(activity, principal):
                services.reschedule(member.id, payload, principal)
    return services.get_activity(activity.id, principal)


def _moves_together(activity, principal) -> list:
    """The activity, and the other half of an in-school Training pair: one
    mission on one day (owner, 2026-09-28), so its two records move as one."""
    from apps.activities import services

    pair = services.in_school_training_pair(activity.id, principal, for_execution=True)
    if pair is None:
        return [activity]
    training, visit = pair
    return [member for member in (training, visit) if is_editable(member)]


def _set_invited(activity, raw_ids, principal) -> None:
    """Re-tick the member schools a cluster session invites."""
    from apps.activities.cluster_attendance import set_invited_schools

    ids = [str(i).strip() for i in (raw_ids or []) if str(i).strip()]
    if not ids:
        raise BadRequest(
            "Invite at least one school, or cancel this session if it is no "
            "longer happening."
        )
    typed_total = activity.expected_participants
    count = set_invited_schools(
        activity, ids, actor_id=str(getattr(principal, "id", "") or "")
    )
    fields = []
    if activity.schools_invited != count:
        activity.schools_invited = count
        fields.append("schools_invited")
    # `set_invited_schools` derives the head count from the composition per
    # school. A session planned with a number per school, or with a total
    # and no composition, has none to multiply: its count would be written
    # as zero. Such a session keeps its number per school across the new
    # list, or the total it was planned with.
    composition = sum(
        value or 0
        for value in (
            activity.teachers_per_school,
            activity.leaders_per_school,
            activity.other_per_school,
        )
    )
    if not composition:
        total = (activity.participants_per_school or 0) * count or typed_total
        if activity.expected_participants != total:
            activity.expected_participants = total
            fields.append("expected_participants")
    if fields:
        activity.save(update_fields=[*fields, "updated_at"])
        if "expected_participants" in fields:
            from django.db import transaction

            transaction.on_commit(lambda: _reprice_quietly(activity))


def _reprice_quietly(activity) -> None:
    """Re-price after a head count moved; a finance-locked session keeps the
    cost it has, as it does when its invitations change at scheduling."""
    try:
        from apps.activities.services import reprice_activity

        reprice_activity(activity)
    except Exception:  # noqa: BLE001 — the invitation list is the edit
        return


def _project_activity(lead, item_id, old_project, new_project):
    """The catalogue item the work carries under its new project.

    General support (a follow-up, an SSA visit) belongs to no project and
    keeps its item. An activity that is the old project's own — the CC-SEL
    training — is replaced by the new project's activity of the same kind;
    when the new project has none there is nothing to schedule it as.
    """
    from apps.activity_catalogue.models import (
        ActivityCatalogueItem,
        ActivityProjectMapping,
    )

    if not item_id:
        return item_id
    owners = set(
        ActivityProjectMapping.objects.filter(
            catalogue_item_id=item_id, active=True
        ).values_list("project_id", flat=True)
    )
    if not owners or new_project.id in owners:
        return item_id
    item = ActivityCatalogueItem.objects.filter(id=item_id).first()
    own = (
        ActivityProjectMapping.objects.filter(
            project=new_project,
            active=True,
            catalogue_item__workflow_kind=getattr(item, "workflow_kind", None),
        )
        .order_by("catalogue_item__display_name")
        .values_list("catalogue_item_id", flat=True)
        .first()
    )
    if own:
        return own
    raise BadRequest(
        f"'{getattr(item, 'display_name', 'This activity')}' is "
        f"{old_project.name if old_project else 'another project'}'s own "
        f"activity, and '{new_project.name}' has none of the same kind. Cancel "
        f"it and plan {new_project.name}'s activity from its school list."
    )


def _schedule_again(activity, school, *, project, day, reason, data, principal) -> dict:
    """Cancel the plan and make it again at ``school``, under ``project``
    when one is named.

    Scheduled through the same service a drawer uses, so the school's and the
    project's own rules decide whether the work can be taken; a refusal there
    rolls the cancellation back with it.
    """
    from apps.activities import services
    from apps.planning.services import (
        schedule_in_school_training_pair,
        schedule_school_visit,
    )

    pair = services.in_school_training_pair(activity.id, principal, for_execution=True)
    members = list(pair) if pair else [activity]
    for member in members:
        assert_editable(member)
    lead = pair[0] if pair else activity
    moved_school = school.id != lead.school_id

    def chosen(key, saved):
        return data[key] if key in data else saved

    payload = {
        "schoolId": school.school_id,
        "scheduledDate": day.isoformat(),
        "plannedMonth": day.month,
        "plannedWeek": min(5, (day.day - 1) // 7 + 1),
        "deliveryType": "staff",
        "responsibleStaffId": lead.responsible_staff_id,
        "activityPurposeText": chosen(
            "activityPurposeText", lead.activity_purpose_text
        ),
        "expectedOutcome": chosen("expectedOutcome", lead.expected_outcome),
        "purposeType": lead.purpose_type,
        "ssaCollectionExpected": lead.ssa_collection_expected,
        "requireCatalogue": True,
    }
    item_id = lead.training_course_id if pair else lead.catalogue_item_id
    if project is not None:
        from apps.projects.models import Project, ProjectSchoolAssignment
        from apps.projects.services import assign_school

        old_project = Project.objects.filter(id=lead.project_id).first()
        item_id = _project_activity(lead, item_id, old_project, project)
        if not ProjectSchoolAssignment.objects.filter(
            project=project, school=school
        ).exists():
            # The school joins the project it now has work under, by the
            # rules of "Add to Project": the adder's allocation, the
            # project's focus and its country.
            assign_school(
                project.id,
                {"schoolId": school.school_id, "reason": reason},
                principal,
            )
        payload["projectId"] = project.id
        # The purpose a project activity is given when the planner types
        # none is its project's name: it follows the project.
        if (
            old_project
            and (payload["activityPurposeText"] or "").strip()
            == (old_project.name or "").strip()
        ):
            payload["activityPurposeText"] = ""
        # The focus the planner chose for the new project, or the one the
        # project names; never the old project's, left on the activity.
        focus = data.get("focusIntervention")
    else:
        if lead.project_id:
            payload["projectId"] = lead.project_id
        focus = chosen("focusIntervention", lead.focus_intervention)
    if focus:
        payload["focusIntervention"] = focus
        payload["purposeIntervention"] = focus
    if lead.expected_participants:
        payload["expectedParticipants"] = lead.expected_participants
    facilitator = chosen("facilitatingPartnerId", lead.facilitating_partner_id)
    if facilitator:
        payload["facilitatingPartnerId"] = facilitator

    moved = []
    if moved_school:
        moved.append(f"Moved to {school.name}")
    if project is not None:
        moved.append(f"Changed to {project.name}")
    moved_reason = f"{', '.join(moved)}: {reason}"
    for member in members:
        services.cancel(member.id, {"reason": moved_reason}, principal)
    if pair:
        return schedule_in_school_training_pair(
            {**payload, "catalogueItemId": item_id}, principal
        )
    return schedule_school_visit(
        {
            **payload,
            "activityType": lead.activity_type,
            "catalogueItemId": item_id,
        },
        principal,
    )


LOCKED_REASON = "Already carried out, so it can no longer be edited."


def edit_state(activity, principal) -> str:
    """What the Edit button is for this reader: "open", "locked" or "".

    "open" — staff work still scheduled that the reader may run. "locked" —
    work the reader could have edited, now started or delivered: the button
    stays, greyed (owner, 2026-10-02). "" — not theirs to edit, or not a
    plan that is edited here (a partner's delivery, a cancelled or returned
    activity, a request awaiting its owner): no button, as for every action
    a role does not hold.
    """
    if getattr(activity, "delivery_type", "") == "partner":
        return ""
    editable = is_editable(activity)
    if not editable and not is_executed(activity):
        return ""
    from apps.activities.profile_activities import _may_run
    from apps.core.permissions import RolePermissionService

    if not RolePermissionService.can_view_page(principal, "my_plan"):
        return ""
    if not _may_run(activity, principal):
        return ""
    return "open" if editable else "locked"


__all__ = [
    "EDITABLE_STATUSES",
    "EXECUTED_STATUSES",
    "assert_editable",
    "assert_not_executed",
    "edit",
    "edit_state",
    "is_cluster_session",
    "is_editable",
    "is_executed",
    "may_move_school",
    "movable_schools",
]
