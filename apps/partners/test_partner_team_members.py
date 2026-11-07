"""A partner's team members schedule their own schools; the Partner Admin
runs the team and sees the money.

Owner, 2026-11-06: "the partner admin should be assigned by platform admin
becomes partner admin and they can add new team members. Add the button for
add new member of the partner portal under users. Partner admin is the only
who should be shown cost (40,000). Team members only have access to schools
assigned to them and their only work is to schedule. the scheduling drawer
should not have the cost (40000) labels". Asked, the owner chose: the cost is
hidden from team members only (the Partner Admin still sees it when
scheduling); a team member schedules and has My Plan; the team is run from a
new Users page.

A team member is a person on the roster with a login of their own who does
not lead the team (apps.partners.member_scope). The organisation's own login
and its Partner Admins are not team members.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners import member_logins, member_scope
from apps.partners.models import (
    Partner,
    PartnerAssignment,
    PartnerMember,
    PartnerSchoolMember,
)
from apps.schools.models import School

User = get_user_model()
PASSWORD = "StrongPassphrase!23"


def _sidebar_labels(user) -> set[str]:
    return {
        item["label"]
        for section in build_sidebar_for_user(user, "/partner/assigned-schools")
        for item in section["items"]
    }


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerTeamMembersTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="tm-admin@edify.test",
            name="Edify Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password=PASSWORD,
        )
        self.staff = StaffProfile.objects.create(
            user=self.admin, country="Uganda", title="Admin"
        )
        # The Partner Admin the platform Admin set up for the organisation.
        self.lead = User.objects.create_user(
            email="tm-lead@reading.test",
            name="Ruth Lead",
            roles=[EdifyRole.PARTNER_ADMIN.value],
            active_role=EdifyRole.PARTNER_ADMIN.value,
            password=PASSWORD,
        )
        self.org = Partner.objects.create(
            name="Reading Partners", user=self.lead, active_status=True
        )
        region = Region.objects.create(name="TM Region")
        district = District.objects.create(name="TM District", region=region)
        self.mine = School.objects.create(
            school_id="TM-001",
            name="Peter's School",
            region=region,
            district=district,
            school_type="client",
        )
        self.other = School.objects.create(
            school_id="TM-002",
            name="Someone Else's School",
            region=region,
            district=district,
            school_type="client",
        )
        item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
        )
        self.assignments = {}
        for school in (self.mine, self.other):
            self.assignments[school.id] = PartnerAssignment.objects.create(
                school=school,
                partner=self.org,
                assigning_staff_id=self.staff.id,
                monitoring_staff_id=self.staff.id,
                catalogue_item=item,
                catalogue_snapshot=item.snapshot(),
                purpose_of_visit="ssa_support",
                expected_activity_type="school_visit_ssa_collection",
                status="pending_scheduling",
            )
        self.peter = PartnerMember.objects.create(
            partner=self.org, name="Peter Okello", email="peter@reading.test"
        )
        PartnerSchoolMember.objects.create(
            partner=self.org, school=self.mine, member=self.peter
        )
        member_logins.create_login(
            self.org.id,
            self.peter.id,
            {"email": "peter@reading.test", "password": PASSWORD},
            self.lead,
        )
        self.peter.refresh_from_db()
        self.member = self.peter.user
        User.objects.filter(id=self.member.id).update(must_change_password=False)
        self.member.refresh_from_db()
        planned = timezone.localdate() + timedelta(days=14)
        self.activities = {
            school.id: Activity.objects.create(
                activity_type="school_visit",
                school=school,
                fy=get_operational_fy(planned),
                quarter=get_quarter_for_date(planned),
                planned_date=planned,
                assigned_partner_id=self.org.id,
                delivery_type="partner",
                status="scheduled",
            )
            for school in (self.mine, self.other)
        }

    # ── Who is a team member ──────────────────────────────────────────────
    def test_the_member_login_is_a_team_member_and_the_partner_admin_is_not(self):
        self.assertEqual(member_scope.team_member(self.member).id, self.peter.id)
        self.assertEqual(member_scope.member_school_ids(self.member), {self.mine.id})
        self.assertIsNone(member_scope.team_member(self.lead))
        self.assertIsNone(member_scope.member_school_ids(self.lead))
        self.assertIsNone(member_scope.team_member(self.admin))

    # ── The Users page ────────────────────────────────────────────────────
    def test_the_partner_admin_adds_members_from_a_users_page(self):
        self.assertIn("Users", _sidebar_labels(self.lead))
        self.client.force_login(self.lead)
        page = self.client.get("/partner/users").content.decode()
        self.assertIn(f'hx-get="/partners/{self.org.id}/members/drawer"', page)
        self.assertIn("Add member", page)
        self.assertIn("Peter Okello", page)
        self.assertIn("peter@reading.test", page)

        response = self.client.post(
            f"/partners/{self.org.id}/members",
            {"name": "Mary Atim", "role": "staff"},
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/partner/users",
        )
        self.assertEqual(response["HX-Redirect"], "/partner/users")
        self.assertTrue(
            PartnerMember.objects.filter(partner=self.org, name="Mary Atim").exists()
        )

    def test_a_team_member_has_no_users_page(self):
        self.assertNotIn("Users", _sidebar_labels(self.member))
        self.client.force_login(self.member)
        self.assertNotEqual(self.client.get("/partner/users").status_code, 200)

    # ── What a team member sees ───────────────────────────────────────────
    def test_a_team_members_sidebar_is_assigned_schools_and_my_plan(self):
        labels = _sidebar_labels(self.member)
        self.assertIn("Assigned Schools", labels)
        self.assertIn("My Plan", labels)
        for withheld in (
            "Assigned Activities",
            "Evidence",
            "Completed & Payments",
            "Calendar",
            "To-Do",
        ):
            self.assertNotIn(withheld, labels)
        # The Partner Admin keeps the whole portal.
        lead_labels = _sidebar_labels(self.lead)
        self.assertIn("Completed & Payments", lead_labels)
        self.assertIn("Evidence", lead_labels)

    def test_a_team_member_lands_on_assigned_schools(self):
        self.client.force_login(self.member)
        response = self.client.get("/home")
        self.assertRedirects(
            response, "/partner/assigned-schools", fetch_redirect_response=False
        )

    def test_assigned_schools_lists_only_the_members_schools(self):
        self.client.force_login(self.member)
        page = self.client.get("/partner/assigned-schools").content.decode()
        self.assertIn("Peter&#x27;s School", page)
        self.assertNotIn("Someone Else", page)

        self.client.force_login(self.lead)
        page = self.client.get("/partner/assigned-schools").content.decode()
        self.assertIn("Someone Else", page)

    def test_the_members_scheduling_drawer_has_no_cost(self):
        self.client.force_login(self.member)
        mine = self.assignments[self.mine.id]
        drawer = self.client.get(
            f"/partner/assignments/{mine.id}/schedule-drawer", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(drawer.status_code, 200)
        html = drawer.content.decode()
        self.assertIn('name="scheduled_date"', html)
        self.assertNotIn("data-partner-cost-preview", html)
        self.assertNotIn("UGX", html)

    def test_the_partner_admins_scheduling_drawer_keeps_the_cost(self):
        self.client.force_login(self.lead)
        mine = self.assignments[self.mine.id]
        html = self.client.get(
            f"/partner/assignments/{mine.id}/schedule-drawer", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn("data-partner-cost-preview", html)

    def test_a_team_member_cannot_open_another_members_school(self):
        self.client.force_login(self.member)
        other = self.assignments[self.other.id]
        for url in (
            f"/partner/assignments/{other.id}/schedule-drawer",
            f"/partner/assignments/{other.id}",
        ):
            self.assertEqual(
                self.client.get(url, HTTP_HX_REQUEST="true").status_code, 404, url
            )
        response = self.client.post(
            f"/partner/assignments/{other.id}/schedule-action",
            {"scheduled_date": (timezone.localdate() + timedelta(days=7)).isoformat()},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.status, "pending_scheduling")

    def test_a_team_member_only_schedules(self):
        self.client.force_login(self.member)
        mine = self.assignments[self.mine.id]
        for url in (
            "/partner/evidence",
            "/partner/completed",
            "/partner/assigned-activities",
            "/partner/invoices/new",
            f"/partners/{self.org.id}",
            f"/partner/assignments/{mine.id}/return-drawer",
            "/calendar",
            "/todos",
        ):
            self.assertNotEqual(
                self.client.get(url, HTTP_HX_REQUEST="true").status_code, 200, url
            )

    def test_a_team_members_my_plan_is_their_schools_without_money(self):
        self.client.force_login(self.member)
        page = self.client.get("/my-plan").content.decode()
        self.assertIn("Peter&#x27;s School", page)
        self.assertNotIn("Someone Else", page)
        self.assertNotIn("Send Invoice", page)
        self.assertNotIn("UGX", page)
        # Rescheduling is scheduling; delivering is the organisation's.
        mine = self.activities[self.mine.id]
        self.assertIn(f"/my-plan/{mine.id}/reschedule-drawer", page)
        self.assertNotIn(f"/partner/activities/{mine.id}/evidence", page)

    def test_a_team_member_cannot_reschedule_another_members_work(self):
        self.client.force_login(self.member)
        other = self.activities[self.other.id]
        response = self.client.get(
            f"/my-plan/{other.id}/reschedule-drawer", HTTP_HX_REQUEST="true"
        )
        self.assertNotEqual(response.status_code, 200)

    def test_the_partner_admins_my_plan_keeps_invoices(self):
        self.client.force_login(self.lead)
        page = self.client.get("/my-plan").content.decode()
        self.assertIn("Send Invoice", page)
        self.assertIn("Someone Else", page)
