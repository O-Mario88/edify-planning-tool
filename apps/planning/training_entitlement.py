"""Which trainings a school's training entitlement counts, and which it does not.

Owner, 2026-10-06:

  "School Improvement Planning training is universal every schools can
  attend. for the rest of the trainings, Core gets 4 training and clients get
  1 training ontop of School improvement training. therefore schools that are
  added to school improvement training can have one more training. Special
  project trainings like Technology, cc-sel.... are not restricted. any
  school can be assigned to those but it is controlled byt project
  coordinator"

And, later the same day: "I have realized that School improvement Planning
is actually SSA training. can you just link SSA training to Leadership ssa
intervention and then remove the school improvement planning that i proposed
earlier". So the universal training is the catalogue's own SSA Training.

Three kinds of training, then, and one answer for each wherever a school's
year is counted or a plan is refused:

* **A universal training** (the catalogue's ``universal_training`` courses:
  SSA Training). Every school that takes training may attend
  it, and it is *on top of* the school's entitlement. It is not the client
  school's one support visit of the year, it takes none of a Core package's
  four trainings and is on neither half of the 2 + 2 split, and no count
  refuses it. The School Visit an in-school delivery writes beside itself is
  the same mission and follows it: no visit slot, no half.
* **The rest of the catalogue's trainings.** The entitlement, unchanged: a
  Core school's package of four, two staff's and two a Partner's
  (``apps.core_schools.package_split``); a Client, Core Trained or Core
  Graduate school's one (``apps.planning.visit_gate``).
* **A training under a Special Project.** Never refused over the school's
  entitlement: which schools take it is the Project Coordinator's, through
  the project's own enrolment and capacity (``apps.projects``). It still
  counts where project work counted before (owner, 2026-09-30: project work
  "can contribute to the core school packages"); only the refusal is lifted.

A Champion school is planned for donor and story visits only (owner,
2026-09-25, kept on 2026-09-28). That rule is about the school, not about the
training, and stays ahead of everything here.

Read from the row's own columns, so a list can ask for a thousand rows in one
filter (``not_universal_q``), a door can ask before the row exists
(``never_refused``) and a saved row can be asked by itself
(``activity_is_universal``).
"""

from __future__ import annotations

from django.db.models import Q

#: The School Visit an in-school training writes beside itself
#: (``apps.planning.visit_gate.COMPANION_VISIT_PURPOSE``, restated so this
#: module imports nothing that imports it).
COMPANION_VISIT_PURPOSE = "in_school_training_delivery_visit"

#: The trainings delivered at one school (``cluster_attendance``).
SCHOOL_TRAINING_TYPES = frozenset(
    {"training", "in_school_training", "school_improvement_training", "core_training"}
)
#: The retired In-school Coaching Visit, "the same as In-school training".
IN_SCHOOL_TRAINING_SHAPES = SCHOOL_TRAINING_TYPES | {"in_school_coaching_visit"}


def universal_course_ids() -> frozenset[str]:
    """Ids of the catalogue trainings every school may attend on top of its
    entitlement. One or two rows, read once a request."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.core.request_cache import memoize

    def read() -> frozenset[str]:
        return frozenset(
            ActivityCatalogueItem.objects.filter(
                is_training_course=True, universal_training=True
            ).values_list("id", flat=True)
        )

    return memoize("training_entitlement.universal_courses", read)


def is_universal(course_or_id) -> bool:
    """Whether this training (a catalogue course, or its id) is universal.
    False for no training at all."""
    if not course_or_id:
        return False
    flag = getattr(course_or_id, "universal_training", None)
    if flag is not None:
        return bool(flag)
    return str(getattr(course_or_id, "id", course_or_id)) in universal_course_ids()


def is_training_shape(activity_type) -> bool:
    """A training delivered at one school, by its type alone."""
    return str(activity_type or "") in IN_SCHOOL_TRAINING_SHAPES


def never_refused(activity_type, *, course=None, project_id=None) -> bool:
    """Whether a school's entitlement never refuses work of this shape: a
    universal training, or a training under a Special Project. A visit is
    never one, whatever it belongs to."""
    if not is_training_shape(activity_type):
        return False
    return bool(project_id) or is_universal(course)


def names_universal_course(activity) -> bool:
    """Whether this saved row names a universal training as its own: an
    in-school delivery by its course, a group session by its catalogue item.
    Asked on every save of school work, so a row that names no training pays
    nothing and the rest read the short list once a request."""
    if not (
        activity.training_course_id
        or str(activity.activity_type or "") in SCHOOL_TRAINING_TYPES
        or activity.cluster_id
    ):
        return False
    ids = universal_course_ids()
    return bool(ids) and (
        activity.training_course_id in ids or activity.catalogue_item_id in ids
    )


def activity_is_universal(activity) -> bool:
    """Whether this saved row is a universal training, or the School Visit one
    wrote beside itself (found from the training that points at it)."""
    if names_universal_course(activity):
        return True
    if str(activity.purpose_type or "") != COMPANION_VISIT_PURPOSE:
        return False
    return (
        type(activity)
        .objects.filter(
            paired_school_visit_id=activity.id,
            training_course__universal_training=True,
        )
        .exists()
    )


def universal_q(prefix: str = "") -> Q:
    """Activities that are a universal training: an in-school delivery, a
    group session, or the School Visit written beside an in-school one. Read
    through the rows' own joins, so a list pays no query to ask."""
    p = prefix
    return (
        Q(**{f"{p}training_course__universal_training": True})
        | Q(**{f"{p}catalogue_item__universal_training": True})
        | Q(
            **{
                f"{p}paired_in_school_training__training_course__universal_training": True
            }
        )
    )


def not_universal_q(prefix: str = "") -> Q:
    """Rows a school's entitlement counts as far as this rule goes: everything
    but the universal trainings and the visits written beside them."""
    return ~universal_q(prefix)


__all__ = [
    "COMPANION_VISIT_PURPOSE",
    "activity_is_universal",
    "is_training_shape",
    "is_universal",
    "names_universal_course",
    "never_refused",
    "not_universal_q",
    "universal_course_ids",
    "universal_q",
]
