"""Put Core package work in the package of the year it is planned for, and
take out of the packages what is no part of one.

Owner, 2026-10-02: "Core School page are not fetching the number of visits.
People have planned first visit and second visits but they are not showing in
V1, V2, V3, V4 but the trainings are showing but also inflated numbers. The
staff are only supposed to plan for two visits and two trainings but it is
showing all the 4. The other two visits and trainings are supposed to be
assigned." And, asked what counts: cluster sessions are "outside the
package", and "the only visits that count are in-school visits and Training
Follow Up visits".

Through September staff planned October's visits. Every door booked them into
the package of the day the planner was sitting in — FY2026, the only package
there was — so from 1 October the FY2027 page showed V1..V4 empty. A cluster
training or meeting took a training slot at every Core school it invited, so
two trainings and two meetings read "4/4 trainings" with the Partner's half
never assigned; and a data collection (SSA Support) visit took one of the
four visits.

New work is filed by its own year as it is saved, and neither a cluster
session nor a data collection visit takes a slot any more
(apps.core_schools.package_year, package_credit, cluster_credit). This
corrects what is already written:

1. for the running year's packages onward, a slot held by a cluster session
   or a data collection visit is given back;
2. a visit or training linked to another year's package moves to the package
   of the year it is dated in — made from the school's newest package if the
   year has none — oldest first, so the earliest is V1;
3. the packages touched lose their gaps.

No activity is changed or removed: only which package slot points at it.
Historical models only, through ``package_year.refile``, which reads no live
service code (see activities 0057/0058). Every change is printed to the
deploy log. The reverse is a no-op. ``manage.py refile_core_package_work``
runs the same repair, dry run first.
"""

from __future__ import annotations

from django.db import migrations


def forwards(apps, schema_editor):
    from apps.core.fy import get_operational_fy
    from apps.core_schools import package_year

    package_year.refile(
        apps.get_model("core_schools", "CorePlan"),
        apps.get_model("core_schools", "CoreActivitySlot"),
        apps.get_model("activities", "Activity"),
        from_fy=str(get_operational_fy()),
        tag="0008_refile_package_work_by_year",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0007_correct_slot_days"),
        ("activities", "0064_partner_date_set_by"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
