"""A visit at a Core School is core package work, wherever it was scheduled.

The Planning page's Core tab and the Cluster schools table open the same
drawer as each other (`/planning/schedule-modal`), and it went through
`schedule_school_visit` -> a plain `school_visit` with no package slot. So a
visit planned from either surface was real and funded but invisible on the
Core School Visit page, counted toward no package, and priced as client work
— while the identical visit made from the Core Schools page was a `core_visit`
holding a slot. Three surfaces, two answers.

These pin the one answer, and the backfill that carries the rows already
planned the old way across to it.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command

from apps.activities.models import Activity
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.core_schools.test_core_visit_purposes import _CoreFixture
from apps.planning.services import schedule_school_visit

TODAY = date.today()


def _weekday(day: date) -> date:
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day


class CoreVisitRoutingTest(_CoreFixture):
    def _payload(self, school, **extra):
        """What the shared scheduling drawer posts for a school visit.

        ``catalogueItemId`` is what the view derives from the purpose before
        POSTing. The core path replaces it with the Core Visit costing; the
        ordinary path keeps it, and refuses without one.
        """
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        return {
            "schoolId": school.school_id,
            "activityType": "school_visit",
            "catalogueItemId": resolve_item_for_workflow_kind("school_visit").id,
            "scheduledDate": _weekday(TODAY + timedelta(days=3)).isoformat(),
            "purposeType": "ssa_support",
            "responsibleStaffId": self.cceo_sp.id,
            "deliveryType": "staff",
            "requireCatalogue": True,
            **extra,
        }

    def test_a_visit_planned_from_planning_or_cluster_is_core_package_work(self):
        result = schedule_school_visit(self._payload(self.school), self.cceo)

        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(
            activity.activity_type,
            "core_visit",
            "a visit at a core school is a core visit wherever it was planned",
        )
        self.assertEqual(activity.catalogue_item_id, self.core_visit_item.id)

        slot = CoreActivitySlot.objects.get(activity_id=activity.id)
        self.assertEqual(slot.activity_type, "visit")
        self.assertEqual(slot.core_plan.school_id, self.school.school_id)
        self.assertEqual(slot.status, "Scheduled")
        self.assertEqual(slot.owner, "staff")

    def test_the_visit_reaches_the_core_page_and_the_package_count(self):
        """The two things the planner was actually missing."""
        from apps.core_schools.core_planning_services import (
            CorePackageSchedulingService,
        )

        before = CorePackageSchedulingService.summary(self.plan)["visits"]
        schedule_school_visit(self._payload(self.school), self.cceo)
        after = CorePackageSchedulingService.summary(self.plan)["visits"]

        self.assertEqual(after, before + 1, "it contributes to the core package")
        # The Core School Visit page reads slots, and the slot now names the
        # activity — so the visit is reachable from that page.
        self.assertTrue(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, activity_type="visit", activity_id__isnull=False
            ).exists()
        )

    def test_a_client_school_visit_is_untouched(self):
        client_school = self._school("CLIENT-9", "Ordinary Client", self.cceo_sp)
        client_school.school_type = "client"
        client_school.save(update_fields=["school_type"])

        result = schedule_school_visit(self._payload(client_school), self.cceo)

        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.activity_type, "school_visit")
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=activity.id))

    def test_project_work_at_a_core_school_stays_project_work(self):
        """The project funds it, from its own approved activity list.

        The project scheduler shares this entry point, and it has already
        validated its Catalogue item as eligible for every school in the
        batch. Routing it would re-cost it against the Core Visit item and
        count the project's delivery as core package support.
        """
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="Literacy Project",
            category=ProjectCategory.INTERVENTION_SPECIFIC,
        )
        result = schedule_school_visit(
            self._payload(self.school, projectId=project.id), self.cceo
        )

        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.activity_type, "school_visit")
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=activity.id))

    def test_a_core_school_with_no_package_still_schedules(self):
        """Routing must never make a school unschedulable."""
        CorePlan.objects.filter(school_id=self.school.school_id).delete()

        result = schedule_school_visit(self._payload(self.school), self.cceo)

        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.activity_type, "school_visit")


class CoreVisitBackfillTest(_CoreFixture):
    """The rows users already planned the old way."""

    def _legacy_visit(self, **extra) -> Activity:
        """A visit as the Planning/Cluster drawer used to create it."""
        fields = {
            "activity_type": "school_visit",
            "school": self.school,
            "fy": self.plan.fy,
            "quarter": "Q1",
            "status": "scheduled",
            "planned_date": _weekday(TODAY + timedelta(days=4)),
            "planned_month": 1,
            "planned_week": 1,
            "purpose_type": "ssa_support",
            "responsible_staff_id": self.cceo_sp.id,
            "delivery_type": "staff",
        }
        fields.update(extra)
        return Activity.objects.create(**fields)

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("backfill_core_school_visits", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_it_is_a_dry_run_until_told_otherwise(self):
        activity = self._legacy_visit()

        output = self._run()

        self.assertIn("Dry run", output)
        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "school_visit")
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=activity.id))

    def test_it_converts_a_visit_planned_the_old_way(self):
        activity = self._legacy_visit()

        self._run("--apply")

        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "core_visit")
        self.assertEqual(activity.catalogue_item_id, self.core_visit_item.id)
        slot = CoreActivitySlot.objects.get(activity_id=activity.id)
        self.assertEqual(slot.activity_type, "visit")
        self.assertEqual(slot.status, "Scheduled")

    def test_it_leaves_a_visit_that_already_holds_a_slot_alone(self):
        """Idempotent: a second run must not consume a second slot."""
        self._legacy_visit()
        self._run("--apply")
        taken_after_first = CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type="visit", activity_id__isnull=False
        ).count()

        output = self._run("--apply")

        self.assertEqual(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, activity_type="visit", activity_id__isnull=False
            ).count(),
            taken_after_first,
        )
        self.assertIn("already linked", output)

    def test_it_does_not_touch_a_client_school(self):
        client_school = self._school("CLIENT-8", "Ordinary Client", self.cceo_sp)
        client_school.school_type = "client"
        client_school.save(update_fields=["school_type"])
        activity = self._legacy_visit()
        activity.school = client_school
        activity.save(update_fields=["school"])

        self._run("--apply")

        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "school_visit")

    def test_delivered_work_is_left_alone_unless_asked_for(self):
        """Re-pricing rebuilds budget lines, so completed work opts in."""
        activity = self._legacy_visit(status="ia_verified")

        self._run("--apply")
        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "school_visit")

        self._run("--apply", "--include-delivered")
        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "core_visit")

    def test_the_companion_visit_of_a_training_takes_no_visit_slot(self):
        """It is the training, recorded twice for Salesforce — not a visit."""
        activity = self._legacy_visit(
            purpose_type="in_school_training_delivery_visit",
        )

        self._run("--apply")

        activity.refresh_from_db()
        self.assertEqual(activity.activity_type, "school_visit")
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=activity.id))
