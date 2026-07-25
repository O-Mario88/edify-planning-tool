"""An overdue activity has three honest ways out, not one.

The row offered only "Reschedule", which quietly assumed the work had not
happened. It can equally have been done (Complete), or be worth talking about
(Discuss). All three are now on the row, and these tests hold each one wired to
the real workflow rather than to a plausible-looking URL.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.debriefs.field_debrief_service import DailyDebriefFlowService
from apps.geography.models import District, Region
from apps.schools.models import School

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates" / "pages" / "dashboards" / "cceo.html"


class OverdueRowMenuMarkupTest(TestCase):
    def setUp(self):
        self.src = TEMPLATE.read_text()

    def test_the_row_offers_a_menu_not_a_lone_reschedule_button(self):
        self.assertIn("row-menu__trigger", self.src)
        self.assertIn('aria-haspopup="true"', self.src)
        for label in ("Complete", "Reschedule", "Discuss this activity"):
            with self.subTest(label=label):
                self.assertIn(f">{label}<", self.src)

    def test_complete_and_reschedule_open_drawers_in_place(self):
        """Both are drawers; navigating away would lose the dashboard."""
        self.assertIn('hx-get="{{ r.complete_url }}"', self.src)
        self.assertIn('hx-get="{{ r.reschedule_url }}"', self.src)
        self.assertIn('hx-target="#drawer-container"', self.src)

    def test_discuss_is_a_link_carrying_the_activity(self):
        self.assertIn('href="{{ r.discuss_url }}"', self.src)


class DebriefFocusActivityTest(TestCase):
    """"Discuss this activity" has to arrive with its subject. An overdue
    activity is by definition not planned for today, so the daily form would
    not have listed it."""

    def setUp(self):
        region = Region.objects.create(name="Focus Region")
        district = District.objects.create(name="Focus District", region=region)
        self.user = User.objects.create_user(
            email="focus@debrief.test",
            password="password123",
            name="Focus CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        self.school = School.objects.create(
            school_id="FOCUS-1",
            name="Focus Primary",
            region=region,
            district=district,
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff, school_id=self.school.id
        )
        self.today = timezone.localdate()
        # Overdue: planned well before today.
        self.overdue = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.staff.id,
            fy="2026",
            quarter="Q4",
            planned_date=self.today - dt.timedelta(days=14),
        )

    def test_an_overdue_activity_is_carried_into_todays_form(self):
        without = DailyDebriefFlowService.get_state(self.user, self.today)
        self.assertNotIn(
            self.overdue.id, [r["activity"].id for r in without["rows"]]
        )

        with_focus = DailyDebriefFlowService.get_state(
            self.user, self.today, focus_activity_id=self.overdue.id
        )
        rows = {r["activity"].id: r for r in with_focus["rows"]}
        self.assertIn(self.overdue.id, rows)
        row = rows[self.overdue.id]
        self.assertTrue(row["is_focus"])
        # Ticked on arrival — the user came here to talk about this one.
        self.assertTrue(row["checked"])

    def test_it_is_not_duplicated_when_already_in_the_day(self):
        today_activity = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=self.staff.id,
            fy="2026",
            quarter="Q4",
            planned_date=self.today,
        )
        state = DailyDebriefFlowService.get_state(
            self.user, self.today, focus_activity_id=today_activity.id
        )
        ids = [r["activity"].id for r in state["rows"]]
        self.assertEqual(ids.count(today_activity.id), 1)

    def test_someone_elses_activity_cannot_be_pulled_in(self):
        """The id comes from a query string; ownership is re-checked."""
        other = User.objects.create_user(
            email="other@debrief.test",
            password="password123",
            name="Other CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        other_staff = StaffProfile.objects.create(user=other, title="CCEO")
        foreign = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=other_staff.id,
            fy="2026",
            quarter="Q4",
            planned_date=self.today - dt.timedelta(days=3),
        )
        state = DailyDebriefFlowService.get_state(
            self.user, self.today, focus_activity_id=foreign.id
        )
        self.assertNotIn(foreign.id, [r["activity"].id for r in state["rows"]])

    def test_the_page_marks_what_is_being_discussed(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/debriefs/submit?activity={self.overdue.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Discussing")
        # And says where it came from, since it is not today's work.
        self.assertContains(response, "carried in from")
