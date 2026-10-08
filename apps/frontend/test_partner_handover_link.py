"""The link a hand-over's confirmation offers opens a page.

After a school is assigned to a partner the Planning page stays put and a
confirmation says where the work went, with a link to follow it. That link
was "/partner-assignments", which is no page: the Partner's own list is
"/partner/assignments" and staff cannot open it, so every assigner who
pressed "Open partner assignments" met a 404 (found 2026-10-08; the link
dated from 2026-09-18, when the confirmation stopped leaving the page).

It now opens Partner Oversight — the staff page a hand-over is followed on —
on the partner the school went to, and is offered only to a reader who can
open that page.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.frontend.views import planning_views
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

DEAD_PATH = "/partner-assignments"


class HandoverConfirmationLinkTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo = User.objects.create_user(
            email="handover-link-cceo@edify.org",
            name="Linking Officer",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.cceo, title="CCEO")
        region = Region.objects.create(name="Handover Link Region")
        district = District.objects.create(name="Handover Link District", region=region)
        sub_county = SubCounty.objects.create(
            name="Handover Link Sub", district=district
        )
        cls.schools = [
            School.objects.create(
                school_id=f"HANDOVER-LINK-{index}",
                name=f"Handover Link School {index}",
                region=region,
                district=district,
                sub_county=sub_county,
                school_type="client",
            )
            for index in range(2)
        ]
        for school in cls.schools:
            StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=school.id)
        cls.partner = Partner.objects.create(
            name="Handover Link Partner", active_status=True
        )

    def setUp(self):
        self.client.force_login(self.cceo)

    def link_in(self, response) -> str:
        """The address of the link the confirmation carries."""
        self.assertEqual(response.status_code, 200, response.content)
        body = response.content.decode()
        self.assertIn("data-planning-saved-toast", body)
        found = re.search(r'<a href="([^"]+)" class="underline font-bold">', body)
        self.assertIsNotNone(found, "the confirmation offers no link")
        return found.group(1).replace("&amp;", "&")

    def assert_opens_on_the_partner(self, response):
        link = self.link_in(response)
        self.assertNotIn(DEAD_PATH, link)
        self.assertEqual(link, f"/partner-oversight/?partner={self.partner.id}")
        self.assertContains(response, "Open Partner Oversight")

        page = self.client.get(link)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Partner Monitoring")
        self.assertContains(page, self.partner.name)

    def test_the_link_after_one_school_is_assigned_opens_partner_oversight(self):
        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.schools[0].school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
                "purpose": "Support visit.",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertTrue(
            PartnerAssignment.objects.filter(
                school=self.schools[0], partner=self.partner
            ).exists()
        )
        self.assert_opens_on_the_partner(response)

    def test_the_link_after_a_bulk_assignment_opens_partner_oversight(self):
        response = self.client.post(
            "/planning/bulk-action",
            {
                "action": "partner",
                "purpose_of_visit": "ssa_support",
                "school_ids": [school.school_id for school in self.schools],
                "partner_id": self.partner.id,
            },
        )

        self.assertEqual(
            PartnerAssignment.objects.filter(partner=self.partner).count(), 2
        )
        self.assert_opens_on_the_partner(response)

    def test_a_reader_who_cannot_open_partner_oversight_is_offered_no_link(self):
        """The Project Coordinator plans on this page and does not monitor
        Partner work: a link there would only refuse them."""
        coordinator = User.objects.create_user(
            email="handover-link-pc@edify.org",
            name="Planning Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            password="x",
            is_active=True,
        )

        self.assertEqual(
            planning_views._partner_work_link(coordinator, self.partner.id), ("", "")
        )
        self.assertEqual(
            planning_views._partner_work_link(self.cceo, self.partner.id),
            (
                f"/partner-oversight/?partner={self.partner.id}",
                "Open Partner Oversight",
            ),
        )

    def test_no_planning_view_names_the_page_that_does_not_exist(self):
        source = Path(planning_views.__file__).read_text()

        self.assertNotIn(f'"{DEAD_PATH}"', source)
