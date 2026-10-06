"""Give back the Core package slots SSA Training holds.

Owner, 2026-10-06: "School Improvement Planning training is universal every
schools can attend. for the rest of the trainings, Core gets 4 training and
clients get 1 training ontop of School improvement training", and, the same
day, "School improvement Planning is actually SSA training".

So SSA Training is on top of a Core package's four trainings. From this
release it takes no slot as it is saved and is on neither half of the 2 + 2
split (apps.planning.training_entitlement). Until now it was a training like
any other: a session already on the calendar holds one of the package's
training slots, and the School Visit an in-school delivery wrote beside
itself holds one of its visit slots. Left there, the Core Schools page would
go on reading "Trainings 2/4" for a school the split now counts at 1/4. This
brings what is already written into line, for the running year's packages
onward:

* a slot held by SSA Training — delivered at the school or as a group
  session — is given back, and so is the visit slot held by the visit written
  beside an in-school one;
* the packages touched lose their gaps.

No activity is changed or removed: only which package slot points at it. An
earlier year's package keeps what it recorded.

The training is found by its stable code, restated here: which trainings are
universal is a column the governed seed fills after every migrate
(activity_catalogue 0016), so it is still empty when this runs on a database
that has never had it. Historical models only, through
``package_year.refile``, which reads no live service code and has already run
on this database as 0008, 0009 and 0010. Every change is printed to the
deploy log. The reverse is a no-op. ``manage.py refile_core_package_work``
runs the same repair, dry run first.
"""

from __future__ import annotations

from django.db import migrations

#: ``activity_catalogue.seed_data.UNIVERSAL_TRAINING_CODES`` on 2026-10-06.
UNIVERSAL_TRAINING_CODES = ("SSA_TRAINING",)


def _outside_ssa(Project) -> set:
    """Projects no SSA intervention measures (Alumni), whose work is no part
    of a package: ``Project.measured_by_ssa`` over the historical model."""
    outside = set()
    for project in Project.objects.filter(deleted_at__isnull=True):
        targets = [str(t) for t in (project.target_interventions or []) if t]
        if project.intervention:
            targets.append(str(project.intervention))
        if targets and all(target == "general" for target in targets):
            outside.add(project.id)
    return outside


def forwards(apps, schema_editor):
    from apps.core.fy import get_operational_fy
    from apps.core_schools import package_year

    universal = set(
        apps.get_model("activity_catalogue", "ActivityCatalogueItem")
        .objects.filter(stable_code__in=UNIVERSAL_TRAINING_CODES)
        .values_list("id", flat=True)
    )
    if not universal:
        # A database with no catalogue yet (a new one, a test one) has no
        # SSA Training on any calendar either.
        return
    package_year.refile(
        apps.get_model("core_schools", "CorePlan"),
        apps.get_model("core_schools", "CoreActivitySlot"),
        apps.get_model("activities", "Activity"),
        apps.get_model("activities", "ClusterActivityAttendance"),
        apps.get_model("schools", "School"),
        from_fy=str(get_operational_fy()),
        tag="0011_universal_training_on_top_of_the_package",
        outside_projects=_outside_ssa(apps.get_model("projects", "Project")),
        universal_courses=universal,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0010_in_school_training_visit_in_the_package"),
        ("activities", "0065_activity_meeting_kind"),
        ("activity_catalogue", "0016_item_universal_training"),
        ("projects", "0014_project_staff_capacity"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
