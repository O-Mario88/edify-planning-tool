"""Correcting the purpose a planned school visit was scheduled with.

Owner, 2026-10-19: "The user had intended to schedule ssa support visit. he
should be able to edit the activity to what he intended." Officers planned
Training Follow Up visits where no training had yet been completed for the
visit to follow up. Completion names the training a follow-up answered
(``services._bind_followed_up_training``), so such a visit could never be
completed, and the only way out was to cancel it and plan it again.

The purpose is now changed on the visit itself, from its Edit drawer, and
the visit stays the one activity: its ID, its school, its day, its owner and
its notes are kept. What the purpose decides follows it:

* A client school's visit takes the workflow the purpose maps to
  (``apps.partners.purposes.PURPOSE_ACTIVITY_TYPES``) and that workflow's
  catalogue entry, so its Salesforce record type and its price are the ones a
  visit planned with that purpose has. The school's rules are asked again as
  scheduling asks them: the one support visit of the year, and a Champion
  school's donor and story visits only.
* A Core package visit keeps its slot: it moves between the package's two
  visit purposes, Training Follow Up and SSA Support, and keeps its workflow
  and its price. Leaving the package (a donor or story visit) is a different
  plan, made from Core Schools.
* SSA Support collects the year's SSA, so completion asks for the scores or
  why none were collected. A visit that stops being a Training Follow Up no
  longer names a training.

Only a plan that is still scheduled is changed (``apps.activities.editing``);
an In-school Training is planned as its own training-and-visit pair and is
not reached by changing a visit's purpose. Each change is written to the
audit trail with the purpose before and after.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

__all__ = ["change_purpose", "may_change_purpose", "moves_money", "purpose_options"]

#: The two purposes a Core package visit may hold: both are the package's
#: staff visit (apps.core_schools.package_credit.package_kind_for).
CORE_PACKAGE_VISIT_PURPOSES = ("training_follow_up", "ssa_support")

#: Planned as a training and its companion visit, never by changing a visit.
_PAIRED_PURPOSES = frozenset({"in_school_training"})


def _purpose_workflows() -> frozenset:
    """The workflows a client school's visit is planned under through its
    purpose (the retired In-school Coaching is no longer offered)."""
    from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES

    return frozenset(
        workflow
        for purpose, workflow in PURPOSE_ACTIVITY_TYPES.items()
        if purpose not in _PAIRED_PURPOSES and purpose != "in_school_coaching"
    )


def _is_core_slot(activity) -> bool:
    return (activity.activity_type or "") == "core_visit"


def may_change_purpose(activity) -> bool:
    """A staff visit at one school whose purpose decides what it is: a
    client school's purpose-planned visit, or a Core package visit."""
    if not activity.school_id or activity.cluster_id:
        return False
    if activity.delivery_type == "partner" or activity.paired_school_visit_id:
        return False
    if _is_core_slot(activity):
        return (activity.purpose_type or "") in ("", *CORE_PACKAGE_VISIT_PURPOSES)
    return (activity.activity_type or "") in _purpose_workflows()


def purpose_options(activity) -> list[tuple[str, str]]:
    """The purposes this visit may be changed to."""
    from apps.partners.purposes import STAFF_VISIT_PURPOSES

    if not may_change_purpose(activity):
        return []
    if _is_core_slot(activity):
        allowed = CORE_PACKAGE_VISIT_PURPOSES
    else:
        allowed = tuple(
            value
            for value, _label in STAFF_VISIT_PURPOSES
            if value not in _PAIRED_PURPOSES
        )
    labels = dict(STAFF_VISIT_PURPOSES)
    return [(value, labels[value]) for value in allowed]


def moves_money(activity) -> bool:
    """Whether a purpose change re-prices this visit: a client school's visit
    takes another workflow's catalogue entry; a Core slot keeps its price."""
    return not _is_core_slot(activity)


def _day(activity):
    from apps.core.clock import local_day

    return activity.planned_date or local_day(activity.scheduled_date)


def _renamed_text(text: str, old_label: str, new_label: str) -> str:
    """The purpose written when it was planned names the old purpose ("Training
    Follow Up for Kitgum Municipality Cluster cluster schools"): it is renamed
    with it. Anything the planner wrote in their own words is kept."""
    text = text or ""
    if old_label and text.startswith(old_label):
        return new_label + text[len(old_label) :]
    return text


