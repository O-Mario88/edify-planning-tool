"""Give staff's SSA Support visits at Core schools their package slot.

Owner, 2026-10-03: "SSA should be part of the core package v1-v4", and
"Staff scheduled SSA Support for both core and clients schools counts towards
the core visit package ... if it is assigned to the partner it does not
count."

On 2026-10-02 data collection was taken out of the package for everybody and
migration 0008 gave back every slot such a visit held. From this release an
SSA Support visit staff schedule is a package visit again, on the staff half,
and takes its slot as it is saved (apps.core_schools.package_credit). This
brings what is already written into line, for the running year's packages
onward:

* every staff SSA Support visit at a Core school that holds no slot takes the
  next open visit slot of the package of the year it is dated in, oldest
  first, so the earliest is V1 (a slot past the fourth is made when the four
  are taken: work that is planned is counted, never dropped);
* a slot a Partner's data collection visit still holds is given back;
* the packages touched lose their gaps.

No activity is changed or removed: only which package slot points at it.
Historical models only, through ``package_year.refile``, which reads no live
service code and has already run on this database as 0008. Every change is
printed to the deploy log. The reverse is a no-op.
``manage.py refile_core_package_work`` runs the same repair, dry run first.
"""

from __future__ import annotations

from django.db import migrations


def _outside_ssa(Project) -> set:
    """Projects no SSA intervention measures (Alumni), whose work is no part
    of a package: ``Project.measured_by_ssa`` over the historical model, which
    carries no properties. A project's targets are SSA interventions or
    General, so the unmeasured ones are those that name General and nothing
    else; one that names no target at all is measured like any other."""
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
        tag="0009_staff_ssa_support_in_the_package",
        outside_projects=_outside_ssa(apps.get_model("projects", "Project")),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0008_refile_package_work_by_year"),
        ("activities", "0064_partner_date_set_by"),
        ("projects", "0014_project_staff_capacity"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
