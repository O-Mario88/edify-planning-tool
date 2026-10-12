"""A drawer save stays on the page (owner, 2026-10-12: "Saving everything
takes too long").

Every save answered with a whole-page reload, and the live stream then read
the page a second time 400 ms later. A save now answers with a call to the
page's live regions (static/js/live-regions.js ``EdifyLive.saved``): read
once, swapped in place, the stream's echo skipped. Pinned here: the answer
itself, the clock the server stamps a live read with, and that the two pages
the field officer saves from carry a live region to read.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.core.htmx_saved import SAVED_SCRIPT, saved_in_place
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


class SavedInPlaceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            email="sip-cceo@t.test",
            name="Saver",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
            status="active",
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, title="Saver", country="Uganda"
        )
        region = Region.objects.create(name="SIP Region")
        district = District.objects.create(name="SIP District", region=region)
        cls.school = School.objects.create(
            school_id="SIP-1", name="Save Primary", region=region, district=district
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=cls.school.id)
        cls.activity = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            planned_date=date.today() + timedelta(days=3),
            responsible_staff_id=cls.staff.id,
            school=cls.school,
        )

    def test_the_answer_reads_the_regions_and_reloads_only_without_them(self):
        response = saved_in_place()
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        body = response.content.decode()
        self.assertEqual(body, SAVED_SCRIPT)
        self.assertIn("window.EdifyLive.saved()", body)
        # The fallback is the reload every page gave before.
        self.assertIn(": window.location.reload()", body)

    def test_a_reschedule_from_a_drawer_answers_in_place(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/my-plan/{self.activity.id}/reschedule",
            {
                "scheduled_date": (date.today() + timedelta(days=5)).isoformat(),
                "reason": "The head teacher asked for Friday.",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), SAVED_SCRIPT)
        self.assertEqual(response["HX-Trigger"], "close-drawer")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "rescheduled")

    def test_the_pages_the_officer_saves_from_carry_a_live_region(self):
        self.client.force_login(self.user)
        for url in ("/my-plan", f"/my-plan/{self.activity.id}"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-live-region")

    def test_a_live_read_is_stamped_with_the_servers_clock(self):
        self.client.force_login(self.user)
        response = self.client.get(
            "/my-plan", headers={"X-Requested-With": "EdifyLive"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response["X-Edify-Live-At"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"
        )
        plain = self.client.get("/my-plan")
        self.assertNotIn("X-Edify-Live-At", plain)