def _assert_school_takes_it(activity, workflow: str, item, purpose: str) -> None:
    """The school's rules, asked as scheduling asks them, for a visit that
    moves into a count it was not in before."""
    from apps.planning.visit_gate import (
        assert_outreach_activity_allowed,
        assert_staff_may_schedule_visit,
        client_visit_pool,
        rule_for,
    )

    school = activity.school
    assert_outreach_activity_allowed(school, workflow)
    if rule_for(school.school_type) != "client":
        return
    before = client_visit_pool(
        activity.activity_type, activity.catalogue_item, activity.purpose_type
    )
    after = client_visit_pool(workflow, item, purpose)
    if after is not None and after != before:
        assert_staff_may_schedule_visit(
            school, activity.fy, pool=after, exclude_activity_id=activity.id
        )


def change_purpose(activity, purpose, principal, *, reason: str = "") -> bool:
    """Set the purpose this planned visit is for. Returns whether it changed.

    Call inside the edit's transaction, after ``editing.assert_editable``.
    Re-pricing a visit whose workflow moved is the caller's (``moves_money``).
    """
    from apps.audit.services import log as audit_log
    from apps.partners.purposes import (
        INTERVENTION_FREE_PURPOSES,
        purpose_activity_type,
        visit_purpose_label,
    )

    purpose = str(purpose or "").strip()
    current = activity.purpose_type or ""
    if purpose == current:
        return False
    if not may_change_purpose(activity):
        raise BadRequest(
            "The purpose is changed on a planned visit to one school. This "
            "activity is planned as something else; cancel it and plan the "
            "visit you need."
        )
    offered = dict(purpose_options(activity))
    if purpose not in offered:
        if purpose in _PAIRED_PURPOSES:
            raise BadRequest(
                "An In-school Training is planned with its training and its "
                "visit together. Cancel this visit and plan the In-school "
                "Training from the school."
            )
        if _is_core_slot(activity):
            raise BadRequest(
                "A Core package visit is a Training Follow Up or SSA Support. "
                "A donor, story or other visit is planned from Core Schools."
            )
        raise BadRequest("Choose one of the visit purposes offered.")

    old_label = visit_purpose_label(current, "")
    new_label = offered[purpose]
    previous = {
        "purposeType": current or None,
        "purpose": old_label or None,
        "activityType": activity.activity_type,
        "catalogueItemId": activity.catalogue_item_id,
        "ssaCollectionExpected": bool(activity.ssa_collection_expected),
        "followUpOfActivityId": activity.follow_up_of_activity_id,
        "activityPurposeText": activity.activity_purpose_text or "",
    }

    collects_ssa = purpose == "ssa_support"
    if _is_core_slot(activity):
        # The slot, its workflow and its price stay; only why it is made moves.
        activity.follow_up_of_activity = None
        fields = ["follow_up_of_activity"]
    else:
        from apps.activities.services import sf_kind
        from apps.activity_catalogue.services import (
            apply_catalogue_snapshot,
            resolve_item_for_workflow_kind,
        )

        workflow = purpose_activity_type(purpose)
        item = resolve_item_for_workflow_kind(workflow, on_date=_day(activity))
        if item is None:
            raise BadRequest(
                f"No single approved Catalogue Activity costs “{new_label}”. "
                "Ask the Country Director to define one costing for it."
            )
        _assert_school_takes_it(activity, workflow, item, purpose)
        activity.activity_type = workflow
        # The catalogue entry, its snapshots and its Salesforce record type;
        # the follow-up link is cleared (no source activity), the planner's
        # focus and recommendation are carried over.
        apply_catalogue_snapshot(
            activity,
            item=item,
            recommendation_reason=activity.recommendation_reason or "",
            requested_intervention=activity.focus_intervention,
            override_reason=activity.override_reason or "",
            recommendation_source=activity.recommendation_source or {},
            intervention_optional=collects_ssa or purpose in INTERVENTION_FREE_PURPOSES,
        )
        activity.salesforce_activity_type = sf_kind(workflow)
        fields = ["activity_type", "salesforce_activity_type"]

    activity.purpose_type = purpose
    activity.ssa_collection_expected = collects_ssa
    activity.activity_purpose_text = _renamed_text(
        activity.activity_purpose_text, old_label, new_label
    )
    activity.save(
        update_fields=[
            *fields,
            "purpose_type",
            "ssa_collection_expected",
            "activity_purpose_text",
            "updated_at",
        ]
    )

    audit_log(
        action="activity.purpose_changed",
        subject_kind="Activity",
        subject_id=str(activity.id),
        actor_id=str(getattr(principal, "id", "") or ""),
        actor_role=getattr(principal, "active_role", None),
        reason=reason or None,
        payload={
            "from": previous,
            "to": {
                "purposeType": purpose,
                "purpose": new_label,
                "activityType": activity.activity_type,
                "catalogueItemId": activity.catalogue_item_id,
                "ssaCollectionExpected": collects_ssa,
                "followUpOfActivityId": activity.follow_up_of_activity_id,
                "activityPurposeText": activity.activity_purpose_text or "",
            },
        },
    )
    return True
