"""Give the visit of every in-school training at a Core school its package
slot.

Owner, 2026-10-03: an in-school training at a Core school "does not record
the visit package V1, V2, V3, V4" beside the training package T1..T4.

An in-school training is written as two records on one day: the Training and
the School Visit that carries the day's cost. The Training took the package's
next training slot; the visit took none, so the Core Schools list read one
training and no visit, and My Plan numbered the training row and not the
visit row. From this release the visit takes the package's next open visit
slot as it is saved (apps.core_schools.package_credit.slot_kind). This brings
what is already written into line, for the running year's packages onward:

* every such visit at a Core school that holds no slot takes the next open
  visit slot of the package of the year it is dated in, oldest first (a slot
  past the fourth is made when the four are taken: work that is planned is
  counted, never dropped);
* the packages touched lose their gaps.

No activity is changed or removed: only which package slot points at it.
Historical models only, through ``package_year.refile``, which reads no live
service code and has already run on this database as 0008 and 0009. Every
change is printed to the deploy log. The reverse is a no-op.
``manage.py refile_core_package_work`` runs the same repair, dry run first.
"""

from __future__ import annotations

from django.db import migrations


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

    package_year.refile(
        apps.get_model("core_schools", "CorePlan"),
        apps.get_model("core_schools", "CoreActivitySlot"),
        apps.get_model("activities", "Activity"),
        apps.get_model("activities", "ClusterActivityAttendance"),
        apps.get_model("schools", "School"),
        from_fy=str(get_operational_fy()),
        tag="0010_in_school_training_visit_in_the_package",
        outside_projects=_outside_ssa(apps.get_model("projects", "Project")),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0009_staff_ssa_support_in_the_package"),
        ("activities", "0064_partner_date_set_by"),
        ("projects", "0014_project_staff_capacity"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
