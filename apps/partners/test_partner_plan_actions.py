"""A partner's My Plan row offers Complete and Cancel.

Owner, 2026-11-06: "On the action, can you add complete, cancel, it has only
reschedule and change team member". The menu is the Partner Admin's (a team
member only reschedules: apps.partners.member_scope). Complete opens the
partner's own completion — the form is uploaded and submitted to IA, which is
how partner work is verified (owner, 2026-10-14); Cancel opens the platform's
one cancel drawer, with its reason.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners import member_logins
from apps.partners.models import Partner, PartnerMember, PartnerSchoolMember
from apps.schools.models import School

User = get_user_model()
PASSWORD = "StrongPassphrase!23"


def _menu(page: str, activity_id: str) -> str:
    """The table row of one activity, with its Actions menu."""
    for row in re.findall(r"<tr\b.*?</tr>", page, re.S):
        if activity_id in row:
            return row
    raise AssertionError(f"no row for {activity_id}")


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerPlanActionsTests(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user(
            email="pa-lead@reading.test",
            name="Ruth Lead",
            roles=[EdifyRole.PARTNER_ADMIN.value],
            active_role=EdifyRole.PARTNER_ADMIN.value,
            password=PASSWORD,
        )
        self.org = Partner.objects.create(
            name="Reading Partners", user=self.lead, active_status=True
        )
        region = Region.objects.create(name="PA Region")
        district = District.objects.create(name="PA District", region=region)
        self.school = School.objects.create(
            school_id="PA-001",
            name="Hill Primary",
            region=region,
            district=district,
            school_type="client",
        )
        planned = timezone.localdate() + timedelta(days=10)
        common = {
            "activity_type": "school_visit",
            "school": self.school,
            "fy": get_operational_fy(planned),
            "quarter": get_quarter_for_date(planned),
            "planned_date": planned,
            "assigned_partner_id": self.org.id,
            "delivery_type": "partner",
        }
        self.scheduled = Activity.objects.create(**common, status="scheduled")
        self.started = Activity.objects.create(**common, status="in_progress")

    def _page(self, user) -> str:
        self.client.force_login(user)
        return self.client.get("/my-plan").content.decode()

    def test_a_scheduled_row_offers_complete_and_cancel(self):
        menu = _menu(self._page(self.lead), self.scheduled.id)
        self.assertIn(">Complete<", menu)
        self.assertIn(f'hx-get="/my-plan/{self.scheduled.id}/cancel-drawer"', menu)
        self.assertIn(">Cancel<", menu)
        # Reschedule and the team member stay.
        self.assertIn(">Reschedule<", menu)
        self.assertIn("team member", menu)

    def test_complete_starts_the_work_and_opens_its_upload(self):
        menu = _menu(self._page(self.lead), self.scheduled.id)
        self.assertIn(
            f'action="/partner/activities/{self.scheduled.id}/start-action"', menu
        )
        self.client.force_login(self.lead)
        response = self.client.post(
            f"/partner/activities/{self.scheduled.id}/start-action"
        )
        self.assertRedirects(
            response,
            f"/partner/activities/{self.scheduled.id}/evidence",
            fetch_redirect_response=False,
        )

    def test_started_work_completes_on_its_upload_page(self):
        menu = _menu(self._page(self.lead), self.started.id)
        self.assertIn(f'href="/partner/activities/{self.started.id}/evidence"', menu)
        self.assertIn(">Complete<", menu)
        self.assertIn(">Cancel<", menu)

    def test_the_partner_cancels_its_own_work_with_a_reason(self):
        self.client.force_login(self.lead)
        drawer = self.client.get(
            f"/my-plan/{self.scheduled.id}/cancel-drawer", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(drawer.status_code, 200)
        # The partner is the one cancelling: it is not told it is notified.
        self.assertNotIn("partner is notified", drawer.content.decode())
        self.client.post(
            f"/my-plan/{self.scheduled.id}/cancel",
            {"reason": "The school closed early for the term"},
            HTTP_HX_REQUEST="true",
        )
        self.scheduled.refresh_from_db()
        self.assertEqual(self.scheduled.status, "cancelled")

    def test_a_team_member_is_offered_neither(self):
        peter = PartnerMember.objects.create(
            partner=self.org, name="Peter Okello", email="pa-peter@reading.test"
        )
        PartnerSchoolMember.objects.create(
            partner=self.org, school=self.school, member=peter
        )
        member_logins.create_login(
            self.org.id,
            peter.id,
            {"email": "pa-peter@reading.test", "password": PASSWORD},
            self.lead,
        )
        peter.refresh_from_db()
        User.objects.filter(id=peter.user_id).update(must_change_password=False)
        menu = _menu(self._page(User.objects.get(id=peter.user_id)), self.scheduled.id)
        self.assertIn(">Reschedule<", menu)
        self.assertNotIn(">Complete<", menu)
        self.assertNotIn(">Cancel<", menu)
