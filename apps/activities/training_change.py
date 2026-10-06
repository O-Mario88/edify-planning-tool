"""Naming, or renaming, the training a scheduled training delivers.

Owner, 2026-10-06: "Allow the users to update training names on the existing
training profiles. When I go to the training profile, I should be able to
click edit and then the training field is empty, then I click and get a
dropdown of all the trainings and select the right one for that training."

A training planned before every training named a Training Catalogue entry —
or planned as the wrong one — is put right from its own Edit drawer: the
planner chooses the training, and everything the catalogue attaches to that
choice follows it. Its SSA intervention becomes the one the training is
linked to, its schools are counted under that training (and must fit under
the officer's ceiling for it), and its name on every plan reads as the
training chosen.

Only a plan that is still scheduled is edited (apps.activities.editing), so a
training already carried out keeps the record it was completed with. Work
under a project keeps the training its project approved.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

__all__ = ["change_training", "may_change_training", "training_options"]


def may_change_training(activity) -> bool:
    """A training plan outside a project: a group training, an in-school
    training, or a cluster meeting classified Training."""
    from apps.planning import training_ceilings

    return training_ceilings.is_training(activity) and not activity.project_id


def _day(activity):
    from apps.core.clock import local_day

    return activity.planned_date or local_day(activity.scheduled_date)


def _is_universal(course_id) -> bool:
    from apps.planning.training_entitlement import is_universal

    return is_universal(course_id)


def _assert_school_takes_it(activity) -> None:
    """A training that stops being a universal one starts to count as the
    school's own: the client school's one support visit of the year, or one
    of a Core package's trainings on the half of whoever delivers it. Refuse
    the change where the school has no room for it, as the scheduling door
    would have (apps.activities.services)."""
    school = activity.school if activity.school_id else None
    if school is None:
        # A group session is never refused over one school.
        return
    from apps.planning.visit_gate import (
        assert_staff_may_schedule_visit,
        client_visit_pool,
        rule_for,
    )

    rule = rule_for(school.school_type)
    partner = activity.delivery_type == "partner"
    if rule == "core":
        from apps.core_schools.package_credit import package_kind_for
        from apps.core_schools.package_split import (
            PARTNER,
            STAFF,
            assert_side_open,
        )

        assert_side_open(
            school,
            package_kind_for(activity.activity_type, activity.purpose_type),
            PARTNER if partner else STAFF,
            fy=activity.fy,
            exclude_activity_id=activity.id,
        )
    elif rule == "client" and not partner:
        pool = client_visit_pool(
            activity.activity_type, activity.catalogue_item, activity.purpose_type
        )
        if pool is not None:
            assert_staff_may_schedule_visit(
                school, activity.fy, pool=pool, exclude_activity_id=activity.id
            )


def training_options(activity) -> list[dict]:
    """Every training this plan may be named as: the Training Catalogue for
    the way it is delivered, and the one it already names even if that one
    has since left the list."""
    from apps.activity_catalogue.availability import (
        CLUSTER,
        _serialize_training_courses,
        in_school_training_course_options,
        training_activity_options,
    )
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.planning import training_ceilings

    day = _day(activity)
    if training_ceilings.delivery_of(activity) == training_ceilings.IN_SCHOOL:
        options = in_school_training_course_options(on_date=day)
    else:
        options = training_activity_options(planning_context=CLUSTER, on_date=day)
    current = training_ceilings.course_id_of(activity)
    if current and all(option["id"] != current for option in options):
        from django.db.models import Prefetch

        from apps.hr.models import MilestoneActivityRule

        kept = ActivityCatalogueItem.objects.filter(id=current).prefetch_related(
            "intervention_mappings",
            Prefetch(
                "milestone_rules",
                queryset=MilestoneActivityRule.objects.filter(
                    active=True
                ).select_related("milestone__priority"),
                to_attr="active_priority_rules",
            ),
        )
        options = [*options, *_serialize_training_courses(kept)]
    return options


def change_training(
    activity, course_id, principal, *, schools_after: int | None = None
) -> bool:
    """Set the training this plan delivers. Returns whether it changed.

    Call inside the edit's transaction. ``schools_after`` is how many schools
    the plan will hold once the same save has finished, when that save also
    changes its invited schools; left out, the schools it holds now.
    """
    from apps.activity_catalogue.availability import (
        CLUSTER,
        validate_in_school_training_course_selection,
        validate_priority_training_selection,
    )
    from apps.activity_catalogue.services import get_selectable_item
    from apps.activity_catalogue.training_intervention import (
        catalogue_sets_intervention,
        intervention_for,
    )
    from apps.audit.services import log as audit_log
    from apps.core.activity_types import CLUSTER_MEETING_TYPES
    from apps.planning import training_ceilings

    course_id = str(course_id or "").strip()
    current = training_ceilings.course_id_of(activity)
    if course_id == (current or ""):
        return False
    if not may_change_training(activity):
        raise BadRequest(
            "The training is chosen on a training. Work under a project keeps "
            "the training its project approved."
        )
    if not course_id:
        raise BadRequest("Choose the training this delivers.")

    day = _day(activity)
    delivery = training_ceilings.delivery_of(activity)
    if delivery == training_ceilings.IN_SCHOOL:
        validate_in_school_training_course_selection(course_id, on_date=day)
    else:
        validate_priority_training_selection(
            course_id, planning_context=CLUSTER, on_date=day
        )
    course = get_selectable_item(course_id, on_date=day)

    # Its schools move under the new training, and must fit under the
    # officer's ceiling for it. None of them was counted there before.
    held = (
        schools_after
        if schools_after is not None
        else training_ceilings.schools_held(activity)
    )
    training_ceilings.reserve(
        staff_id=activity.responsible_staff_id,
        course_id=course.id,
        fy=activity.fy,
        requested=held,
        exclude_activity_id=activity.id,
    )

    was_universal = _is_universal(current)
    now_universal = bool(course.universal_training)
    if was_universal and not now_universal:
        _assert_school_takes_it(activity)

    previous = {
        "trainingId": current,
        "training": activity.activity_name_snapshot,
        "focus": activity.focus_intervention,
    }
    is_meeting = activity.activity_type in CLUSTER_MEETING_TYPES
    fields = ["recommendation_source", "updated_at"]
    item = activity.catalogue_item
    if (
        delivery == training_ceilings.GROUP
        and not is_meeting
        and course.workflow_kind == activity.activity_type
        and (item is None or item.is_training_course)
    ):
        # A group training names its training as its catalogue item.
        activity.catalogue_item = course
        activity.catalogue_version = (
            course.versions.order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        activity.training_course = None
        fields += ["catalogue_item", "catalogue_version", "training_course"]
    else:
        # An in-school training, and a training at a cluster meeting, keep
        # the workflow that prices them and name the training beside it.
        activity.training_course = course
        fields.append("training_course")
    if not is_meeting:
        activity.activity_name_snapshot = course.display_name
        fields.append("activity_name_snapshot")
    activity.recommendation_source = {
        **(activity.recommendation_source or {}),
        "trainingCourseId": course.id,
        "trainingCourseName": course.display_name,
        "trainingCourseCode": course.stable_code,
        "trainingCategory": course.training_category,
        "ssaIndicator": course.ssa_indicator_label,
    }
    if catalogue_sets_intervention(activity):
        linked = intervention_for(training_course_id=course.id) or None
        activity.focus_intervention = linked
        activity.purpose_intervention = linked
        fields += ["focus_intervention", "purpose_intervention"]
    activity.save(update_fields=fields)

    visit = activity.paired_school_visit
    if now_universal and not was_universal and activity.school_id:
        # A universal training is on top of a Core package's four (owner,
        # 2026-10-06): the slots this one and its visit held go back. A
        # group session's are settled as it is saved (cluster_credit).
        from apps.core_schools.package_credit import release_work

        release_work([activity.id, getattr(visit, "id", None)])
    if visit is not None:
        # The companion School Visit is the same mission: it carries the
        # training's intervention and says which training it accompanies.
        visit.focus_intervention = activity.focus_intervention
        visit.purpose_intervention = activity.focus_intervention
        visit_fields = ["focus_intervention", "purpose_intervention", "updated_at"]
        if (visit.activity_purpose_text or "").startswith("School visit accompanying "):
            visit.activity_purpose_text = (
                f"School visit accompanying {course.display_name}"
            )
            visit_fields.append("activity_purpose_text")
        visit.save(update_fields=visit_fields)

    if (activity.focus_intervention or None) != (previous["focus"] or None):
        # The SSA verdict described the old target (apps.ssa.plan_alignment).
        from apps.ssa.plan_alignment import rejudge

        rejudge(activity)
        if visit is not None:
            rejudge(visit)

    audit_log(
        action="activity.training_changed",
        subject_kind="Activity",
        subject_id=str(activity.id),
        actor_id=str(getattr(principal, "id", "") or ""),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "from": previous,
            "to": {
                "trainingId": course.id,
                "training": course.display_name,
                "focus": activity.focus_intervention,
            },
            "delivery": training_ceilings.DELIVERY_LABELS.get(delivery, ""),
        },
    )
    return True
