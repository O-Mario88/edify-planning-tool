"""What a planned training is called, and how it is delivered.

Owner, 2026-10-06, on My Plan: "the training Name should be the actual
training name fetched from the training catalogue like literacy, TAM ... and
Mode of delivery should be (Cluster Group training or In-School training)".
The cards used to print the workflow — "In-school Training", "Cluster
Training" — in the Training Name column, which says how the day is run and
not what is taught.

The name comes from the Training Catalogue in the two places a plan records
its course: ``training_course``, the course named beside an in-school
delivery, else ``catalogue_item`` when that item is itself a course (a group
training). Both are foreign keys the My Plan query already joins, so a page
with the rows in memory pays no query here.

Mode of delivery is decided by what the plan is attached to: a school of its
own is an in-school delivery, a cluster with no school is a group delivery.
There is no third.
"""

from __future__ import annotations

from apps.core.activity_types import TRAINING_TYPES

GROUP = "group"
IN_SCHOOL = "in_school"
#: The two modes, as My Plan's Mode of Delivery column says them.
MODE_OF_DELIVERY = {GROUP: "Cluster Group Training", IN_SCHOOL: "In-School Training"}

_TRAINING_TYPES = frozenset(getattr(t, "value", t) for t in TRAINING_TYPES)


def is_training(activity) -> bool:
    return activity.activity_type in _TRAINING_TYPES


def course_name_of(activity) -> str:
    """The training's name as the Training Catalogue gives it — Literacy,
    TAM, Leadership; blank for a training nobody has named yet and for
    anything that is not a training."""
    if not is_training(activity):
        return ""
    if activity.training_course_id:
        return activity.training_course.display_name or ""
    item = activity.catalogue_item
    if item is not None and item.is_training_course:
        return item.display_name or ""
    return ""


def delivery_of(activity) -> str | None:
    """``GROUP`` or ``IN_SCHOOL``; None for anything that is not a training
    or is attached to neither a school nor a cluster."""
    if not is_training(activity):
        return None
    if activity.school_id:
        return IN_SCHOOL
    if activity.cluster_id:
        return GROUP
    return None


def mode_of_delivery(activity) -> str:
    """ "Cluster Group Training" or "In-School Training"; blank otherwise."""
    return MODE_OF_DELIVERY.get(delivery_of(activity), "")
