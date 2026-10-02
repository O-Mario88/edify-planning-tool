"""Put Core package work in the package of the year it is planned for, and
take out of the packages what is no part of one.

Owner, 2026-10-02: "Core School page are not fetching the number of visits.
People have planned first visit and second visits but they are not showing in
V1, V2, V3, V4 but the trainings are showing but also inflated numbers. The
staff are only supposed to plan for two visits and two trainings but it is
showing all the 4. The other two visits and trainings are supposed to be
assigned." And, asked what counts: "the only visits that count are in-school
visits and Training Follow Up visits", and the trainings "should include both
in-school training and group trainings planned through clusters".

Through September staff planned October's visits. Every door booked them into
the package of the day the planner was sitting in — FY2026, the only package
there was — so from 1 October the FY2027 page showed V1..V4 empty. A cluster
training or meeting took a training slot at every Core school it invited,
whatever the 2 + 2 split, so two trainings and two meetings read "4/4
trainings" with the Partner's half never assigned; and a data collection (SSA
Support) visit took one of the four visits.

New work is filed by its own year as it is saved; a group training takes a
slot on the half of whoever delivers it while that half has room; and neither
a cluster meeting nor a data collection visit takes a slot any more
(apps.core_schools.package_year, package_credit, cluster_credit). This
corrects what is already written:

1. for the running year's packages onward, a slot held by a cluster meeting
   or a data collection visit is given back;
2. a slot a group training holds in another year's package, or on a half that
   already has its two trainings, is given back;
3. a visit or training linked to another year's package moves to the package
   of the year it is dated in — made from the school's newest package if the
   year has none — oldest first, so the earliest is V1;
4. the group trainings that count and hold no slot take one;
5. the packages touched lose their gaps.

No activity is changed or removed: only which package slot points at it.
Historical models only, through ``package_year.refile``, which reads no live
service code (see activities 0057/0058). Every change is printed to the
deploy log. The reverse is a no-op. ``manage.py refile_core_package_work``
runs the same repair, dry run first.
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
        tag="0008_refile_package_work_by_year",
        outside_projects=_outside_ssa(apps.get_model("projects", "Project")),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0007_correct_slot_days"),
        ("activities", "0064_partner_date_set_by"),
        ("projects", "0014_project_staff_capacity"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
