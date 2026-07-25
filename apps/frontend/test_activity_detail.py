"""The activity detail page, and the timeline it now carries.

The timeline is the part worth pinning: three steps that must read the record
rather than decorate the page. A step that always says "Completed" is worse
than no timeline, because it looks like evidence.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan.services import get_activity_status_label_and_class
from apps.schools.models import School

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "pages" / "my_plan" / "detail.html"


class ActivityDetailLayoutTest(TestCase):
    def setUp(self):
        self.src = TEMPLATE.read_text()

    def test_the_page_is_four_named_panels(self):
        for title in (
            "Activity Overview",
            "Execution Actions",
            "Verification Evidence",
            "Activity Timeline",
        ):
            with self.subTest(panel=title):
                self.assertIn(title, self.src)

    def test_each_action_says_what_it_does(self):
        for label in ("Complete Activity", "Reschedule Activity", "Discuss This Activity"):
            self.assertIn(label, self.src)
        self.assertIn("Mark activity as completed", self.src)

    def test_evidence_upload_reuses_the_completion_drawer(self):
        """One upload path, not a second one bolted onto this page."""
        self.assertIn("complete-drawer", self.src)
        self.assertNotIn("enctype=", self.src)


class ActivityTimelineTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Detail Region")
        district = District.objects.create(name="Detail District", region=region)
        self.user = User.objects.create_user(
            email="detail@activity.test",
            password="password123",
            name="Dana Detail",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        self.school = School.objects.create(
            school_id="DET-1", name="Detail Primary", region=region, district=district
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff, school_id=self.school.id
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _activity(self, status="scheduled"):
        return Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status=status,
            responsible_staff_id=self.staff.id,
            fy="2026",
            quarter="Q4",
            planned_date=dt.date(2026, 7, 15),
            # closed_activity_must_have_sf_id: closing without one is not a
            # state the database allows, so the fixture cannot fake it.
            salesforce_activity_id="SF-DET-1" if status == "closed" else None,
        )

    def _timeline(self, activity):
        response = self.client.get(f"/my-plan/{activity.id}")
        self.assertEqual(response.status_code, 200)
        return {s["label"]: s for s in response.context["timeline"]}

    def test_a_scheduled_activity_has_only_its_first_step_done(self):
        steps = self._timeline(self._activity())
        self.assertTrue(steps["Activity scheduled"]["done"])
        self.assertFalse(steps["Evidence upload"]["done"])
        self.assertFalse(steps["Activity completion"]["done"])

    def test_completion_is_read_from_the_record(self):
        steps = self._timeline(self._activity(status="closed"))
        self.assertTrue(steps["Activity completion"]["done"])

    def test_evidence_is_pending_until_a_file_exists(self):
        """The step counts real evidence rows, not the activity's own status."""
        steps = self._timeline(self._activity(status="closed"))
        self.assertFalse(steps["Evidence upload"]["done"])
        self.assertEqual(steps["Evidence upload"]["detail"], "Pending")


class ClosedActivityLabelTest(TestCase):
    """A closed activity was falling through every branch of the status helper
    to the default "Scheduled" — so a finished activity was labelled upcoming
    in every My Plan table and on its own detail page, directly beside a
    timeline that called it complete."""

    def setUp(self):
        region = Region.objects.create(name="Closed Region")
        district = District.objects.create(name="Closed District", region=region)
        self.school = School.objects.create(
            school_id="CLS-1", name="Closed Primary", region=region, district=district
        )

    def _activity(self, status):
        return Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status=status,
            fy="2026",
            quarter="Q4",
            planned_date=dt.date(2026, 7, 15),
            salesforce_activity_id=(
                "SF-CLS-1" if status in ("closed", "completed") else None
            ),
        )

    def test_a_closed_activity_reads_as_complete(self):
        label, css = get_activity_status_label_and_class(
            self._activity("closed"), dt.date(2026, 7, 25)
        )
        self.assertEqual(label, "Activity complete")
        self.assertIn("emerald", css)

    def test_a_completed_activity_still_reads_as_complete(self):
        label, _ = get_activity_status_label_and_class(
            self._activity("completed"), dt.date(2026, 7, 25)
        )
        self.assertEqual(label, "Activity complete")

    def test_a_scheduled_activity_is_untouched(self):
        label, _ = get_activity_status_label_and_class(
            self._activity("scheduled"), dt.date(2026, 1, 1)
        )
        self.assertNotEqual(label, "Activity complete")
