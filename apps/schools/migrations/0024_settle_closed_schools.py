"""A school already closed leaves the sessions, projects and queues it was in.

Owner, 2026-10-07: "make sure that if a school is closed they go to the closed
school list and total number updated."

Closing a school cancelled its own activities and withdrew its partners, and
stopped there. Three things went on naming it: an invitation to a group
training or cluster meeting not yet held (so it stayed on the session, in the
officer's training count and in the session's price), a project enrolment (so
it stayed on the project's table and used one of the adder's places), and its
open data-quality issues. Closing a school now releases all three
(``apps.schools.lifecycle_service._leave_what_it_was_in``). This does the same
for the schools that closed before it did.

WHAT CHANGES, and only for schools whose status is closed:

* an invitation that was never attended, on a session not yet held and dated
  on or after the day the school closed, is removed, and that session is
  re-counted and re-priced as unticking the school in its drawer does;
* an enrolment in a project that has delivered no work at the school is
  withdrawn, with its history kept (``ProjectSchoolEnrollmentHistory``);
* open data-quality issues are marked resolved.

WHAT DOES NOT
No school record is written. Attendance that was recorded, sessions already
held, and an enrolment a project delivered work under are left as they are.

Historical models decide whether there is anything to do; live code does the
work, as a closure does it (the pattern of activities 0057 and 0058). On a
database with no closed school holding anything, which is every fresh one, no
live code runs. Every school is printed to the deploy log. The same report,
without the change, is ``python manage.py settle_closed_schools``.

Reverse is a no-op: what was released is not put back.
"""

from __future__ import annotations

from django.db import migrations


def settle_closed_schools(apps, schema_editor):
    from apps.schools import closed_school_settlement as settlement

    found = settlement.find(
        apps.get_model("schools", "School"),
        apps.get_model("activities", "ClusterActivityAttendance"),
        apps.get_model("projects", "ProjectSchoolAssignment"),
        apps.get_model("schools", "DataQualityIssue"),
    )
    if not found:
        print("\n  [schools.0024] no closed school holds anything.")
        return
    print(f"\n  [schools.0024] {len(found)} closed school(s) still hold something:")
    for row in found:
        print(f"  [schools.0024] {row.line()}")
        result = settlement.settle(row.school_pk)
        print(
            f"  [schools.0024]   left {result['invitations']} session(s) and "
            f"{result['projects']} project(s); {result['issues']} issue(s) closed."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0023_repair_school_holder_assignments"),
        # The live code reads these apps' models as they are today.
        ("activities", "0065_activity_meeting_kind"),
        ("projects", "0014_project_staff_capacity"),
        ("core_schools", "0012_index_slot_activity"),
        ("planning", "0016_training_country_ceiling"),
        ("partners", "0032_clear_handover_target_dates"),
        ("fund_requests", "0019_index_item_cost_line"),
        ("daily_visit_batches", "0003_reprice_planned_nights_away"),
        ("budget", "0024_management_accommodation_rate"),
        ("activity_catalogue", "0016_item_universal_training"),
        ("audit", "0008_domain_event_aggregate_id_width"),
        ("accounts", "0037_user_admin_is_never_cceo"),
        ("clusters", "0007_cluster_facilitating_partner"),
    ]

    operations = [
        migrations.RunPython(settle_closed_schools, migrations.RunPython.noop),
    ]
