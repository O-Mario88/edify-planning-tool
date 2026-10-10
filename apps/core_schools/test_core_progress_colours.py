"""Completed work is green, planned work is blue (owner, 2026-09-27).

"can we also mark planned activities with a different color and completed
plans with a different colors. All completed core visit and trainings have
green scheduled/planned is blue."
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core_schools.models import CoreActivitySlot
from apps.core_schools.test_core_visit_purposes import _CoreFixture
from apps.my_plan.services import plan_row_tone


def _row(status):
    return SimpleNamespace(status=status)


class MyPlanRowToneTest(SimpleTestCase):
    def test_a_core_visit_is_green_once_completed_and_blue_while_planned(self):
        for status in ("completed", "ia_verified", "accountant_confirmed", "closed"):
            self.assertEqual(plan_row_tone(_row(status), "", "", is_core=True), "green")
        for status in (
            "scheduled",
            "partner_scheduled",
            "in_progress",
            "completion_started",
            "awaiting_ia_verification",
        ):
            self.assertEqual(
                plan_row_tone(_row(status), "Due Today", "bg-amber-50", is_core=True),
                "blue",
                status,
            )

    def test_a_core_return_or_request_keeps_its_own_colour(self):
        self.assertEqual(
            plan_row_tone(_row("returned_by_ia"), "", "", is_core=True), "red"
        )
        self.assertEqual(
            plan_row_tone(_row("awaiting_owner_approval"), "", "", is_core=True),
            "amber",
        )

    def test_every_table_reads_scheduled_work_blue(self):
        for label in ("Scheduled", "This Week"):
            self.assertEqual(
                plan_row_tone(
                    _row("scheduled"),
                    label,
                    "bg-emerald-50 text-emerald-700",
                    is_core=False,
                ),
                "blue",
            )
        # Urgency keeps its colour outside the core tables.
        self.assertEqual(
            plan_row_tone(
                _row("scheduled"),
                "Due Today",
                "bg-amber-50 text-amber-700",
                is_core=False,
            ),
            "amber",
        )


class CoreRowMarksTest(_CoreFixture):
    def test_each_package_slot_reads_done_planned_or_open(self):
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="completed"
        )
        CoreActivitySlot.objects.filter(id=self._slot("v", 2).id).update(
            status="Scheduled", scheduled_for=date(2026, 10, 6)
        )
        CoreActivitySlot.objects.filter(id=self._slot("t", 1).id).update(
            status="Assigned", assigned_partner_id=self.partner.id
        )

        html = (
            self._client(self.cceo)
            .get(f"/core-schools?q={self.school.school_id}&fy={self.plan.fy}")
            .content.decode()
        )

        self.assertIn('data-state="done" title="V1 completed">V1<', html)
        self.assertIn('data-state="planned" title="V2 planned">V2<', html)
        self.assertIn('data-state="open" title="V3 not planned">V3<', html)
        self.assertIn('data-state="planned" title="T1 planned">T1<', html)
        # One of two planned visits is still to be delivered: the count is blue.
        self.assertIn('class="is-planned"', html)
        self.assertIn("core-progress.css", html)

    def test_the_school_profile_shows_the_package_in_the_same_colours(self):
        """Owner, 2026-09-27: "show colors on the core metadata page as well"."""
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="completed"
        )
        CoreActivitySlot.objects.filter(id=self._slot("t", 1).id).update(
            status="Scheduled"
        )

        html = (
            self._client(self.cceo)
            .get(f"/schools/{self.school.school_id}?tab=details")
            .content.decode()
        )

        self.assertIn('data-core-package="visits"', html)
        self.assertIn('data-state="done" title="V1 completed">V1<', html)
        self.assertIn('data-state="planned" title="T1 planned">T1<', html)
        self.assertIn("core-progress.css", html)

    def test_a_client_school_profile_has_no_package(self):
        self.school.school_type = "client"
        self.school.save(update_fields=["school_type"])
        html = (
            self._client(self.cceo)
            .get(f"/schools/{self.school.school_id}?tab=details")
            .content.decode()
        )
        self.assertNotIn("data-core-package", html)

    def test_the_plan_page_names_and_colours_each_slot(self):
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="completed"
        )
        html = (
            self._client(self.cceo)
            .get(f"/core-schools/{self.plan.id}")
            .content.decode()
        )
        self.assertIn('data-core-slot="V1"', html)
        self.assertIn('data-state="done">V1<', html)
        self.assertIn('data-state="open">V2<', html)
        self.assertIn(">Not planned<", html)

    def test_the_planning_queue_recommends_the_next_unplanned_slot(self):
        """V1 booked from any page is planned: the queue asks for V2, not a
        second V1, and colours each slot the same way."""
        from apps.core_schools.core_planning_services import CorePlanningService
        from apps.schools.models import School

        CoreActivitySlot.objects.filter(id=self._slot("a", 1).id).update(
            status="completed"
        )
        CoreActivitySlot.objects.filter(id=self._slot("v", 1).id).update(
            status="Scheduled"
        )

        [row] = CorePlanningService.get_planning_queue(
            School.objects.filter(id=self.school.id), self.plan.fy
        )

        self.assertEqual(row["next_recommended"], "V2 Visit")
        self.assertEqual(
            [(m["label"], m["state"]) for m in row["visit_marks"]][:2],
            [("V1", "planned"), ("V2", "open")],
        )


class MyPlanPackageNumberIsAFilledMarkTest(SimpleTestCase):
    """Owner, 2026-10-03: the V and T numbers on My Plan are filled marks,
    blue while planned and green once completed, like the Core Schools list,
    so staff can tell at a glance what is planned and what is done."""

    def _source(self, path):
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")

    def test_both_core_tables_draw_the_number_as_the_package_mark(self):
        for name in ("core_school_visits", "core_school_trainings"):
            html = self._source(f"templates/partials/my_plan/{name}.html")
            self.assertIn('class="core-seq__mark" data-state="', html, name)
            self.assertNotIn("mp-badge--{{ row.status_tone|default:'blue' }}", html)
        self.assertIn(
            "core-progress.css", self._source("templates/pages/my_plan/index.html")
        )

    def test_a_table_does_not_flatten_the_mark(self):
        script = self._source("static/js/micro-ux.js")
        self.assertIn(".sal-dot, .core-seq__mark')", script)
